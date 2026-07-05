import { afterEach, describe, expect, it, vi } from "vitest";

import { hasPdfSuffix, isPdfTab } from "./pdf";

function stubExecuteScript(result: unknown): ReturnType<typeof vi.fn> {
  const executeScript = vi.fn(async () => [{ result }]);
  vi.stubGlobal("chrome", { scripting: { executeScript } });
  return executeScript;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("hasPdfSuffix", () => {
  it("matches .pdf pathnames, ignoring case and query strings", () => {
    expect(hasPdfSuffix("https://example.com/paper.pdf", null)).toBe(true);
    expect(hasPdfSuffix("https://example.com/paper.PDF?x=1", null)).toBe(true);
  });

  it("misses extension-less PDF URLs like modern arxiv", () => {
    expect(hasPdfSuffix("https://arxiv.org/pdf/2506.06266", "Some Paper Title")).toBe(false);
  });

  it("matches a .pdf tab title", () => {
    expect(hasPdfSuffix("https://example.com/view?id=1", "paper.pdf")).toBe(true);
  });
});

describe("isPdfTab", () => {
  it("detects extension-less PDFs via the viewer contentType", async () => {
    stubExecuteScript("application/pdf");
    expect(await isPdfTab(1, "https://arxiv.org/pdf/2506.06266", "2506.06266")).toBe(true);
  });

  it("returns false for regular html pages", async () => {
    stubExecuteScript("text/html");
    expect(await isPdfTab(1, "https://example.com/article", "Article")).toBe(false);
  });

  it("skips the probe when the suffix already matches", async () => {
    const executeScript = stubExecuteScript("text/html");
    expect(await isPdfTab(1, "https://example.com/paper.pdf", null)).toBe(true);
    expect(executeScript).not.toHaveBeenCalled();
  });

  it("skips the probe on non-http urls", async () => {
    const executeScript = stubExecuteScript("application/pdf");
    expect(await isPdfTab(1, "chrome://settings", null)).toBe(false);
    expect(executeScript).not.toHaveBeenCalled();
  });

  it("degrades to false when the probe cannot inject", async () => {
    const executeScript = vi.fn(async () => {
      throw new Error("Cannot access contents of the page");
    });
    vi.stubGlobal("chrome", { scripting: { executeScript } });
    expect(await isPdfTab(1, "https://example.com/x", null)).toBe(false);
  });
});
