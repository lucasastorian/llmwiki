export interface PageCaptureOptions {
  maxBytes?: number;
  maxNodes?: number;
  maxImages?: number;
}

/** Self-contained (nested helpers, no imports) because executeScript serializes the function. */
export function capturePageHtml(options: PageCaptureOptions = {}): string {
  const maxBytes = positiveInteger(options.maxBytes, 2 * 1024 * 1024);
  const maxNodes = positiveInteger(options.maxNodes, 60_000);
  const maxImages = Math.min(nonNegativeInteger(options.maxImages, 24), 256);
  const maxCandidateUrlLength = 8 * 1024;
  const excludedSelector = [
    "script",
    "style",
    "noscript",
    "iframe",
    "template",
    ".llmwiki-pill",
    ".llmwiki-popover",
    ".llmwiki-toast",
    "#llmwiki-highlight-style",
  ].join(",");
  const lazyImageAttributes = [
    "data-src",
    "data-original",
    "data-lazy-src",
    "data-hires",
    "data-url",
    "data-image",
    "data-full-url",
  ];
  const lazySrcsetAttributes = ["data-srcset", "data-lazy-srcset"];
  const strippedImageAttributes = new Set([
    "src",
    "srcset",
    "sizes",
    "data-sizes",
    ...lazyImageAttributes,
    ...lazySrcsetAttributes,
  ]);
  const root = document.documentElement;
  if (!root) throw new Error("Could not read this page's document.");

  let nodeCount = 1;
  let estimatedBytes = 0;
  assertNodeLimit();
  const clone = cloneElementWithinBudget(root) as HTMLElement;
  const frames: Array<{ source: Node; target: Node; nextChild: ChildNode | null }> = [
    { source: root, target: clone, nextChild: root.firstChild },
  ];
  const imageCandidates: Array<{
    clone: HTMLImageElement;
    src: string;
    width: number;
    height: number;
    score: number;
  }> = [];

  while (frames.length) {
    const frame = frames[frames.length - 1]!;
    const child = frame.nextChild;
    if (!child) {
      frames.pop();
      continue;
    }
    frame.nextChild = child.nextSibling;
    nodeCount += 1;
    assertNodeLimit();

    if (child.nodeType === Node.ELEMENT_NODE) {
      const element = child as Element;
      if (element.matches(excludedSelector)) continue;
      if (element.matches("mark.llmwiki-hl")) {
        frames.push({ source: element, target: frame.target, nextChild: element.firstChild });
        continue;
      }

      const elementClone = cloneElementWithinBudget(element);
      frame.target.appendChild(elementClone);
      if (element.localName === "img") {
        considerImage(
          element as HTMLImageElement,
          elementClone as HTMLImageElement,
        );
      }
      frames.push({ source: element, target: elementClone, nextChild: element.firstChild });
      continue;
    }

    if (child.nodeType === Node.TEXT_NODE) {
      const value = (child as Text).data;
      consumeSerializedString(value, "text");
      frame.target.appendChild(document.createTextNode(value));
    }
    // Skipped nodes still count toward maxNodes so comment-heavy pages stay bounded.
  }

  for (const candidate of imageCandidates) {
    addAttributeWithinBudget(candidate.clone, "src", candidate.src);
    if (candidate.width && !candidate.clone.hasAttribute("width")) {
      addAttributeWithinBudget(candidate.clone, "width", String(candidate.width));
    }
    if (candidate.height && !candidate.clone.hasAttribute("height")) {
      addAttributeWithinBudget(candidate.clone, "height", String(candidate.height));
    }
  }

  // The running estimate already bounds outerHTML; this rescan guards serializer edge cases.
  const html = clone.outerHTML;
  const actualBytes = boundedUtf8Length(html, maxBytes);
  if (actualBytes > maxBytes) throw tooLargeError();
  return html;

  function positiveInteger(value: number | undefined, fallback: number): number {
    return Number.isFinite(value) && Number(value) > 0
      ? Math.floor(Number(value))
      : fallback;
  }

  function nonNegativeInteger(value: number | undefined, fallback: number): number {
    return Number.isFinite(value) && Number(value) >= 0
      ? Math.floor(Number(value))
      : fallback;
  }

  function assertNodeLimit(): void {
    if (nodeCount > maxNodes) {
      throw new Error(
        `This page is too complex to save (${nodeCount.toLocaleString()} nodes; limit ${maxNodes.toLocaleString()}).`,
      );
    }
  }

  function consumeBytes(bytes: number): void {
    if (bytes > maxBytes - estimatedBytes) throw tooLargeError();
    estimatedBytes += bytes;
  }

  function consumeSerializedString(
    value: string,
    context: "raw" | "text" | "attribute",
  ): void {
    // Each UTF-16 unit is at least one byte, so this rejects giant strings before scanning.
    if (value.length > maxBytes - estimatedBytes) throw tooLargeError();

    for (let index = 0; index < value.length; index += 1) {
      const code = value.charCodeAt(index);
      let bytes: number;
      if (context !== "raw" && code === 38) bytes = 5; // &amp;
      else if (context !== "raw" && (code === 60 || code === 62)) bytes = 4;
      else if (context === "attribute" && code === 34) bytes = 6; // &quot;
      else if (code <= 0x7f) bytes = 1;
      else if (code <= 0x7ff) bytes = 2;
      else if (
        code >= 0xd800
        && code <= 0xdbff
        && index + 1 < value.length
        && value.charCodeAt(index + 1) >= 0xdc00
        && value.charCodeAt(index + 1) <= 0xdfff
      ) {
        bytes = 4;
        index += 1;
      } else bytes = 3;
      consumeBytes(bytes);
    }
  }

  function shouldStripImageAttribute(element: Element, attributeName: string): boolean {
    const isImageSource = element.localName === "img"
      || (element.localName === "source" && element.parentElement?.localName === "picture");
    if (!isImageSource) return false;
    const name = attributeName.toLowerCase();
    return strippedImageAttributes.has(name)
      || name.startsWith("data-src")
      || name.startsWith("data-lazy-src")
      || name.startsWith("data-original-src");
  }

  function cloneElementWithinBudget(element: Element): Element {
    const tagName = element.localName || element.tagName.toLowerCase();
    // <tag></tag>, counted even for void elements to stay conservative.
    consumeBytes(5);
    consumeSerializedString(tagName, "raw");
    consumeSerializedString(tagName, "raw");

    const stripsSources = element.localName === "img"
      || (element.localName === "source" && element.parentElement?.localName === "picture");
    for (let index = 0; index < element.attributes.length; index += 1) {
      const attribute = element.attributes.item(index);
      if (!attribute || shouldStripImageAttribute(element, attribute.name)) continue;
      consumeBytes(4); // leading space, equals sign, and two quotes
      consumeSerializedString(attribute.name, "raw");
      consumeSerializedString(attribute.value, "attribute");
    }

    // Images are copied manually to avoid briefly cloning giant src/data URLs we discard.
    if (!stripsSources) return element.cloneNode(false) as Element;

    const qualifiedName = element.prefix
      ? `${element.prefix}:${element.localName}`
      : element.localName;
    const result = element.namespaceURI
      ? document.createElementNS(element.namespaceURI, qualifiedName)
      : document.createElement(qualifiedName);
    for (let index = 0; index < element.attributes.length; index += 1) {
      const attribute = element.attributes.item(index);
      if (!attribute || shouldStripImageAttribute(element, attribute.name)) continue;
      if (attribute.namespaceURI) {
        result.setAttributeNS(attribute.namespaceURI, attribute.name, attribute.value);
      } else {
        result.setAttribute(attribute.name, attribute.value);
      }
    }
    return result;
  }

  function addAttributeWithinBudget(element: Element, name: string, value: string): void {
    if (element.hasAttribute(name)) return;
    consumeBytes(4);
    consumeSerializedString(name, "raw");
    consumeSerializedString(value, "attribute");
    element.setAttribute(name, value);
  }

  function considerImage(img: HTMLImageElement, imageClone: HTMLImageElement): void {
    if (maxImages === 0) return;
    const rect = img.getBoundingClientRect();
    const widthAttr = Number.parseInt(img.getAttribute("width") || "", 10);
    const heightAttr = Number.parseInt(img.getAttribute("height") || "", 10);
    const width = Math.round(rect.width || img.naturalWidth || widthAttr || 0);
    const height = Math.round(rect.height || img.naturalHeight || heightAttr || 0);
    const src = candidateImageUrl(img);
    if (!src) return;
    const inArticle = !!img.closest("article, main, [role='main']");
    const hasKnownSize = width > 0 && height > 0;
    if (!(width >= 80 && height >= 50) && !(inArticle && !hasKnownSize)) return;
    const area = hasKnownSize ? width * height : 120_000;
    const candidate = {
      clone: imageClone,
      src,
      width,
      height,
      score: (inArticle ? 10_000_000 : 0) + area,
    };
    let position = 0;
    while (
      position < imageCandidates.length
      && imageCandidates[position]!.score >= candidate.score
    ) position += 1;
    if (position >= maxImages) return;
    imageCandidates.splice(position, 0, candidate);
    if (imageCandidates.length > maxImages) imageCandidates.pop();
  }

  function absoluteHttpUrl(value: string | null | undefined): string {
    if (!value || value.length > maxCandidateUrlLength) return "";
    const trimmed = value.trim();
    if (!trimmed || trimmed.startsWith("data:") || trimmed.startsWith("blob:")) return "";
    try {
      const url = new URL(trimmed, document.baseURI).toString();
      return /^https?:\/\//i.test(url) ? url : "";
    } catch {
      return "";
    }
  }

  function largestSrcsetUrl(srcset: string | null): string {
    if (!srcset || srcset.length > maxCandidateUrlLength) return "";
    let bestUrl = "";
    let bestWidth = -1;
    let start = 0;
    let candidatesSeen = 0;
    while (start <= srcset.length && candidatesSeen < 128) {
      const comma = srcset.indexOf(",", start);
      const end = comma === -1 ? srcset.length : comma;
      const candidate = srcset.slice(start, end).trim();
      const separator = candidate.search(/\s/);
      const rawUrl = separator === -1 ? candidate : candidate.slice(0, separator);
      const descriptor = separator === -1 ? "" : candidate.slice(separator).trim();
      const width = descriptor.endsWith("w") ? Number.parseInt(descriptor, 10) : 0;
      const url = absoluteHttpUrl(rawUrl);
      if (url && (!bestUrl || width > bestWidth)) {
        bestUrl = url;
        bestWidth = width;
      }
      candidatesSeen += 1;
      if (comma === -1) break;
      start = comma + 1;
    }
    return bestUrl;
  }

  function pictureSourceUrl(img: HTMLImageElement): string {
    const picture = img.parentElement?.localName === "picture" ? img.parentElement : null;
    if (!picture) return "";
    let source = picture.firstElementChild;
    let inspected = 0;
    while (source && inspected < 32) {
      if (source.localName === "source") {
        const srcset = largestSrcsetUrl(
          source.getAttribute("srcset") || source.getAttribute("data-srcset"),
        );
        if (srcset) return srcset;
        const src = absoluteHttpUrl(source.getAttribute("src"));
        if (src) return src;
      }
      source = source.nextElementSibling;
      inspected += 1;
    }
    return "";
  }

  function candidateImageUrl(img: HTMLImageElement): string {
    const direct = [
      img.currentSrc,
      img.getAttribute("src"),
      largestSrcsetUrl(img.getAttribute("srcset")),
      pictureSourceUrl(img),
    ];
    for (const value of direct) {
      const url = absoluteHttpUrl(value);
      if (url) return url;
    }
    for (const attribute of lazyImageAttributes) {
      const url = absoluteHttpUrl(img.getAttribute(attribute));
      if (url) return url;
    }
    for (const attribute of lazySrcsetAttributes) {
      const url = largestSrcsetUrl(img.getAttribute(attribute));
      if (url) return url;
    }
    return "";
  }

  function boundedUtf8Length(value: string, limit: number): number {
    if (value.length > limit) return limit + 1;
    let bytes = 0;
    for (let index = 0; index < value.length; index += 1) {
      const code = value.charCodeAt(index);
      if (code <= 0x7f) bytes += 1;
      else if (code <= 0x7ff) bytes += 2;
      else if (
        code >= 0xd800
        && code <= 0xdbff
        && index + 1 < value.length
        && value.charCodeAt(index + 1) >= 0xdc00
        && value.charCodeAt(index + 1) <= 0xdfff
      ) {
        bytes += 4;
        index += 1;
      } else bytes += 3;
      if (bytes > limit) return limit + 1;
    }
    return bytes;
  }

  function tooLargeError(): Error {
    return new Error(
      `This page is too large to save after cleanup (limit ${formatBytes(maxBytes)}).`,
    );
  }

  function formatBytes(bytes: number): string {
    if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
    if (bytes >= 1024) return `${Math.ceil(bytes / 1024)} KiB`;
    return `${bytes} bytes`;
  }
}
