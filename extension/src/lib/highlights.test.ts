import { beforeEach, describe, expect, it } from "vitest";

import {
  applyHighlights,
  captureAnchor,
  findAllMarks,
  HIGHLIGHT_CLASS,
  unwrapById,
  wrapRange,
} from "./highlights";

function textNode(selector: string): Text {
  const node = document.querySelector(selector)?.firstChild;
  if (!node || node.nodeType !== Node.TEXT_NODE) {
    throw new Error(`Missing text node for ${selector}`);
  }
  return node as Text;
}

describe("highlight DOM helpers", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <article>
        <p id="first">Alpha beta gamma delta.</p>
        <p id="second">Second paragraph with a note.</p>
      </article>
    `;
  });

  it("captures and wraps a single text selection", () => {
    const node = textNode("#first");
    const range = document.createRange();
    range.setStart(node, 6);
    range.setEnd(node, 10);

    const anchor = captureAnchor(range);
    expect(anchor?.textContent).toBe("beta");
    expect(wrapRange(range, "h1")).toBe(true);

    const mark = document.querySelector(`mark.${HIGHLIGHT_CLASS}`);
    expect(mark?.textContent).toBe("beta");
    expect(mark?.getAttribute("data-llmwiki-hl-id")).toBe("h1");
  });

  it("applies stored comments as marker metadata", () => {
    const node = textNode("#second");
    const range = document.createRange();
    range.setStart(node, 24);
    range.setEnd(node, 28);
    const anchor = captureAnchor(range);
    expect(wrapRange(range, "comment-1")).toBe(true);

    const result = applyHighlights([{
      id: "comment-1",
      type: "text",
      comment: "Remember this",
      color: "yellow",
      createdAt: new Date().toISOString(),
      anchor,
    }]);

    expect(result).toEqual({ applied: 1, failed: 0 });
    const [mark] = findAllMarks("comment-1");
    if (!mark) throw new Error("expected a mark");
    expect(mark.textContent).toBe("note");
    expect(mark.getAttribute("data-llmwiki-comment")).toBe("1");
    expect(mark.getAttribute("data-llmwiki-comment-text")).toBe("Remember this");
    expect(mark.getAttribute("title")).toBe("Remember this");
  });

  it("unwraps every mark for the same highlight id", () => {
    const node = textNode("#first");
    const range = document.createRange();
    range.setStart(node, 0);
    range.setEnd(node, 16);
    expect(wrapRange(range, "multi")).toBe(true);

    expect(findAllMarks("multi").length).toBeGreaterThan(0);
    unwrapById("multi");

    expect(findAllMarks("multi")).toHaveLength(0);
    expect(document.querySelector("#first")?.textContent).toBe("Alpha beta gamma delta.");
  });
});
