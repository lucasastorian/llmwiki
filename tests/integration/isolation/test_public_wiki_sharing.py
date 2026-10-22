"""Wiki sharing isolation: ownership, public-only anon reads of /wiki/ docs, revocation TOCTOU, cross-KB assets, slug reservation."""

import pytest

from tests.helpers.jwt import auth_headers
from tests.integration.isolation.conftest import (
    DOC_A2_ID,
    DOC_A_ID,
    DOC_B_ID,
    KB_A_ID,
    KB_B_ID,
    USER_A_ID,
    USER_B_ID,
)


async def publish_kb(pool, kb_id: str, slug: str) -> None:
    """Flip a KB to visibility='public' with the given slug, bypassing the API."""
    await pool.execute(
        "UPDATE knowledge_bases "
        "SET visibility = 'public', public_slug = $1, "
        "    visibility_updated_at = now(), published_at = now() "
        "WHERE id = $2",
        slug, kb_id,
    )


async def set_visibility(pool, kb_id: str, visibility: str) -> None:
    await pool.execute(
        "UPDATE knowledge_bases SET visibility = $1::kb_visibility, "
        "visibility_updated_at = now() WHERE id = $2",
        visibility, kb_id,
    )


async def insert_source_doc(pool, kb_id: str, user_id: str, doc_id: str) -> None:
    """Insert a non-wiki document (path NOT under /wiki/)."""
    await pool.execute(
        "INSERT INTO documents (id, knowledge_base_id, user_id, filename, title, path, "
        "file_type, status, content, version, document_number) "
        "VALUES ($1, $2, $3, 'raw.pdf', 'Raw Source', '/sources/', 'pdf', 'ready', NULL, 1, "
        "(SELECT COALESCE(MAX(document_number), 0) + 1 FROM documents WHERE knowledge_base_id = $2))",
        doc_id, kb_id, user_id,
    )


async def set_document_number(pool, doc_id: str, n: int) -> None:
    await pool.execute("UPDATE documents SET document_number = $1 WHERE id = $2", n, doc_id)


class FakeS3:
    def __init__(self, store: dict[str, bytes] | None = None):
        self.store = store or {}
        self.calls: list[str] = []

    async def download_bytes(self, key: str) -> bytes:
        self.calls.append(key)
        if key not in self.store:
            raise KeyError(key)
        return self.store[key]


@pytest.fixture
def fake_s3(client):
    from main import app
    fake = FakeS3()
    app.state.s3_service = fake
    yield fake
    app.state.s3_service = None


