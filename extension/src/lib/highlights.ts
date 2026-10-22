import type { Highlight, HighlightAnchor } from "./api";

export const HIGHLIGHT_CLASS = "llmwiki-hl";
const HIGHLIGHT_ATTR = "data-llmwiki-hl-id";
const SCAN_SKIP_TAGS = new Set([
  "SCRIPT", "STYLE", "NOSCRIPT", "NAV", "ASIDE",
  "HEADER", "FOOTER", "IFRAME", "OBJECT", "EMBED",
  "BUTTON", "INPUT", "TEXTAREA", "SELECT", "FORM",
]);
const ROOT_LANDMARK_SELECTOR = "main, [role=main], article";

// Largest landmark, not the first: some sites (e.g. HuggingFace) render sidebar cards as <article>.
function findRoot(): Element {
  let best: Element | null = null;
  let bestLen = 0;
  for (const el of Array.from(document.querySelectorAll(ROOT_LANDMARK_SELECTOR))) {
    const len = el.textContent?.length ?? 0;
    if (len > bestLen) {
      best = el;
      bestLen = len;
    }
  }
  return best ?? document.body;
}

export function captureAnchor(range: Range): HighlightAnchor | null {
  const text = range.toString();
  if (!text.trim()) return null;
  const root = findRoot();
  const startContainer = range.startContainer;
  const endContainer = range.endContainer;
  if (!root.contains(startContainer) || !root.contains(endContainer)) return null;

  const xpath = computeXPath(startContainer, root);
  if (!xpath) return null;
  const endXPath = computeXPath(endContainer, root) ?? xpath;

  const { prefix, suffix } = surroundingContext(range, 32);

  return {
    xpath,
    endXPath,
    startOffset: range.startOffset,
    endOffset: range.endOffset,
    textContent: text,
    prefix,
    suffix,
  };
}

function computeXPath(node: Node, root: Element): string | null {
  if (node === root) return ".";
  const segments: string[] = [];
  let current: Node | null = node;
  while (current && current !== root) {
    const parent: ParentNode | null = current.parentNode;
    if (!parent) return null;
    if (current.nodeType === Node.TEXT_NODE) {
      let idx = 1;
      let sib = current.previousSibling;
      while (sib) {
        if (sib.nodeType === Node.TEXT_NODE) idx++;
        sib = sib.previousSibling;
      }
      segments.unshift(`text()[${idx}]`);
    } else if (current.nodeType === Node.ELEMENT_NODE) {
      const el = current as Element;
      let idx = 1;
      let sib = el.previousElementSibling;
      while (sib) {
        if (sib.tagName === el.tagName) idx++;
        sib = sib.previousElementSibling;
      }
      segments.unshift(`${el.tagName.toLowerCase()}[${idx}]`);
    } else {
      return null;
    }
    current = parent;
  }
  return "./" + segments.join("/");
}

function surroundingContext(range: Range, len: number): { prefix: string; suffix: string } {
  const root = findRoot();
  const fullText = root.textContent ?? "";
  const target = range.toString();
  const idx = fullText.indexOf(target);
  if (idx < 0) return { prefix: "", suffix: "" };
  const prefix = fullText.slice(Math.max(0, idx - len), idx);
  const suffix = fullText.slice(idx + target.length, idx + target.length + len);
  return { prefix, suffix };
}

export function resolveAnchor(anchor: HighlightAnchor): Range | null {
  const root = findRoot();
  const xpathResult = tryXPath(anchor, root);
  if (xpathResult) return xpathResult;
  return tryTextScan(anchor, root);
}

function evalXPath(xpath: string, root: Element): Node | null {
  try {
    const result = document.evaluate(
      xpath,
      root,
      null,
      XPathResult.FIRST_ORDERED_NODE_TYPE,
      null,
    );
    return result.singleNodeValue;
  } catch {
    return null;
  }
}

function tryXPath(anchor: HighlightAnchor, root: Element): Range | null {
  const startNode = evalXPath(anchor.xpath, root);
  const endNode = anchor.endXPath ? evalXPath(anchor.endXPath, root) : startNode;
  if (!startNode || !endNode) return null;

  if (startNode !== endNode) {
    if (startNode.nodeType !== Node.TEXT_NODE || endNode.nodeType !== Node.TEXT_NODE) {
      return null;
    }
    const range = document.createRange();
    try {
      range.setStart(startNode, Math.min(anchor.startOffset, startNode.textContent?.length ?? 0));
      range.setEnd(endNode, Math.min(anchor.endOffset, endNode.textContent?.length ?? 0));
    } catch {
      return null;
    }
    if (range.toString() === anchor.textContent) return range;
    return null;
  }

  const node = startNode;
  if (node.nodeType !== Node.TEXT_NODE) return null;
  const text = node.textContent ?? "";
  const target = anchor.textContent;
  const start = anchor.startOffset;
  if (start + target.length <= text.length && text.slice(start, start + target.length) === target) {
    const range = document.createRange();
    range.setStart(node, start);
    range.setEnd(node, start + target.length);
    return range;
  }
  const idx = text.indexOf(target);
  if (idx >= 0) {
    const range = document.createRange();
    range.setStart(node, idx);
    range.setEnd(node, idx + target.length);
    return range;
  }
  return null;
}

