"""Delete tool — remove documents from the knowledge vault."""

import json
from dataclasses import dataclass

from pydantic import BaseModel, Field
from vaultfs import VaultFS

from mcp.server.fastmcp import Context, FastMCP
from mcp.shared.exceptions import McpError
from mcp.types import ClientCapabilities, ElicitationCapability, ToolAnnotations

from .helpers import glob_match, resolve_path

_PROTECTED_FILES = {("/wiki/", "overview.md"), ("/wiki/", "log.md")}
_ALL_DOCUMENTS_PATTERNS = {"*", "**", "**/*", "/*", "/**", "/**/*"}


def _is_protected(doc: dict) -> bool:
    return (doc.get("path", ""), doc.get("filename", "")) in _PROTECTED_FILES


def _document_path(doc: dict) -> str:
    return doc.get("path", "") + doc.get("filename", "")


@dataclass(frozen=True)
class DeletePlan:
    """Exact set of documents shown to the user before approval."""

    pattern: str
    deletable: tuple[dict, ...]
    protected: tuple[dict, ...]

    @property
    def matched_count(self) -> int:
        return len(self.deletable) + len(self.protected)


class DeleteConfirmation(BaseModel):
    """Primitive-only schema required by MCP form elicitation."""

    confirm: bool = Field(
        title="Confirm deletion",
        description="Set to true to delete exactly the documents listed in the approval prompt.",
    )