class TestSharingOwnership:

    async def test_owner_can_publish_with_valid_slug(self, client, pool):
        resp = await client.patch(
            f"/v1/knowledge-bases/{KB_A_ID}/sharing",
            headers=auth_headers(USER_A_ID),
            json={"visibility": "public", "public_slug": "alice-public-wiki"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["visibility"] == "public"
        assert body["public_slug"] == "alice-public-wiki"
        assert body["published_at"] is not None

    async def test_cross_tenant_patch_returns_404_full_stack(self, client, pool):
        resp = await client.patch(
            f"/v1/knowledge-bases/{KB_B_ID}/sharing",
            headers=auth_headers(USER_A_ID),
            json={"visibility": "public", "public_slug": "alice-grabs-bob"},
        )
        assert resp.status_code == 404
        row = await pool.fetchrow(
            "SELECT visibility::text AS v, public_slug FROM knowledge_bases WHERE id = $1",
            KB_B_ID,
        )
        assert row["v"] == "private"
        assert row["public_slug"] is None

    async def test_cross_tenant_patch_returns_404_without_rls(self, client_no_rls, pool):
        resp = await client_no_rls.patch(
            f"/v1/knowledge-bases/{KB_B_ID}/sharing",
            headers=auth_headers(USER_A_ID),
            json={"visibility": "public", "public_slug": "alice-grabs-bob-no-rls"},
        )
        assert resp.status_code == 404
        row = await pool.fetchrow(
            "SELECT visibility::text AS v, public_slug FROM knowledge_bases WHERE id = $1",
            KB_B_ID,
        )
        assert row["v"] == "private"
        assert row["public_slug"] is None


class TestSharingSlugSemantics:

    async def test_first_publish_without_slug_returns_400(self, client):
        resp = await client.patch(
            f"/v1/knowledge-bases/{KB_A_ID}/sharing",
            headers=auth_headers(USER_A_ID),
            json={"visibility": "public"},
        )
        assert resp.status_code == 400
        assert "slug" in resp.json()["detail"].lower()

    async def test_republish_without_slug_preserves_existing(self, client, pool):
        await publish_kb(pool, KB_A_ID, "alice-keeps-slug")
        await set_visibility(pool, KB_A_ID, "private")

        resp = await client.patch(
            f"/v1/knowledge-bases/{KB_A_ID}/sharing",
            headers=auth_headers(USER_A_ID),
            json={"visibility": "public"},
        )
        assert resp.status_code == 200
        assert resp.json()["public_slug"] == "alice-keeps-slug"

    async def test_private_patch_with_slug_does_not_reserve(self, client, pool):
        resp = await client.patch(
            f"/v1/knowledge-bases/{KB_A_ID}/sharing",
            headers=auth_headers(USER_A_ID),
            json={"visibility": "private", "public_slug": "contested-name"},
        )
        assert resp.status_code == 200
        assert resp.json()["public_slug"] is None

        # A private PATCH leaves the slug NULL (CASE in the UPDATE), so Bob can still claim it.
        resp = await client.patch(
            f"/v1/knowledge-bases/{KB_B_ID}/sharing",
            headers=auth_headers(USER_B_ID),
            json={"visibility": "public", "public_slug": "contested-name"},
        )
        assert resp.status_code == 200
        assert resp.json()["public_slug"] == "contested-name"

    async def test_slug_collision_returns_409(self, client, pool):
        await publish_kb(pool, KB_A_ID, "the-taken-slug")
        resp = await client.patch(
            f"/v1/knowledge-bases/{KB_B_ID}/sharing",
            headers=auth_headers(USER_B_ID),
            json={"visibility": "public", "public_slug": "the-taken-slug"},
        )
        assert resp.status_code == 409
        assert "taken" in resp.json()["detail"].lower()

    @pytest.mark.parametrize("bad", [
        "-leading",
        "trailing-",
        "a",
        "a" * 81,
        "bad_slug",
        "bad slug",
        "bad!slug",
    ])
    async def test_bad_slug_returns_400(self, client, bad):
        resp = await client.patch(
            f"/v1/knowledge-bases/{KB_A_ID}/sharing",
            headers=auth_headers(USER_A_ID),
            json={"visibility": "public", "public_slug": bad},
        )
        # 400 from the server-side regex, 422 from Pydantic max_length=80.
        assert resp.status_code in (400, 422)


class TestPublicReadIsolation:

    async def test_anon_cannot_read_private_or_shared(self, client, pool):
        # Same KB, walked through visibility states; only public should 200.
        await pool.execute(
            "UPDATE knowledge_bases SET public_slug = 'transitioning' WHERE id = $1",
            KB_A_ID,
        )
        for v in ("private", "shared"):
            await set_visibility(pool, KB_A_ID, v)
            resp = await client.get("/v1/public/wiki/transitioning")
            assert resp.status_code == 404, f"{v} leaked"

        await set_visibility(pool, KB_A_ID, "public")
        resp = await client.get("/v1/public/wiki/transitioning")
        assert resp.status_code == 200

    async def test_anon_revoked_wiki_immediately_404s(self, client, pool):
        await publish_kb(pool, KB_A_ID, "alice-revoke-test")
        assert (await client.get("/v1/public/wiki/alice-revoke-test")).status_code == 200

        await set_visibility(pool, KB_A_ID, "private")
        assert (await client.get("/v1/public/wiki/alice-revoke-test")).status_code == 404

    async def test_public_wiki_excludes_sources_and_includes_author(self, client, pool):
        await insert_source_doc(pool, KB_A_ID, USER_A_ID, "11112222-1111-1111-1111-111111111111")
        await publish_kb(pool, KB_A_ID, "alice-shaped")

        resp = await client.get("/v1/public/wiki/alice-shaped")
        assert resp.status_code == 200
        body = resp.json()
        assert body["kb"]["author_name"] == "Alice"
        # /wiki/notes.md is in seed data; /sources/raw.pdf must NOT be.
        paths = {d["path"] for d in body["documents"]}
        assert paths == {"/wiki/"}, f"unexpected paths: {paths}"

    async def test_public_wiki_response_has_no_store_cache(self, client, pool):
        await publish_kb(pool, KB_A_ID, "alice-cache-check")
        resp = await client.get("/v1/public/wiki/alice-cache-check")
        assert resp.status_code == 200
        assert resp.headers.get("cache-control") == "no-store, must-revalidate"

    async def test_public_read_excludes_other_public_kbs(self, client, pool):
        """Guards the docs JOIN keeping its kb.public_slug predicate."""
        await publish_kb(pool, KB_A_ID, "alice-public")
        await publish_kb(pool, KB_B_ID, "bob-public")

        resp = await client.get("/v1/public/wiki/alice-public")
        assert resp.status_code == 200
        body = resp.json()
        assert body["kb"]["public_slug"] == "alice-public"
        assert body["kb"]["author_name"] == "Alice"
        # Bob's notes.md shares Alice's path/filename, so assert by content.
        for d in body["documents"]:
            assert "Bob" not in (d.get("content") or ""), (
                f"Bob's content leaked into Alice's public wiki: {d}"
            )


class TestPublicAssetIsolation:

    async def test_asset_serves_wiki_doc(self, client, pool, fake_s3):
        await set_document_number(pool, DOC_A_ID, 7)
        await publish_kb(pool, KB_A_ID, "alice-assets")

        # Key follows {user_id}/{doc_id}/source.md per HostedPublicWikiService.get_asset_key.
        expected_key = f"{USER_A_ID}/{DOC_A_ID}/source.md"
        fake_s3.store[expected_key] = b"# Hello from Alice"

        resp = await client.get("/v1/public/wiki/alice-assets/assets/7")
        assert resp.status_code == 200
        assert resp.content == b"# Hello from Alice"
        assert resp.headers["content-type"].startswith("text/markdown")
        assert resp.headers["cache-control"] == "no-store, must-revalidate"
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert fake_s3.calls == [expected_key]

    async def test_active_asset_types_download_instead_of_rendering_inline(self, client, pool, fake_s3):
        await pool.execute(
            "UPDATE documents SET filename = 'unsafe.html', file_type = 'html' WHERE id = $1",
            DOC_A_ID,
        )
        await set_document_number(pool, DOC_A_ID, 12)
        await publish_kb(pool, KB_A_ID, "alice-html-asset")
        expected_key = f"{USER_A_ID}/{DOC_A_ID}/tagged.html"
        fake_s3.store[expected_key] = b"<script>alert(1)</script>"

        resp = await client.get("/v1/public/wiki/alice-html-asset/assets/12")
        assert resp.status_code == 200
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["content-disposition"] == 'attachment; filename="tagged.html"'

    async def test_asset_rejects_source_doc(self, client, pool, fake_s3):
        await set_document_number(pool, DOC_A2_ID, 8)  # DOC_A2 is at path '/'
        await publish_kb(pool, KB_A_ID, "alice-no-sources")

        resp = await client.get("/v1/public/wiki/alice-no-sources/assets/8")
        assert resp.status_code == 404
        assert fake_s3.calls == []

    async def test_asset_rejects_cross_kb_document(self, client, pool, fake_s3):
        await set_document_number(pool, DOC_A_ID, 9)
        await set_document_number(pool, DOC_B_ID, 9)
        await publish_kb(pool, KB_A_ID, "alice-cross-kb")
        # Bob's KB is still private.

        resp = await client.get("/v1/public/wiki/alice-cross-kb/assets/9")
        assert all(USER_B_ID not in k and DOC_B_ID not in k for k in fake_s3.calls), (
            f"Bob's S3 key leaked into a public Alice request: {fake_s3.calls}"
        )
        # 404 is also fine when the fake S3 holds no object for Alice's doc 9.
        if resp.status_code == 200:
            assert all(USER_A_ID in k and DOC_A_ID in k for k in fake_s3.calls)

    async def test_asset_revoked_kb_404s(self, client, pool, fake_s3):
        await set_document_number(pool, DOC_A_ID, 11)
        await publish_kb(pool, KB_A_ID, "alice-revoke-asset")
        fake_s3.store[f"{USER_A_ID}/{DOC_A_ID}/source.md"] = b"data"

        assert (await client.get("/v1/public/wiki/alice-revoke-asset/assets/11")).status_code == 200

        await set_visibility(pool, KB_A_ID, "private")
        assert (await client.get("/v1/public/wiki/alice-revoke-asset/assets/11")).status_code == 404


class TestRevocationTOCTOU:

    async def test_revoke_between_request_arrival_and_query_blocks_response(self, client, pool):
        """KB metadata, author, and docs are read in one statement gated on visibility, so a flip just before it leaks nothing."""
        await publish_kb(pool, KB_A_ID, "toctou-test")

        class _RevokingPoolProxy:
            def __init__(self, real_pool, kb_id):
                self._pool = real_pool
                self._kb_id = kb_id
                self._revoked = False

            async def fetch(self, query, *args, **kwargs):
                if not self._revoked and "knowledge_bases" in query:
                    self._revoked = True
                    await self._pool.execute(
                        "UPDATE knowledge_bases SET visibility = 'private' WHERE id = $1",
                        self._kb_id,
                    )
                return await self._pool.fetch(query, *args, **kwargs)

            async def fetchrow(self, query, *args, **kwargs):
                return await self._pool.fetchrow(query, *args, **kwargs)

            async def execute(self, query, *args, **kwargs):
                return await self._pool.execute(query, *args, **kwargs)

            async def fetchval(self, query, *args, **kwargs):
                return await self._pool.fetchval(query, *args, **kwargs)

        from services.hosted import HostedPublicWikiService
        svc = HostedPublicWikiService(_RevokingPoolProxy(pool, KB_A_ID), s3=None)

        result = await svc.get_by_slug("toctou-test")
        assert result is None, (
            "TOCTOU leak: revoked KB returned content. Single-statement "
            "visibility gate was bypassed."
        )


class TestRLSStillScopesPublicKBs:
    """Public anon reads must not widen authenticated RLS: User B still can't see User A's KB row."""

    async def test_user_b_rls_cannot_see_user_a_public_kb(self, pool, rls_session):
        await publish_kb(pool, KB_A_ID, "alice-rls-still-tight")

        async with rls_session(USER_B_ID) as conn:
            row = await conn.fetchrow(
                "SELECT id FROM knowledge_bases WHERE public_slug = 'alice-rls-still-tight'",
            )
            assert row is None, "RLS leak: User B's session saw User A's public KB"
