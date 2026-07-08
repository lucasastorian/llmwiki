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

export default defineContentScript({
  // Injected on demand via chrome.scripting.executeScript when the popup opens
  // (under the activeTab grant) — never auto-mounted. `matches` is the API
  // origin only so WXT doesn't fold a broad host into the manifest.
  matches: ["https://api.llmwiki.app/*"],
  registration: "runtime",
  runAt: "document_idle",
  cssInjectionMode: "manual",
  async main() {
    const w = window as unknown as { __llmwikiLoaded?: boolean };
    if (w.__llmwikiLoaded) return;
    w.__llmwikiLoaded = true;
    if (isRestrictedPage()) return;
    if (isLlmWikiAppPage()) return;
    if (await isDomainDisabled(location.hostname)) return;
    new HighlightController();
  },
});

function isLlmWikiAppPage(): boolean {
  // The wiki ships its own in-app highlight UI; the extension must not double up.
  // Detection is via a meta tag in the wiki's root layout so this works on prod,
  // localhost, and any future deploy host without hostname allowlists.
  return !!document.querySelector('meta[name="llmwiki-app"]');
}

const STYLE_ID = "llmwiki-highlight-style";
const MAX_CAPTURED_IMAGES = 24;
const PENDING_PAGE_PREFIX = "llmwiki_pending_page:";
const LAZY_IMAGE_SRC_ATTRIBUTES = [
  "data-src",
  "data-original",
  "data-lazy-src",
  "data-hires",
  "data-url",
  "data-image",
  "data-full-url",
];
const LAZY_IMAGE_SRCSET_ATTRIBUTES = [
  "data-srcset",
  "data-lazy-srcset",
];

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

function largestSrcsetUrl(srcset: string): string {
  let bestUrl = "";
  let bestWidth = 0;
  for (const raw of srcset.split(",")) {
    const parts = raw.trim().split(/\s+/);
    if (!parts[0]) continue;
    const width = parts[1]?.endsWith("w")
      ? Number.parseInt(parts[1], 10)
      : 0;
    if (!bestUrl || width > bestWidth) {
      bestUrl = parts[0];
      bestWidth = width;
    }
  }
  try {
    return bestUrl ? new URL(bestUrl, location.href).toString() : "";
  } catch {
    return bestUrl;
  }
}

function absoluteImageUrl(value: string | null | undefined): string {
  if (!value) return "";
  const trimmed = value.trim();
  if (!trimmed) return "";
  try {
    return new URL(trimmed, location.href).toString();
  } catch {
    return trimmed;
  }
}

function pictureSourceUrl(img: HTMLImageElement): string {
  const picture = img.closest("picture");
  if (!picture) return "";
  for (const source of Array.from(picture.querySelectorAll("source"))) {
    const srcset = source.getAttribute("srcset") || source.getAttribute("data-srcset") || "";
    const best = largestSrcsetUrl(srcset);
    if (best) return best;
    const src = absoluteImageUrl(source.getAttribute("src"));
    if (src) return src;
  }
  return "";
}

function candidateImageUrl(img: HTMLImageElement): string {
  const directCandidates = [
    img.currentSrc,
    img.getAttribute("src"),
    img.src,
    largestSrcsetUrl(img.getAttribute("srcset") || ""),
    pictureSourceUrl(img),
    ...LAZY_IMAGE_SRC_ATTRIBUTES.map((attr) => img.getAttribute(attr)),
    ...LAZY_IMAGE_SRCSET_ATTRIBUTES.map((attr) => largestSrcsetUrl(img.getAttribute(attr) || "")),
  ];

  for (const candidate of directCandidates) {
    const src = absoluteImageUrl(candidate);
    if (src) return src;
  }
  return "";
}

