import {
  applyHighlights,
  captureAnchor,
  findAllMarks,
  findMark,
  HIGHLIGHT_CLASS,
  makeHighlight,
  unwrapById,
  wrapRange,
} from "@/lib/highlights";
import type { Highlight } from "@/lib/api";
import {
  deleteHighlight,
  fetchKnowledgeBases,
  getDocumentByUrl,
  getHighlights,
  saveWebPage,
  upsertHighlight,
} from "@/lib/api";
import {
  getMode,
  getApiUrl,
  getSelectedFolderPath,
  getSelectedKnowledgeBaseId,
  isDomainDisabled,
  setSelectedKnowledgeBaseId,
  type Mode,
} from "@/lib/settings";
import { runtimeMessageWithDeadline, withDeadline } from "@/lib/deadline";
import { capturePageHtml } from "@/lib/page-capture";
import {
  ensureContentStarted,
  type ContentStartupState,
} from "@/lib/content-startup";

type ContentGlobalState = ContentStartupState<HighlightController>;

export default defineContentScript({
  // Runtime-injected only; WXT folds `matches` into host_permissions, so keep it narrow.
  matches: ["https://api.llmwiki.app/*"],
  registration: "runtime",
  runAt: "document_idle",
  cssInjectionMode: "manual",
  async main() {
    const state = window as unknown as ContentGlobalState;
    try {
      await ensureContentStarted(state, {
        isEligible: async () => {
          if (isRestrictedPage() || isLlmWikiAppPage()) return false;
          return !(await isDomainDisabled(location.hostname));
        },
        createController: () => new HighlightController(),
        bootstrap: (controller) => controller.initialize(),
        dispose: (controller) => controller.dispose(),
      });
    } catch (error) {
      console.warn("[llmwiki] content startup failed:", error);
    }
  },
});

function isLlmWikiAppPage(): boolean {
  // Meta tag rather than a hostname allowlist, so any deploy host of the wiki matches.
  return !!document.querySelector('meta[name="llmwiki-app"]');
}

const STYLE_ID = "llmwiki-highlight-style";
const PENDING_PAGE_PREFIX = "llmwiki_pending_page:";
const CONTENT_STORAGE_TIMEOUT_MS = 5_000;

interface SessionResponse {
  accessToken: string | null;
  userId: string | null;
}

interface PendingPageState {
  url: string;
  title: string;
  documentId: string | null;
  knowledgeBaseId: string | null;
  version: number | null;
  folderPath: string;
  highlights: Highlight[];
  deletedHighlightIds: string[];
  updatedAt: string;
}

