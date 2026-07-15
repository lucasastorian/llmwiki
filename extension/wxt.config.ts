import { defineConfig } from "wxt";

const apiOrigin = new URL(process.env.VITE_API_BASE_URL ?? "https://api.llmwiki.app").origin;

export default defineConfig({
  srcDir: "src",
  modules: ["@wxt-dev/module-react"],
  // This is a Chrome MV3 extension. WXT's multi-browser default target asks
  // the pinned esbuild version to downlevel modern Supabase Auth code using a
  // destructuring transform it no longer supports, which prevents packaging.
  vite: () => ({
    build: { target: "chrome109" },
  }),
  // Dev runner config:
  //   - Persistent profile so the Google/Supabase sign-in survives reloads
  //   - Opens a known testbed URL so we can verify the content script bootstraps
  //     against a real site (CSP, CORS, real DOM)
  //   - Uses your actual Chrome binary, in a separate profile dir, so this
  //     doesn't interfere with your normal browsing session
  runner: {
    binaries: {
      chrome: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    },
    chromiumProfile: "/tmp/llmwiki-ext-profile",
    keepProfileChanges: true,
    startUrls: ["https://example.com/"],
  },
  manifest: {
    name: "LLM Wiki",
    description: "Save any web page or PDF to your LLM Wiki knowledge base",
    version: "0.1.0",
    minimum_chrome_version: "109",
    permissions: ["activeTab", "identity", "offscreen", "storage", "scripting"],
    // The page is reached via activeTab on the toolbar click; host_permissions
    // is only the API origin so the extension can call its own backend.
    host_permissions: [`${apiOrigin}/*`, "http://localhost/*"],
    icons: {
      16: "icon/16.png",
      32: "icon/32.png",
      48: "icon/48.png",
      96: "icon/96.png",
      128: "icon/128.png",
    },
    action: {
      default_icon: {
        16: "icon/16.png",
        32: "icon/32.png",
      },
    },
  },
});
