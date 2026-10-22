import { afterEach, describe, expect, it, vi } from "vitest";

import { capturePageHtml } from "./page-capture";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  document.documentElement.innerHTML = "<head></head><body></body>";
});

describe("capturePageHtml", () => {
  it("removes executable/heavy nodes and unwraps extension highlights", () => {
    document.body.innerHTML = `
      <main><p>Hello <mark class="llmwiki-hl">important</mark> world</p></main>
      <script>${"x".repeat(5_000)}</script>
      <style>body { color: red; }</style>
      <noscript>fallback</noscript>
      <iframe></iframe>
      <template><div>hidden</div></template>
    `;

    const html = capturePageHtml({ maxBytes: 2_000, maxNodes: 100 });

    expect(html).toContain("Hello important world");
    expect(html).not.toContain("<mark");
    expect(html).not.toContain("<script");
    expect(html).not.toContain("<style");
    expect(html).not.toContain("<iframe");
    expect(html).not.toContain("<template");
  });

  it("fails clearly before relaying an oversized capture", () => {
    document.body.innerHTML = `<main>${"large page ".repeat(200)}</main>`;

    expect(() => capturePageHtml({ maxBytes: 200, maxNodes: 1_000 })).toThrow(
      /too large to save.*limit/i,
    );
  });

  it("caps document complexity", () => {
    document.body.innerHTML = "<main><div>one</div><div>two</div><div>three</div></main>";

    expect(() => capturePageHtml({ maxBytes: 20_000, maxNodes: 3 })).toThrow(
      /too complex to save/i,
    );
  });

  it("retains sources only for the bounded set of selected images", () => {
    document.body.innerHTML = `
      <main>
        <picture>
          <source srcset="https://example.com/hero-1600.jpg 1600w" data-srcset="https://example.com/lazy-hero.jpg 2000w">
          <img src="https://example.com/hero.jpg" data-src="https://example.com/lazy-hero.jpg" width="800" height="600">
        </picture>
        <img src="data:image/png;base64,${"a".repeat(2_000)}" data-lazy-src="https://example.com/lazy-second.jpg" width="400" height="300">
        <img src="https://example.com/third.jpg" data-original="https://example.com/original-third.jpg" width="200" height="100">
      </main>
    `;

    const html = capturePageHtml({ maxBytes: 5_000, maxNodes: 100, maxImages: 1 });
    const captured = new DOMParser().parseFromString(html, "text/html");
    const images = Array.from(captured.querySelectorAll("img"));

    expect(images.filter((image) => image.hasAttribute("src"))).toHaveLength(1);
    expect(images[0]!.getAttribute("src")).toBe("https://example.com/hero.jpg");
    expect(captured.querySelector("picture source")?.hasAttribute("srcset")).toBe(false);
    expect(html).not.toContain("data:image");
    expect(html).not.toContain("lazy-second.jpg");
    expect(html).not.toContain("original-third.jpg");
  });

  it("rejects a giant text node before cloning or encoding the full value", () => {
    const text = document.createTextNode("x".repeat(20_000));
    document.body.appendChild(text);
    const createTextNode = vi.spyOn(document, "createTextNode");
    const encode = vi.fn(() => {
      throw new Error("TextEncoder should not be used");
    });
    vi.stubGlobal("TextEncoder", class {
      encode = encode;
    });

    expect(() => capturePageHtml({ maxBytes: 200, maxNodes: 100 })).toThrow(
      /too large to save/i,
    );
    expect(createTextNode).not.toHaveBeenCalled();
    expect(encode).not.toHaveBeenCalled();
  });

  it("uses indexed DOM traversal instead of materializing arbitrary node lists", () => {
    document.body.innerHTML = "<main><p>one</p><p>two</p></main>";
    const originalFrom = Array.from;
    vi.spyOn(Array, "from").mockImplementation(((value: ArrayLike<unknown> | Iterable<unknown>) => {
      if (value instanceof NodeList || value instanceof NamedNodeMap) {
        throw new Error("DOM collections must not be materialized");
      }
      return originalFrom(value);
    }) as typeof Array.from);

    expect(capturePageHtml({ maxBytes: 2_000, maxNodes: 100 })).toContain("one");
  });
});