class DeleteHandler:
    """Deletes documents from the knowledge vault."""

    def __init__(self, fs: VaultFS, kb: dict):
        self.fs = fs
        self.kb = kb
        self.kb_id = str(kb["id"])
        self.slug = kb["slug"]

    async def delete(self, ctx: Context, path: str) -> str:
        """Preview, approve, then delete documents matching a path or glob."""
        if not path or not path.strip():
            return "Error: path is required."
        path = path.strip()

        plan = await self._build_plan(path)
        if not plan.matched_count:
            return f"No documents matching `{path}` found in {self.slug}."

        if not plan.deletable:
            names = ", ".join(f"`{_document_path(d)}`" for d in plan.protected)
            return (
                f"Cannot delete {names} — these are structural wiki pages. "
                "Use `edit` or `append` to modify their content instead."
            )

        preview = self._format_preview(plan)
        if not self._client_supports_elicitation(ctx):
            return self._approval_unavailable(preview)

        try:
            approval = await ctx.elicit(message=preview, schema=DeleteConfirmation)
        except McpError:
            # A client can advertise elicitation but still reject the request
            # (for example, METHOD_NOT_FOUND from a partial implementation).
            return self._approval_unavailable(preview)

        if approval.action == "decline":
            return "Deletion declined. No documents were deleted."
        if approval.action == "cancel":
            return "Deletion cancelled. No documents were deleted."
        confirmed = getattr(getattr(approval, "data", None), "confirm", False)
        if approval.action != "accept" or not confirmed:
            return "Deletion was not explicitly confirmed. No documents were deleted."

        return await self._execute(plan)

    async def _build_plan(self, path: str) -> DeletePlan:
        matched = await self._find_documents(path)
        clears_entire_kb = path in _ALL_DOCUMENTS_PATTERNS
        protected = tuple(
            sorted(
                (d for d in matched if _is_protected(d) and not clears_entire_kb),
                key=_document_path,
            )
        )
        deletable = tuple(
            sorted(
                (d for d in matched if clears_entire_kb or not _is_protected(d)),
                key=_document_path,
            )
        )
        return DeletePlan(pattern=path, deletable=deletable, protected=protected)

    async def _execute(self, plan: DeletePlan) -> str:
        """Delete only documents whose IDs and paths still match the preview."""
        current_docs = await self.fs.list_documents(self.kb_id)
        current_by_id = {str(d["id"]): d for d in current_docs}
        deletable = []
        changed = []
        for approved in plan.deletable:
            current = current_by_id.get(str(approved["id"]))
            if (
                current
                and _document_path(current) == _document_path(approved)
                and (
                    plan.pattern in _ALL_DOCUMENTS_PATTERNS
                    or not _is_protected(current)
                )
            ):
                deletable.append(current)
            else:
                changed.append(approved)

        if not deletable:
            return "No documents were deleted because the approved documents changed before deletion."

        doc_ids = [str(d["id"]) for d in deletable]
        deleted_count = await self.fs.archive_documents(doc_ids)
        if not deleted_count:
            return "No documents were deleted because the approved documents changed before deletion."

        deleted = deletable
        if deleted_count != len(deletable):
            remaining = {
                str(d["id"])
                for d in await self.fs.list_documents(self.kb_id)
            }
            deleted = [d for d in deletable if str(d["id"]) not in remaining]
            changed.extend(d for d in deletable if str(d["id"]) in remaining)

        # Delete local files only after the database mutation succeeds. A DB
        # failure must never leave the index pointing at a file we removed.
        self.fs.delete_from_disk(deleted)

        return self._format_response(
            len(deleted),
            deleted,
            list(plan.protected),
            changed,
        )

    async def _find_documents(self, path: str) -> list[dict]:
        """Find documents by exact path or glob pattern."""
        if "*" in path or "?" in path:
            docs = await self.fs.list_documents(self.kb_id)
            if path in _ALL_DOCUMENTS_PATTERNS:
                return docs
            glob_pat = "/" + path.lstrip("/") if not path.startswith("/") else path
            return [d for d in docs if glob_match(d["path"] + d["filename"], glob_pat)]

        dir_path, filename = resolve_path(path)
        doc = await self.fs.get_document(self.kb_id, filename, dir_path)
        return [doc] if doc else []

    def _format_preview(self, plan: DeletePlan) -> str:
        lines = [
            f"The pattern {json.dumps(plan.pattern)} matched {plan.matched_count} document(s) "
            f"in knowledge base {json.dumps(self.slug)}.",
            f"Exact documents to delete ({len(plan.deletable)}):",
        ]
        lines.extend(
            f"  {index}. {json.dumps(_document_path(doc))}"
            for index, doc in enumerate(plan.deletable, 1)
        )
        if plan.protected:
            lines.append(f"Protected structural pages that will be skipped ({len(plan.protected)}):")
            lines.extend(f"  - {json.dumps(_document_path(doc))}" for doc in plan.protected)
        lines.extend(
            (
                "This action cannot be undone in every Supavault deployment.",
                "Set `confirm` to true only if you approve deleting exactly the documents listed above.",
            )
        )
        return "\n".join(lines)

    @staticmethod
    def _client_supports_elicitation(ctx: Context) -> bool:
        try:
            session = ctx.request_context.session
        except (AttributeError, ValueError):
            # Lightweight Context fakes and compatible wrappers may not expose
            # the underlying session; ctx.elicit remains the source of truth.
            return True
        return session.check_client_capability(
            ClientCapabilities(elicitation=ElicitationCapability())
        )

    @staticmethod
    def _approval_unavailable(preview: str) -> str:
        return (
            f"{preview}\n\n"
            "No documents were deleted because this MCP client could not provide interactive "
            "approval. Use a client with MCP elicitation support or delete the documents in "
            "the Supavault app."
        )

    def _format_response(
        self,
        deleted_count: int,
        deletable: list[dict],
        protected: list[dict],
        changed: list[dict],
    ) -> str:
        """Build the response message listing deleted and skipped files."""
        lines = [f"Deleted {deleted_count} document(s):\n"]
        for d in deletable:
            lines.append(f"  {_document_path(d)}")
        if protected:
            names = ", ".join(f"`{_document_path(d)}`" for d in protected)
            lines.append(f"\nSkipped (protected): {names}")
        if changed:
            names = ", ".join(f"`{_document_path(d)}`" for d in changed)
            lines.append(f"\nSkipped (changed after approval): {names}")
        return "\n".join(lines)


def register(mcp: FastMCP, get_user_id, fs_factory) -> None:

    @mcp.tool(
        name="delete",
        description=(
            "Delete documents or wiki pages from the knowledge vault.\n\n"
            "Provide a path to delete a single file, or a glob pattern to delete multiple.\n"
            "Examples:\n"
            "- `path=\"old-notes.md\"` — delete a single file\n"
            "- `path=\"/wiki/drafts/*\"` — delete all files in a folder\n"
            "- `path=\"/wiki/**\"` — delete the entire wiki\n\n"
            "Note: overview.md and log.md are protected from targeted/folder deletion. "
            "A whole-knowledge-base pattern includes them after approval.\n"
            "The complete match list is shown for interactive approval before anything is deleted.\n"
            "Returns a list of deleted files. This action cannot be undone."
        ),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True),
    )
    async def delete(ctx: Context, knowledge_base: str, path: str) -> str:
        user_id = get_user_id(ctx)
        fs = fs_factory(user_id)
        kb = await fs.resolve_kb(knowledge_base)
        if not kb:
            return f"Knowledge base '{knowledge_base}' not found."

        handler = DeleteHandler(fs, kb)
        return await handler.delete(ctx, path)
