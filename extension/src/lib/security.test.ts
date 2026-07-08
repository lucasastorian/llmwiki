import { describe, expect, it } from "vitest";

import { isAllowedApiFetchUrl } from "./security";

describe("extension security helpers", () => {
  describe("isAllowedApiFetchUrl", () => {
    it("allows only the configured cloud or dev API origin", () => {
      const apiUrl = "https://api.llmwiki.app";

      expect(isAllowedApiFetchUrl("https://api.llmwiki.app/v1/knowledge-bases", apiUrl)).toBe(true);
      expect(isAllowedApiFetchUrl("https://api.llmwiki.app:443/v1/documents/by-url", apiUrl)).toBe(true);
    });

    it("allows the configured local origin without allowing every localhost port", () => {
      const apiUrl = "http://localhost:8000";

      expect(isAllowedApiFetchUrl("http://localhost:8000/v1/knowledge-bases", apiUrl)).toBe(true);
      expect(isAllowedApiFetchUrl("http://localhost:8080/v1/knowledge-bases", apiUrl)).toBe(false);
      expect(isAllowedApiFetchUrl("http://127.0.0.1:8000/v1/knowledge-bases", apiUrl)).toBe(false);
    });

    it("blocks cross-origin and non-http targets", () => {
      const apiUrl = "https://api.llmwiki.app";

      expect(isAllowedApiFetchUrl("https://evil.example/steal", apiUrl)).toBe(false);
      expect(isAllowedApiFetchUrl("file:///etc/passwd", apiUrl)).toBe(false);
      expect(isAllowedApiFetchUrl("chrome://extensions", apiUrl)).toBe(false);
      expect(isAllowedApiFetchUrl("not a url", apiUrl)).toBe(false);
    });
  });
});
