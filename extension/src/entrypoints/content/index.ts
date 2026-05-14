import {
  applyHighlights,
  captureAnchor,
  findAllMarks,
  findMark,
  HIGHLIGHT_CLASS,
  makeHighlight,
  unwrapAllMarks,
  unwrapById,
  wrapRange,
} from "@/lib/highlights";
import type { Highlight } from "@/lib/api";
import {
  getDocumentByUrl,
  getHighlights,
  replaceHighlights,
} from "@/lib/api";
import { getApiUrl } from "@/lib/settings";

export default defineContentScript({
  matches: ["<all_urls>"],
  runAt: "document_idle",
  cssInjectionMode: "manifest",
  async main() {
    if (isRestrictedPage()) return;
    new HighlightController();
  },
});

const STYLE_ID = "llmwiki-highlight-style";

function injectStyle(): void {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
    mark.${HIGHLIGHT_CLASS} {
      background-color: rgba(255, 224, 84, 0.65);
      color: inherit;
      padding: 0 1px;
      border-radius: 2px;
      cursor: pointer;
    }
    mark.${HIGHLIGHT_CLASS}[data-llmwiki-comment="1"]::after {
      content: "💬";
      font-size: 0.7em;
      margin-left: 2px;
      opacity: 0.7;
    }
    .llmwiki-pill {
      position: absolute;
      z-index: 2147483647;
      background: #1f1f1f;
      color: #fff;
      border-radius: 999px;
      padding: 4px 6px;
      display: inline-flex;
      gap: 2px;
      box-shadow: 0 6px 18px rgba(0, 0, 0, 0.25);
      font: 500 12px/1 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .llmwiki-pill button {
      background: transparent;
      border: none;
      color: #fff;
      cursor: pointer;
      padding: 4px 8px;
      border-radius: 999px;
      font-size: 12px;
    }
    .llmwiki-pill button:hover {
      background: rgba(255, 255, 255, 0.12);
    }
    .llmwiki-popover {
      position: absolute;
      z-index: 2147483647;
      background: #fff;
      color: #111;
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      box-shadow: 0 10px 28px rgba(0, 0, 0, 0.18);
      padding: 10px;
      width: 280px;
      font: 13px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .llmwiki-popover textarea {
      width: 100%;
      box-sizing: border-box;
      min-height: 64px;
      max-height: 220px;
      resize: vertical;
      border: 1px solid #d1d5db;
      border-radius: 6px;
      padding: 6px 8px;
      font: inherit;
      color: #111;
      background: #fff;
      outline: none;
    }
    .llmwiki-popover textarea:focus {
      border-color: #6366f1;
      box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.2);
    }
    .llmwiki-popover .llmwiki-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
      margin-top: 8px;
    }
    .llmwiki-popover .llmwiki-row .llmwiki-actions {
      display: inline-flex;
      gap: 6px;
    }
    .llmwiki-popover button {
      cursor: pointer;
      border: none;
      border-radius: 6px;
      padding: 5px 10px;
      font: 500 12px/1 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .llmwiki-popover .llmwiki-save {
      background: #111;
      color: #fff;
    }
    .llmwiki-popover .llmwiki-cancel {
      background: transparent;
      color: #555;
    }
    .llmwiki-popover .llmwiki-delete {
      background: transparent;
      color: #b00020;
    }
  `;
  document.documentElement.appendChild(style);
}

function isRestrictedPage(): boolean {
  const proto = location.protocol;
  if (proto === "chrome:" || proto === "chrome-extension:" || proto === "edge:" || proto === "about:") {
    return true;
  }
  if (location.host === "chrome.google.com" && location.pathname.startsWith("/webstore")) {
    return true;
  }
  if (window.top !== window) return true;
  return false;
}

const TRACKING_PARAMS = new Set([
  "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
  "utm_id", "utm_name", "utm_brand", "utm_social",
  "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src",
  "_branch_match_id", "igshid",
]);

function canonicalizeUrl(href: string): string {
  try {
    const u = new URL(href);
    u.hash = "";
    const keep = new URLSearchParams();
    u.searchParams.forEach((v, k) => {
      if (!TRACKING_PARAMS.has(k.toLowerCase())) keep.append(k, v);
    });
    u.search = keep.toString() ? `?${keep.toString()}` : "";
    if (u.pathname.length > 1 && u.pathname.endsWith("/")) {
      u.pathname = u.pathname.replace(/\/+$/, "");
    }
    return u.toString();
  } catch {
    return href;
  }
}

class HighlightController {
  private highlights: Highlight[] = [];
  private documentId: string | null = null;
  private knowledgeBaseId: string | null = null;
  private version: number | null = null;
  private apiUrl: string | null = null;
  private accessToken: string | null = null;
  private pill: HTMLElement | null = null;
  private popover: HTMLElement | null = null;
  private saveTimer: number | null = null;
  private isSaving = false;

  constructor() {
    injectStyle();
    this.bootstrap();
    document.addEventListener("mouseup", this.onMouseUp);
    document.addEventListener("mousedown", this.onMouseDown);
    document.addEventListener("click", this.onMarkClick, true);
    document.addEventListener("scroll", this.onViewportChange, true);
    window.addEventListener("resize", this.onViewportChange);
    chrome.runtime.onMessage.addListener(this.onRuntimeMessage);
  }

  private async bootstrap() {
    try {
      this.apiUrl = await getApiUrl();
      const session = await chrome.runtime.sendMessage({ type: "GET_SESSION" });
      this.accessToken = session?.accessToken ?? null;
      // No token → user hasn't signed in. Highlight UI still works locally;
      // network sync starts once they sign in via the popup. Don't call the
      // API and don't log noise on every page load.
      if (!this.accessToken) return;
      const url = canonicalizeUrl(location.href);
      let doc;
      try {
        doc = await getDocumentByUrl(this.apiUrl, this.accessToken, url);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        // 401 means the stored session is stale; sign-in flow will refresh.
        // Anything else is worth logging.
        if (!msg.includes("401")) {
          console.warn("[llmwiki] by-url lookup failed:", err);
        }
        return;
      }
      if (!doc) return;
      this.documentId = doc.id;
      this.knowledgeBaseId = doc.knowledge_base_id;
      this.version = doc.version;
      this.highlights = doc.highlights ?? [];
      // Defer apply slightly so SPA hydration settles
      window.requestAnimationFrame(() => applyHighlights(this.highlights));
    } catch (err) {
      console.warn("[llmwiki] bootstrap failed:", err);
    }
  }

  private async refreshAfterSave(documentId: string) {
    if (!this.apiUrl) return;
    this.documentId = documentId;
    try {
      const fresh = await getHighlights(this.apiUrl, this.accessToken, documentId);
      this.version = fresh.version;
      // Server may have stripped/normalized; trust its copy if non-empty
      if (fresh.highlights && fresh.highlights.length) {
        this.highlights = fresh.highlights;
      }
    } catch {
      this.version = 0;
    }
    // Flush any pending in-memory highlights that were captured pre-save
    if (this.highlights.length) this.scheduleSave();
  }

  private onRuntimeMessage = (msg: { type: string; documentId?: string }, _sender: any, sendResponse: (r: unknown) => void) => {
    if (msg.type === "GET_PAGE_HIGHLIGHTS") {
      sendResponse({ highlights: this.highlights });
      return true;
    }
    if (msg.type === "DOCUMENT_SAVED" && msg.documentId) {
      this.refreshAfterSave(msg.documentId).then(() => sendResponse({ ok: true }));
      return true;
    }
    return undefined;
  };

  private onMouseDown = (e: MouseEvent) => {
    const target = e.target as Node;
    if (this.pill && this.pill.contains(target)) return;
    if (this.popover && this.popover.contains(target)) return;
    this.removePill();
    if (this.popover && !this.popover.contains(target)) {
      this.removePopover();
    }
  };

  private onMouseUp = (e: MouseEvent) => {
    if (this.popover && this.popover.contains(e.target as Node)) return;
    if (this.pill && this.pill.contains(e.target as Node)) return;
    setTimeout(() => this.maybeShowPill(), 0);
  };

  private onMarkClick = (e: MouseEvent) => {
    const target = e.target as HTMLElement;
    if (!target || !target.classList?.contains(HIGHLIGHT_CLASS)) return;
    const id = target.getAttribute("data-llmwiki-hl-id");
    if (!id) return;
    e.preventDefault();
    e.stopPropagation();
    this.openPopoverForExisting(id, target);
  };

  private onViewportChange = () => {
    this.removePill();
    this.removePopover();
  };

  private maybeShowPill() {
    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return;
    const range = sel.getRangeAt(0);
    const text = range.toString();
    if (!text || text.trim().length < 2) return;
    if (!isRangeInDocument(range)) return;
    this.showPillForRange(range);
  }

  private showPillForRange(range: Range) {
    this.removePill();
    const rect = range.getBoundingClientRect();
    if (!rect.width && !rect.height) return;
    const pill = document.createElement("div");
    pill.className = "llmwiki-pill";
    const highlightBtn = document.createElement("button");
    highlightBtn.textContent = "Highlight";
    highlightBtn.onclick = (ev) => {
      ev.preventDefault();
      this.handleHighlight(range, false);
    };
    const noteBtn = document.createElement("button");
    noteBtn.textContent = "Note";
    noteBtn.onclick = (ev) => {
      ev.preventDefault();
      this.handleHighlight(range, true);
    };
    pill.appendChild(highlightBtn);
    pill.appendChild(noteBtn);
    document.body.appendChild(pill);
    const top = window.scrollY + rect.top - pill.offsetHeight - 8;
    const left = window.scrollX + rect.left + rect.width / 2 - pill.offsetWidth / 2;
    pill.style.top = `${Math.max(window.scrollY + 4, top)}px`;
    pill.style.left = `${Math.max(window.scrollX + 4, left)}px`;
    this.pill = pill;
  }

  private removePill() {
    if (this.pill && this.pill.parentNode) {
      this.pill.parentNode.removeChild(this.pill);
    }
    this.pill = null;
  }

  private removePopover() {
    if (this.popover && this.popover.parentNode) {
      this.popover.parentNode.removeChild(this.popover);
    }
    this.popover = null;
  }

  private async handleHighlight(range: Range, withNote: boolean) {
    this.removePill();
    const anchor = captureAnchor(range);
    if (!anchor) return;
    const highlight = makeHighlight(anchor, null);
    const wrapped = wrapRange(range, highlight.id);
    // If wrapping fails (multi-node range crossing inline tags), still keep the
    // anchor so it persists, the LLM sees it, and the next page-load reapply
    // pass can attempt text-scan resolution into a single text node.
    this.highlights.push(highlight);
    window.getSelection()?.removeAllRanges();
    if (withNote && wrapped) {
      const mark = findMark(highlight.id);
      if (mark) this.openPopoverForExisting(highlight.id, mark);
    } else if (withNote) {
      // No wrap means no anchor element to point a popover at — open at the
      // last range bounding rect via a transient anchor element.
      this.openPopoverAtRect(highlight.id, range.getBoundingClientRect());
    }
    this.scheduleSave();
  }

  private openPopoverAtRect(id: string, rect: DOMRect) {
    const highlight = this.highlights.find((h) => h.id === id);
    if (!highlight) return;
    this.removePopover();
    const popover = document.createElement("div");
    popover.className = "llmwiki-popover";
    const textarea = document.createElement("textarea");
    textarea.placeholder = "Add a note…";
    textarea.value = highlight.comment ?? "";
    popover.appendChild(textarea);
    const row = document.createElement("div");
    row.className = "llmwiki-row";
    const actions = document.createElement("div");
    actions.className = "llmwiki-actions";
    const cancel = document.createElement("button");
    cancel.className = "llmwiki-cancel";
    cancel.textContent = "Cancel";
    cancel.onclick = () => this.removePopover();
    const save = document.createElement("button");
    save.className = "llmwiki-save";
    save.textContent = "Save";
    save.onclick = () => {
      const value = textarea.value.trim() || null;
      highlight.comment = value;
      this.removePopover();
      this.scheduleSave();
    };
    actions.appendChild(cancel);
    actions.appendChild(save);
    row.appendChild(actions);
    popover.appendChild(row);
    document.body.appendChild(popover);
    popover.style.top = `${window.scrollY + rect.bottom + 6}px`;
    popover.style.left = `${window.scrollX + rect.left}px`;
    this.popover = popover;
    setTimeout(() => textarea.focus(), 0);
  }

  private openPopoverForExisting(id: string, mark: HTMLElement) {
    const highlight = this.highlights.find((h) => h.id === id);
    if (!highlight) return;
    this.removePopover();
    const rect = mark.getBoundingClientRect();
    const popover = document.createElement("div");
    popover.className = "llmwiki-popover";
    const textarea = document.createElement("textarea");
    textarea.placeholder = "Add a note…";
    textarea.value = highlight.comment ?? "";
    popover.appendChild(textarea);

    const row = document.createElement("div");
    row.className = "llmwiki-row";
    const del = document.createElement("button");
    del.className = "llmwiki-delete";
    del.textContent = "Delete";
    del.onclick = () => {
      this.deleteHighlight(id);
      this.removePopover();
    };
    const actions = document.createElement("div");
    actions.className = "llmwiki-actions";
    const cancel = document.createElement("button");
    cancel.className = "llmwiki-cancel";
    cancel.textContent = "Cancel";
    cancel.onclick = () => this.removePopover();
    const save = document.createElement("button");
    save.className = "llmwiki-save";
    save.textContent = "Save";
    save.onclick = () => {
      const value = textarea.value.trim() || null;
      highlight.comment = value;
      // A multi-node highlight has multiple marks under the same id — keep
      // the comment indicator in sync across all of them.
      for (const m of findAllMarks(highlight.id)) {
        m.toggleAttribute("data-llmwiki-comment", !!value);
      }
      this.removePopover();
      this.scheduleSave();
    };
    actions.appendChild(cancel);
    actions.appendChild(save);
    row.appendChild(del);
    row.appendChild(actions);
    popover.appendChild(row);
    document.body.appendChild(popover);

    const top = window.scrollY + rect.bottom + 6;
    const left = window.scrollX + rect.left;
    popover.style.top = `${top}px`;
    popover.style.left = `${left}px`;
    this.popover = popover;
    setTimeout(() => textarea.focus(), 0);
  }

  private deleteHighlight(id: string) {
    unwrapById(id);
    this.highlights = this.highlights.filter((h) => h.id !== id);
    this.scheduleSave();
  }

  private scheduleSave() {
    if (this.saveTimer) {
      window.clearTimeout(this.saveTimer);
    }
    this.saveTimer = window.setTimeout(() => this.flushSave(), 600);
  }

  private async flushSave() {
    // Without a saved document, highlights live in-memory only until the user
    // hits "Save to LLM Wiki" — SaveForm will pull them via GET_PAGE_HIGHLIGHTS.
    if (!this.documentId || !this.apiUrl) return;
    if (this.isSaving) {
      // Re-queue
      this.scheduleSave();
      return;
    }
    this.isSaving = true;
    try {
      const result = await replaceHighlights(
        this.apiUrl,
        this.accessToken,
        this.documentId,
        this.highlights,
        this.version ?? undefined,
      );
      this.version = result.version;
    } catch (err) {
      const conflict = (err as { conflict?: boolean })?.conflict;
      if (conflict && this.documentId) {
        // Refetch and merge — last writer wins on duplicates by id
        try {
          const fresh = await getHighlights(this.apiUrl, this.accessToken, this.documentId);
          const ids = new Set(this.highlights.map((h) => h.id));
          const merged = [...this.highlights];
          for (const h of fresh.highlights) {
            if (!ids.has(h.id)) merged.push(h);
          }
          this.highlights = merged;
          this.version = fresh.version;
          this.isSaving = false;
          this.scheduleSave();
          return;
        } catch (e) {
          console.warn("[llmwiki] reconcile failed:", e);
        }
      } else {
        console.warn("[llmwiki] save highlights failed:", err);
      }
    } finally {
      this.isSaving = false;
    }
  }
}

function isRangeInDocument(range: Range): boolean {
  const startEl = range.startContainer.parentElement;
  if (!startEl) return false;
  // Skip selections inside form fields, code editors, etc.
  if (startEl.closest("input,textarea,[contenteditable='true']")) return false;
  return true;
}