function imageDimensions(img: HTMLImageElement): { width: number; height: number } {
  const rect = img.getBoundingClientRect();
  const widthAttr = Number.parseInt(img.getAttribute("width") || "", 10);
  const heightAttr = Number.parseInt(img.getAttribute("height") || "", 10);
  return {
    width: Math.round(rect.width || img.naturalWidth || widthAttr || 0),
    height: Math.round(rect.height || img.naturalHeight || heightAttr || 0),
  };
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

  private async ensureSession(): Promise<string | null> {
    // Local mode is intentionally unauthenticated, so never hand the cloud
    // Supabase token to a user-configured local URL.
    if (this.mode === "local") {
      this.accessToken = null;
      return null;
    }
    const session: SessionResponse | undefined = await chrome.runtime.sendMessage({ type: "GET_SESSION" });
    this.accessToken = session?.accessToken ?? null;
    return this.accessToken;
  }

  private async bootstrap() {
    try {
      this.mode = await getMode();
      this.apiUrl = await getApiUrl();
      this.knowledgeBaseId = await getSelectedKnowledgeBaseId();
      this.folderPath = await getSelectedFolderPath();
      await this.ensureSession();
      // In cloud mode, no token means the user is signed out. Keep the page
      // untouched until they sign in. Local mode is intentionally unauthenticated.
      if (this.mode !== "local" && !this.accessToken) return;
      await this.restorePendingPageState();
      const url = canonicalizeUrl(location.href);
      let doc;
      try {
        doc = await getDocumentByUrl(this.apiUrl, this.accessToken, url);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        // 401 means the stored session is stale; sign-in flow will refresh.
        // Network failures are expected when a selected local server is down.
        // Pending edits are already restored from chrome.storage and will
        // retry on the next sync opportunity, so do not spam extension logs.
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
      // Defer apply slightly so SPA hydration settles
      window.requestAnimationFrame(() => applyHighlights(this.highlights));
      if (this.highlights.length || this.deletedHighlightIds.size) this.scheduleSave();
    } catch (err) {
      console.warn("[llmwiki] bootstrap failed:", err);
    }
  }

  private async refreshAfterSave(documentId: string, flushPending = true) {
    if (!this.apiUrl) return;
    this.documentId = documentId;
    await this.ensureSession();
    try {
      const fresh = await getHighlights(this.apiUrl, this.accessToken, documentId);
      this.version = fresh.version;
      // Server may have stripped/normalized; trust its copy if non-empty
      if (fresh.highlights && fresh.highlights.length) {
        this.highlights = fresh.highlights;
      }
    } catch (err) {
      console.warn("[llmwiki] refresh after save failed; resetting version:", err);
      this.version = 0;
    }
    // Flush any pending in-memory highlights that were captured pre-save
    if (flushPending && this.highlights.length) this.scheduleSave();
  }

  private onRuntimeMessage = (msg: { type: string; documentId?: string }, sender: chrome.runtime.MessageSender, sendResponse: (r: unknown) => void) => {
    if (sender.id !== chrome.runtime.id) return false;
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
    // If wrapping fails (multi-node range crossing inline tags), still keep the
    // anchor so it persists, the LLM sees it, and the next page-load reapply
    // pass can attempt text-scan resolution into a single text node.
    this.highlights.push(highlight);
    this.deletedHighlightIds.delete(highlight.id);
    this.savePendingPageState();
    window.getSelection()?.removeAllRanges();
    if (withNote && wrapped) {
      const mark = findMark(highlight.id);
      if (mark) this.openPopoverForExisting(highlight.id, mark, { discardOnCancel: true });
    } else if (withNote) {
      // No wrap means no anchor element to point a popover at — open at the
      // last range bounding rect via a transient anchor element.
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
    try {
      const key = this.pendingStorageKey();
      const result = await chrome.storage.local.get(key);
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
        window.requestAnimationFrame(() => applyHighlights(this.highlights));
      }
    } catch (err) {
      console.warn("[llmwiki] restore pending highlights failed:", err);
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
    const clone = document.documentElement.cloneNode(true) as HTMLElement;
    clone.querySelectorAll(
      ".llmwiki-pill, .llmwiki-popover, .llmwiki-toast, #llmwiki-highlight-style",
    ).forEach((el) => el.remove());
    clone.querySelectorAll(`mark.${HIGHLIGHT_CLASS}`).forEach((mark) => {
      const parent = mark.parentNode;
      if (!parent) return;
      while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
      parent.removeChild(mark);
    });

    this.normalizeImageUrls(clone);
    return clone.outerHTML;
  }

  // No client-side image fetching: resolve each image to its best absolute
  // URL and let the API's server-side fetcher rehost it.
  private normalizeImageUrls(clone: HTMLElement): void {
    const liveImages = Array.from(document.images);
    const cloneImages = Array.from(clone.querySelectorAll("img"));
    const candidates = liveImages
      .map((img, index) => {
        const { width, height } = imageDimensions(img);
        const src = candidateImageUrl(img);
        const inArticle = !!img.closest("article, main, [role='main']");
        const hasKnownSize = width > 0 && height > 0;
        const area = hasKnownSize ? width * height : 120_000;
        return {
          index,
          src,
          width,
          height,
          inArticle,
          hasKnownSize,
          score: (inArticle ? 10_000_000 : 0) + area,
        };
      })
      .filter((item) => {
        if (!item.src || item.src.startsWith("data:") || item.src.startsWith("blob:")) return false;
        if (!/^https?:\/\//i.test(item.src)) return false;
        if (item.width >= 80 && item.height >= 50) return true;
        return item.inArticle && !item.hasKnownSize;
      })
      .sort((a, b) => b.score - a.score)
      .slice(0, MAX_CAPTURED_IMAGES);

    for (const item of candidates) {
      const cloneImg = cloneImages[item.index];
      if (!cloneImg) continue;
      cloneImg.setAttribute("src", item.src);
      cloneImg.removeAttribute("srcset");
      cloneImg.removeAttribute("sizes");
      if (item.width) cloneImg.setAttribute("width", String(item.width));
      if (item.height) cloneImg.setAttribute("height", String(item.height));
    }
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
      // create_web_clip enriches initial highlights with textAnchor for the
      // TipTap renderer. Re-posting the original browser highlight would
      // replace that enriched copy and drop textAnchor, so skip only the
      // highlight event that was part of the initial autosave payload.
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
    if (this.saveTimer) {
      window.clearTimeout(this.saveTimer);
    }
    this.saveTimer = window.setTimeout(() => this.flushSave(), 600);
  }

  private async flushSave() {
    if (!this.apiUrl) return;
    if (this.isSaving) {
      // Re-queue
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
        // Refetch and merge — last writer wins on duplicates by id
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
  // Skip selections inside form fields, code editors, etc.
  if (startEl.closest("input,textarea,[contenteditable='true']")) return false;
  return true;
}