function tryTextScan(anchor: HighlightAnchor, root: Element): Range | null {
  const target = anchor.textContent;
  if (!target) return null;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement;
      if (!parent) return NodeFilter.FILTER_REJECT;
      if (SCAN_SKIP_TAGS.has(parent.tagName)) return NodeFilter.FILTER_REJECT;
      if (parent.closest("nav,aside,header,footer,[aria-hidden='true']")) {
        return NodeFilter.FILTER_REJECT;
      }
      return NodeFilter.FILTER_ACCEPT;
    },
  });

  let node = walker.nextNode();
  while (node) {
    const text = node.textContent ?? "";
    const idx = text.indexOf(target);
    if (idx >= 0) {
      const prefixOk = !anchor.prefix || idx === 0 ||
        text.slice(Math.max(0, idx - anchor.prefix.length), idx).endsWith(anchor.prefix);
      if (prefixOk) {
        const range = document.createRange();
        range.setStart(node, idx);
        range.setEnd(node, idx + target.length);
        return range;
      }
    }
    node = walker.nextNode();
  }
  return null;
}

// One <mark> per intersected text node, all sharing the highlight id, so a highlight can span elements.
export function wrapRange(range: Range, highlightId: string): boolean {
  if (range.collapsed) return false;

  const root = range.commonAncestorContainer;
  const rootEl = root.nodeType === Node.ELEMENT_NODE
    ? (root as Element)
    : root.parentElement;
  if (!rootEl) return false;

  const textNodes = collectTextNodesInRange(rootEl, range);
  if (textNodes.length === 0) return false;

  let wrappedAny = false;
  for (const { node, start, end } of textNodes) {
    if (start === end) continue;
    let target = node;
    if (start > 0) {
      target = (target as Text).splitText(start);
    }
    const length = end - start;
    if (target.nodeValue && target.nodeValue.length > length) {
      (target as Text).splitText(length);
    }
    const mark = document.createElement("mark");
    mark.className = HIGHLIGHT_CLASS;
    mark.setAttribute(HIGHLIGHT_ATTR, highlightId);
    const parent = target.parentNode;
    if (!parent) continue;
    parent.insertBefore(mark, target);
    mark.appendChild(target);
    wrappedAny = true;
  }
  return wrappedAny;
}

interface TextNodeSlice {
  node: Text;
  start: number;
  end: number;
}

function collectTextNodesInRange(root: Element, range: Range): TextNodeSlice[] {
  const slices: TextNodeSlice[] = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      if (!range.intersectsNode(node)) return NodeFilter.FILTER_REJECT;
      const parent = node.parentElement;
      if (parent && (parent.tagName === "SCRIPT" || parent.tagName === "STYLE")) {
        return NodeFilter.FILTER_REJECT;
      }
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  let node = walker.nextNode() as Text | null;
  while (node) {
    const length = node.nodeValue?.length ?? 0;
    let start = 0;
    let end = length;
    if (node === range.startContainer) start = range.startOffset;
    if (node === range.endContainer) end = range.endOffset;
    if (start < end) slices.push({ node, start, end });
    node = walker.nextNode() as Text | null;
  }
  return slices;
}

export function findMark(highlightId: string): HTMLElement | null {
  return document.querySelector(
    `mark.${HIGHLIGHT_CLASS}[${HIGHLIGHT_ATTR}="${cssEscape(highlightId)}"]`,
  ) as HTMLElement | null;
}

export function findAllMarks(highlightId: string): HTMLElement[] {
  return Array.from(
    document.querySelectorAll(
      `mark.${HIGHLIGHT_CLASS}[${HIGHLIGHT_ATTR}="${cssEscape(highlightId)}"]`,
    ),
  ) as HTMLElement[];
}

export function unwrapMark(mark: HTMLElement): void {
  const parent = mark.parentNode;
  if (!parent) return;
  while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
  parent.removeChild(mark);
  parent.normalize();
}

export function unwrapById(highlightId: string): void {
  for (const mark of findAllMarks(highlightId)) {
    unwrapMark(mark);
  }
}

function cssEscape(s: string): string {
  return s.replace(/["\\]/g, "\\$&");
}

export function newId(): string {
  return crypto.randomUUID();
}

export function nowIso(): string {
  return new Date().toISOString();
}

export function makeHighlight(
  anchor: HighlightAnchor,
  comment: string | null = null,
): Highlight {
  return {
    id: newId(),
    type: "text",
    anchor,
    comment,
    color: "yellow",
    createdAt: nowIso(),
  };
}

export function applyHighlights(highlights: Highlight[]): { applied: number; failed: number } {
  let applied = 0;
  let failed = 0;
  for (const h of highlights) {
    if (h.type !== "text" || !h.anchor) {
      failed++;
      continue;
    }
    let mark = findMark(h.id);
    if (!mark) {
      const range = resolveAnchor(h.anchor);
      if (!range) {
        failed++;
        continue;
      }
      if (!wrapRange(range, h.id)) {
        failed++;
        continue;
      }
      mark = findMark(h.id);
    }
    if (h.comment) {
      for (const m of findAllMarks(h.id)) {
        m.setAttribute("data-llmwiki-comment", "1");
        m.setAttribute("data-llmwiki-comment-text", h.comment);
        m.setAttribute("title", h.comment);
      }
    }
    applied++;
  }
  return { applied, failed };
}