function injectStyle(): void {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
    mark.${HIGHLIGHT_CLASS} {
      position: relative;
      background-color: rgba(255, 224, 84, 0.65);
      color: inherit;
      padding: 0 1px;
      border-radius: 2px;
      cursor: pointer;
      transition: background-color 120ms ease, box-shadow 120ms ease;
    }
    mark.${HIGHLIGHT_CLASS}:hover {
      background-color: rgba(255, 213, 43, 0.78);
      box-shadow: 0 0 0 1px rgba(217, 119, 6, 0.24);
    }
    mark.${HIGHLIGHT_CLASS}[data-llmwiki-comment="1"]::after {
      content: "💬";
      font-size: 0.7em;
      margin-left: 2px;
      opacity: 0.7;
    }
    mark.${HIGHLIGHT_CLASS}[data-llmwiki-comment-text]:hover::before {
      content: attr(data-llmwiki-comment-text);
      position: absolute;
      left: 0;
      bottom: calc(100% + 8px);
      z-index: 2147483647;
      box-sizing: border-box;
      width: max-content;
      max-width: min(280px, 70vw);
      white-space: pre-wrap;
      background: #111827;
      color: #fff;
      border: 1px solid rgba(255, 255, 255, 0.12);
      border-radius: 8px;
      padding: 8px 10px;
      box-shadow: 0 12px 32px rgba(0, 0, 0, 0.24);
      font: 500 12px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      pointer-events: none;
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
      padding: 8px;
      width: min(320px, calc(100vw - 20px));
      font: 13px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .llmwiki-popover textarea {
      width: 100%;
      box-sizing: border-box;
      min-height: 64px;
      max-height: 180px;
      overflow-y: auto;
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
      transition: background-color .12s ease, color .12s ease;
    }
    .llmwiki-popover .llmwiki-save {
      background: #111;
      color: #fff;
    }
    .llmwiki-popover .llmwiki-save:hover {
      background: #000;
    }
    .llmwiki-popover .llmwiki-cancel {
      background: transparent;
      color: #555;
    }
    .llmwiki-popover .llmwiki-cancel:hover {
      background: #f1f1f1;
      color: #111;
    }
    .llmwiki-popover .llmwiki-delete {
      background: transparent;
      color: #b00020;
    }
    .llmwiki-popover .llmwiki-delete:hover {
      background: #fdecef;
    }
    .llmwiki-toast {
      position: fixed;
      right: 16px;
      bottom: 16px;
      z-index: 2147483647;
      display: flex;
      align-items: center;
      gap: 8px;
      max-width: 280px;
      border: 1px solid #bbf7d0;
      border-radius: 8px;
      background: #ecfdf5;
      color: #047857;
      box-shadow: 0 10px 28px rgba(0, 0, 0, 0.16);
      padding: 9px 11px;
      font: 600 13px/1.3 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
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
  private deletedHighlightIds = new Set<string>();
  private documentId: string | null = null;
  private knowledgeBaseId: string | null = null;
  private folderPath = "/webclipper/";
  private mode: Mode = "cloud";
  private version: number | null = null;
  private apiUrl: string | null = null;
  private accessToken: string | null = null;
  private pill: HTMLElement | null = null;
  private popover: HTMLElement | null = null;
  private saveTimer: number | null = null;
  private toastTimer: number | null = null;
  private isSaving = false;
  private restoredPendingState = false;
  private autoSavePromise: Promise<boolean> | null = null;
  private autoSaveIncludedHighlightIds = new Set<string>();
  private disposed = false;
  private listenersAttached = false;

  async initialize(): Promise<void> {
    await this.bootstrap();
    this.assertActive();
    injectStyle();
    this.attachListeners();
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    if (this.saveTimer) window.clearTimeout(this.saveTimer);
    if (this.toastTimer) window.clearTimeout(this.toastTimer);
    this.saveTimer = null;
    this.toastTimer = null;
    this.removePill();
    this.removePopover();
    document.querySelector(".llmwiki-toast")?.remove();

    this.detachListeners();
    document.getElementById(STYLE_ID)?.remove();
  }

  private attachListeners(): void {
    if (this.listenersAttached) return;
    // Set first so dispose() cleans up if a Chrome API throws during extension invalidation.
    this.listenersAttached = true;
    document.addEventListener("mouseup", this.onMouseUp);
    document.addEventListener("mousedown", this.onMouseDown);
    document.addEventListener("click", this.onMarkClick, true);
    document.addEventListener("scroll", this.onViewportChange, true);
    window.addEventListener("resize", this.onViewportChange);
    chrome.runtime.onMessage.addListener(this.onRuntimeMessage);
  }

  private detachListeners(): void {
    if (!this.listenersAttached) return;
    document.removeEventListener("mouseup", this.onMouseUp);
    document.removeEventListener("mousedown", this.onMouseDown);
    document.removeEventListener("click", this.onMarkClick, true);
    document.removeEventListener("scroll", this.onViewportChange, true);
    window.removeEventListener("resize", this.onViewportChange);
    try {
      chrome.runtime.onMessage.removeListener(this.onRuntimeMessage);
    } catch {
      // Chrome APIs can throw after extension context invalidation.
    }
    this.listenersAttached = false;
  }

  private assertActive(): void {
    if (this.disposed) throw new Error("Content controller was disposed during startup");
  }

  private async ensureSession(): Promise<string | null> {
    // Never send the cloud Supabase token to a user-configured local URL.
    if (this.mode === "local") {
      this.accessToken = null;
      return null;
    }
    const session = await runtimeMessageWithDeadline<SessionResponse | undefined>(
      { type: "GET_SESSION" },
      5_000,
      "Timed out while checking the extension session",
    );
    this.accessToken = session?.accessToken ?? null;
    return this.accessToken;
  }

  private async bootstrap(): Promise<void> {
    const [mode, apiUrl, knowledgeBaseId, folderPath] = await withDeadline(
      Promise.all([
        getMode(),
        getApiUrl(),
        getSelectedKnowledgeBaseId(),
        getSelectedFolderPath(),
      ]),
      CONTENT_STORAGE_TIMEOUT_MS,
      "Content settings storage timed out",
    );
    this.assertActive();
    this.mode = mode;
    this.apiUrl = apiUrl;
    this.knowledgeBaseId = knowledgeBaseId;
    this.folderPath = folderPath;

    await this.ensureSession();
    this.assertActive();
    if (this.mode !== "local" && !this.accessToken) return;

    await this.restorePendingPageState();
    this.assertActive();
    const url = canonicalizeUrl(location.href);
    let doc;
    try {
      doc = await getDocumentByUrl(this.apiUrl, this.accessToken, url);
      this.assertActive();
    } catch (err) {
      this.assertActive();
      const msg = err instanceof Error ? err.message : String(err);
      if (shouldWarnForLookupFailure(msg)) {
        console.warn("[llmwiki] by-url lookup failed:", err);
      }
      if (this.highlights.length || this.deletedHighlightIds.size) this.scheduleSave();
      return;
    }
    if (!doc) {
      if (this.highlights.length || this.deletedHighlightIds.size) this.scheduleSave();
      return;
    }
    this.documentId = doc.id;
    this.knowledgeBaseId = doc.knowledge_base_id;
    this.version = doc.version;
    this.highlights = mergeHighlightsById(doc.highlights ?? [], this.highlights);
    this.dropDeletedHighlights();
    // Let SPA hydration settle before mutating the DOM.
    window.requestAnimationFrame(() => {
      if (!this.disposed) applyHighlights(this.highlights);
    });
    if (this.highlights.length || this.deletedHighlightIds.size) this.scheduleSave();
  }

  private async refreshAfterSave(documentId: string, flushPending = true) {
    if (!this.apiUrl) return;
    this.documentId = documentId;
    await this.ensureSession();
    try {
      const fresh = await getHighlights(this.apiUrl, this.accessToken, documentId);
      this.version = fresh.version;
      if (fresh.highlights && fresh.highlights.length) {
        this.highlights = fresh.highlights;
      }
    } catch (err) {
      console.warn("[llmwiki] refresh after save failed; resetting version:", err);
      this.version = 0;
    }
    if (flushPending && this.highlights.length) this.scheduleSave();
  }

  private onRuntimeMessage = (msg: { type: string; documentId?: string }, sender: chrome.runtime.MessageSender, sendResponse: (r: unknown) => void) => {
    if (sender.id !== chrome.runtime.id) return false;
    if (msg.type === "GET_PAGE_HIGHLIGHTS") {
      sendResponse({ highlights: this.highlights });
      return false;
    }
    if (msg.type === "DOCUMENT_SAVED" && msg.documentId) {
      void this.refreshAfterSave(msg.documentId).then(
        () => sendResponse({ ok: true }),
        (error: unknown) => sendResponse({
          ok: false,
          error: error instanceof Error ? error.message : "Could not refresh saved document",
        }),
      );
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

  private onViewportChange = (event?: Event) => {
    const target = event?.target;
    if (this.popover && target instanceof Node && this.popover.contains(target)) {
      return;
    }
    this.removePill();
    this.removePopover();
  };

  private maybeShowPill() {
    if (this.mode !== "local" && !this.accessToken) {
      void this.ensureSession().then((token) => {
        if (token) this.maybeShowPill();
      }).catch(() => {
        this.showToast("Could not reach the extension. Try again.");
      });
      return;
    }
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
    // Keep the anchor even if wrapping fails; the next page load retries resolution.
    this.highlights.push(highlight);
    this.deletedHighlightIds.delete(highlight.id);
    this.savePendingPageState();
    window.getSelection()?.removeAllRanges();
    if (withNote && wrapped) {
      const mark = findMark(highlight.id);
      if (mark) this.openPopoverForExisting(highlight.id, mark, { discardOnCancel: true });
    } else if (withNote) {
      this.openPopoverAtRect(highlight.id, range.getBoundingClientRect(), { discardOnCancel: true });
    } else {
      this.persistHighlight(highlight, "Highlight saved");
    }
  }

  private discardLocalHighlight(id: string) {
    unwrapById(id);
    this.highlights = this.highlights.filter((h) => h.id !== id);
    this.deletedHighlightIds.delete(id);
    if (this.highlights.length || this.deletedHighlightIds.size) {
      this.savePendingPageState();
    } else {
      this.clearPendingPageState();
    }
  }

  private openPopoverAtRect(
    id: string,
    rect: DOMRect,
    options: { discardOnCancel?: boolean } = {},
  ) {
    const highlight = this.highlights.find((h) => h.id === id);
    if (!highlight) return;
    this.removePill();
    this.removePopover();
    const popover = document.createElement("div");
    popover.className = "llmwiki-popover";
    const textarea = document.createElement("textarea");
    textarea.placeholder = "Add a note…";
    textarea.value = highlight.comment ?? "";
    this.configureCommentTextarea(textarea);
    popover.appendChild(textarea);
    const row = document.createElement("div");
    row.className = "llmwiki-row";
    const actions = document.createElement("div");
    actions.className = "llmwiki-actions";
    const cancel = document.createElement("button");
    cancel.className = "llmwiki-cancel";
    cancel.textContent = "Cancel";
    cancel.onclick = () => {
      if (options.discardOnCancel) this.discardLocalHighlight(id);
      this.removePopover();
    };
    const save = document.createElement("button");
    save.className = "llmwiki-save";
    save.textContent = "Save";
    save.onclick = () => {
      const value = textarea.value.trim() || null;
      highlight.comment = value;
      this.savePendingPageState();
      this.removePopover();
      this.syncCommentMarkers(highlight);
      this.persistHighlight(highlight, "Comment saved");
    };
    actions.appendChild(cancel);
    actions.appendChild(save);
    row.appendChild(actions);
    popover.appendChild(row);
    document.body.appendChild(popover);
    this.positionPopover(popover, rect);
    this.popover = popover;
    setTimeout(() => textarea.focus(), 0);
  }

  private openPopoverForExisting(
    id: string,
    mark: HTMLElement,
    options: { discardOnCancel?: boolean } = {},
  ) {
    const highlight = this.highlights.find((h) => h.id === id);
    if (!highlight) return;
    this.removePill();
    this.removePopover();
    const rect = mark.getBoundingClientRect();
    const popover = document.createElement("div");
    popover.className = "llmwiki-popover";
    const textarea = document.createElement("textarea");
    textarea.placeholder = "Add a note…";
    textarea.value = highlight.comment ?? "";
    this.configureCommentTextarea(textarea);
    popover.appendChild(textarea);

    const row = document.createElement("div");
    row.className = "llmwiki-row";
    const del = document.createElement("button");
    del.className = "llmwiki-delete";
    del.textContent = "Delete";
    del.onclick = () => {
      if (options.discardOnCancel) this.discardLocalHighlight(id);
      else this.deleteHighlight(id);
      this.removePopover();
    };
    const actions = document.createElement("div");
    actions.className = "llmwiki-actions";
    const cancel = document.createElement("button");
    cancel.className = "llmwiki-cancel";
    cancel.textContent = "Cancel";
    cancel.onclick = () => {
      if (options.discardOnCancel) this.discardLocalHighlight(id);
      this.removePopover();
    };
    const save = document.createElement("button");
    save.className = "llmwiki-save";
    save.textContent = "Save";
    save.onclick = () => {
      highlight.comment = textarea.value.trim() || null;
      this.syncCommentMarkers(highlight);
      this.savePendingPageState();
      this.removePopover();
      this.persistHighlight(highlight, "Comment saved");
    };
    actions.appendChild(cancel);
    actions.appendChild(save);
    row.appendChild(del);
    row.appendChild(actions);
    popover.appendChild(row);
    document.body.appendChild(popover);

    this.positionPopover(popover, rect);
    this.popover = popover;
    setTimeout(() => textarea.focus(), 0);
  }

  private configureCommentTextarea(textarea: HTMLTextAreaElement) {
    const maxHeight = 180;
    const fit = () => {
      textarea.style.height = "auto";
      textarea.style.height = `${Math.min(textarea.scrollHeight, maxHeight)}px`;
      textarea.style.overflowY = textarea.scrollHeight > maxHeight ? "auto" : "hidden";
    };
    textarea.addEventListener("input", fit);
    setTimeout(fit, 0);
  }

  private positionPopover(popover: HTMLElement, rect: DOMRect) {
    const margin = 8;
    const below = window.scrollY + rect.bottom + 6;
    const above = window.scrollY + rect.top - popover.offsetHeight - 6;
    const maxTop = window.scrollY + window.innerHeight - popover.offsetHeight - margin;
    const top = below <= maxTop
      ? below
      : Math.max(window.scrollY + margin, above);
    const maxLeft = window.scrollX + window.innerWidth - popover.offsetWidth - margin;
    const left = Math.min(
      Math.max(window.scrollX + margin, window.scrollX + rect.left),
      Math.max(window.scrollX + margin, maxLeft),
    );
    popover.style.top = `${top}px`;
    popover.style.left = `${left}px`;
  }

  private deleteHighlight(id: string) {
    unwrapById(id);
    this.highlights = this.highlights.filter((h) => h.id !== id);
    this.deletedHighlightIds.add(id);
    this.savePendingPageState();
    this.persistDelete(id);
  }

  private mergeServerHighlights(result: { version: number; highlights?: Highlight[] }) {
    this.version = result.version;
    if (!result.highlights) return;
    const localById = new Map(this.highlights.map((h) => [h.id, h]));
    for (const h of result.highlights) {
      localById.set(h.id, h);
    }
    this.highlights = Array.from(localById.values());
  }

  private dropDeletedHighlights() {
    if (!this.deletedHighlightIds.size) return;
    this.highlights = this.highlights.filter((h) => !this.deletedHighlightIds.has(h.id));
  }

  private pendingStorageKey(): string {
    return `${PENDING_PAGE_PREFIX}${canonicalizeUrl(location.href)}`;
  }

  private async restorePendingPageState() {
    const key = this.pendingStorageKey();
    const result = await withDeadline(
      chrome.storage.local.get(key),
      CONTENT_STORAGE_TIMEOUT_MS,
      "Pending highlight storage timed out",
    );
    this.assertActive();
    const pending = result[key] as PendingPageState | undefined;
    if (!pending || pending.url !== canonicalizeUrl(location.href)) return;

    this.documentId = this.documentId ?? pending.documentId ?? null;
    this.knowledgeBaseId = this.knowledgeBaseId ?? pending.knowledgeBaseId ?? null;
    this.version = this.version ?? pending.version ?? null;
    this.folderPath = pending.folderPath || this.folderPath;
    this.highlights = mergeHighlightsById(this.highlights, pending.highlights ?? []);
    this.deletedHighlightIds = new Set(pending.deletedHighlightIds ?? []);
    this.dropDeletedHighlights();
    this.restoredPendingState = true;

    if (this.highlights.length) {
      window.requestAnimationFrame(() => {
        if (!this.disposed) applyHighlights(this.highlights);
      });
    }
  }

  private savePendingPageState() {
    const state: PendingPageState = {
      url: canonicalizeUrl(location.href),
      title: document.title || location.href,
      documentId: this.documentId,
      knowledgeBaseId: this.knowledgeBaseId,
      version: this.version,
      folderPath: this.folderPath,
      highlights: this.highlights,
      deletedHighlightIds: Array.from(this.deletedHighlightIds),
      updatedAt: new Date().toISOString(),
    };
    chrome.storage.local.set({ [this.pendingStorageKey()]: state }).catch((err) => {
      console.warn("[llmwiki] save pending highlights failed:", err);
    });
  }

  private clearPendingPageState() {
    chrome.storage.local.remove(this.pendingStorageKey()).catch(() => {});
  }

  private syncCommentMarkers(highlight: Highlight) {
    const comment = highlight.comment?.trim() || null;
    for (const mark of findAllMarks(highlight.id)) {
      if (comment) {
        mark.setAttribute("data-llmwiki-comment", "1");
        mark.setAttribute("data-llmwiki-comment-text", comment);
        mark.setAttribute("title", comment);
      } else {
        mark.removeAttribute("data-llmwiki-comment");
        mark.removeAttribute("data-llmwiki-comment-text");
        mark.removeAttribute("title");
      }
    }
  }

  private showToast(message: string) {
    const existing = document.querySelector(".llmwiki-toast");
    if (existing?.parentNode) existing.parentNode.removeChild(existing);
    if (this.toastTimer) window.clearTimeout(this.toastTimer);

    const toast = document.createElement("div");
    toast.className = "llmwiki-toast";
    toast.textContent = message;
    document.body.appendChild(toast);

    this.toastTimer = window.setTimeout(() => {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
      this.toastTimer = null;
    }, 1800);
  }

  private captureCleanHtml(): string {
    return capturePageHtml();
  }

  private async resolveKnowledgeBaseId(): Promise<string | null> {
    if (this.knowledgeBaseId) return this.knowledgeBaseId;

    const stored = await getSelectedKnowledgeBaseId();
    if (stored) {
      this.knowledgeBaseId = stored;
      return stored;
    }

    if (!this.apiUrl) return null;
    const list = await fetchKnowledgeBases(this.apiUrl, this.accessToken);
    const first = list[0]?.id ?? null;
    if (first) {
      this.knowledgeBaseId = first;
      await setSelectedKnowledgeBaseId(first);
    }
    return first;
  }

  private async ensureDocumentSavedForHighlights(): Promise<boolean> {
    if (this.documentId) return true;
    if (this.autoSavePromise) return this.autoSavePromise;

    this.autoSavePromise = this.createDocumentFromCurrentPage()
      .finally(() => {
        this.autoSavePromise = null;
      });
    return this.autoSavePromise;
  }

  private async createDocumentFromCurrentPage(): Promise<boolean> {
    try {
      this.apiUrl = this.apiUrl ?? await getApiUrl();
      await this.ensureSession();
      if (this.mode !== "local" && !this.accessToken) {
        this.showToast("Sign in to save highlights");
        return false;
      }

      const knowledgeBaseId = await this.resolveKnowledgeBaseId();
      if (!knowledgeBaseId) {
        this.showToast("Choose a knowledge base first");
        return false;
      }

      this.showToast("Saving article...");
      const highlightsToSave = this.highlights.length ? [...this.highlights] : [];
      this.autoSaveIncludedHighlightIds = new Set(highlightsToSave.map((h) => h.id));
      const result = await saveWebPage(this.apiUrl, this.accessToken, knowledgeBaseId, {
        url: canonicalizeUrl(location.href),
        title: document.title || location.href,
        path: this.folderPath,
        html: this.captureCleanHtml(),
        highlights: highlightsToSave.length ? highlightsToSave : undefined,
      });
      this.knowledgeBaseId = knowledgeBaseId;
      this.documentId = result.id;
      if (typeof result.version === "number") this.version = result.version;
      if (result.highlights) this.highlights = result.highlights;
      await this.refreshAfterSave(result.id, false);
      this.showToast("Article saved with highlight");
      return true;
    } catch (err) {
      const message = err instanceof Error ? err.message : "";
      if (message.includes("too large to save") || message.includes("too complex to save")) {
        console.warn("[llmwiki] page capture rejected:", err);
        this.showToast("Page is too large to save");
        return false;
      }
      console.warn("[llmwiki] auto-save failed; cached locally:", err);
      this.savePendingPageState();
      this.showToast("Saved locally; will retry");
      return false;
    }
  }

  private async persistHighlight(highlight: Highlight, successMessage?: string) {
    const hadDocument = !!this.documentId;
    if (!this.documentId) {
      const saved = await this.ensureDocumentSavedForHighlights();
      if (!saved || !this.documentId) {
        return;
      }
      // Re-posting would overwrite the server's textAnchor-enriched copy from create_web_clip.
      if (
        successMessage === "Highlight saved" &&
        this.autoSaveIncludedHighlightIds.has(highlight.id)
      ) {
        if (!this.restoredPendingState) this.clearPendingPageState();
        return;
      }
    }

    if (!this.apiUrl) {
      if (successMessage) this.showToast(successMessage);
      return;
    }
    try {
      await this.ensureSession();
      const existing = this.highlights.find((h) => h.id === highlight.id);
      const payload = existing
        ? {
            ...existing,
            ...highlight,
            textAnchor: highlight.textAnchor ?? existing.textAnchor,
          }
        : highlight;
      const result = await upsertHighlight(
        this.apiUrl,
        this.accessToken,
        this.documentId,
        payload,
      );
      this.mergeServerHighlights(result);
      this.deletedHighlightIds.delete(highlight.id);
      if (!this.restoredPendingState && !this.deletedHighlightIds.size) this.clearPendingPageState();
      if (successMessage && (hadDocument || successMessage !== "Highlight saved")) {
        this.showToast(successMessage);
      }
    } catch (err) {
      console.warn("[llmwiki] save highlight failed; cached locally:", err);
      this.savePendingPageState();
      this.showToast("Saved locally; will retry");
      this.scheduleSave();
    }
  }

  private async persistDelete(id: string) {
    if (!this.documentId || !this.apiUrl) {
      this.savePendingPageState();
      return;
    }
    try {
      await this.ensureSession();
      const result = await deleteHighlight(
        this.apiUrl,
        this.accessToken,
        this.documentId,
        id,
      );
      this.version = result.version;
      this.deletedHighlightIds.delete(id);
      if (!this.restoredPendingState && !this.deletedHighlightIds.size) this.clearPendingPageState();
    } catch (err) {
      console.warn("[llmwiki] delete highlight failed; cached locally:", err);
      this.savePendingPageState();
      this.showToast("Saved locally; will retry");
      this.scheduleSave();
    }
  }

  private scheduleSave() {
    if (this.disposed) return;
    if (this.saveTimer) {
      window.clearTimeout(this.saveTimer);
    }
    this.saveTimer = window.setTimeout(() => this.flushSave(), 600);
  }

  private async flushSave() {
    if (!this.apiUrl) return;
    if (this.isSaving) {
      this.scheduleSave();
      return;
    }
    this.isSaving = true;
    try {
      await this.ensureSession();
      const saved = await this.ensureDocumentSavedForHighlights();
      if (!saved || !this.documentId) {
        this.savePendingPageState();
        return;
      }

      this.dropDeletedHighlights();
      for (const id of Array.from(this.deletedHighlightIds)) {
        const result = await deleteHighlight(
          this.apiUrl,
          this.accessToken,
          this.documentId,
          id,
        );
        this.version = result.version;
        this.deletedHighlightIds.delete(id);
      }

      for (const highlight of this.highlights) {
        const result = await upsertHighlight(
          this.apiUrl,
          this.accessToken,
          this.documentId,
          highlight,
        );
        this.mergeServerHighlights(result);
      }

      const fresh = await getHighlights(this.apiUrl, this.accessToken, this.documentId);
      this.version = fresh.version;
      this.highlights = mergeHighlightsById(fresh.highlights ?? [], this.highlights);
      this.restoredPendingState = false;
      this.clearPendingPageState();
    } catch (err) {
      const conflict = (err as { conflict?: boolean })?.conflict;
      if (conflict && this.documentId) {
        try {
          const fresh = await getHighlights(this.apiUrl, this.accessToken, this.documentId);
          const ids = new Set(this.highlights.map((h) => h.id));
          const merged = [...this.highlights];
          for (const h of fresh.highlights) {
            if (!ids.has(h.id)) merged.push(h);
          }
          this.highlights = merged;
          this.dropDeletedHighlights();
          this.version = fresh.version;
          this.isSaving = false;
          this.scheduleSave();
          return;
        } catch (e) {
          console.warn("[llmwiki] reconcile failed:", e);
        }
      } else {
        console.warn("[llmwiki] save highlights failed; cached locally:", err);
        this.savePendingPageState();
        this.showToast("Saved locally; will retry");
      }
    } finally {
      this.isSaving = false;
    }
  }
}

function mergeHighlightsById(serverHighlights: Highlight[], localHighlights: Highlight[]): Highlight[] {
  const merged = new Map<string, Highlight>();
  for (const highlight of serverHighlights) {
    merged.set(highlight.id, highlight);
  }
  for (const highlight of localHighlights) {
    const existing = merged.get(highlight.id);
    merged.set(
      highlight.id,
      existing
        ? {
            ...existing,
            ...highlight,
            textAnchor: highlight.textAnchor ?? existing.textAnchor,
          }
        : highlight,
    );
  }
  return Array.from(merged.values());
}

function shouldWarnForLookupFailure(message: string): boolean {
  return (
    !message.includes("401") &&
    !message.includes("Failed to fetch") &&
    !message.includes("Network error")
  );
}

function isRangeInDocument(range: Range): boolean {
  const startEl = range.startContainer.parentElement;
  if (!startEl) return false;
  if (startEl.closest("input,textarea,[contenteditable='true']")) return false;
  return true;
}
