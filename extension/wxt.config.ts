import { defineConfig } from "wxt";

export default defineConfig({
  srcDir: "src",
  modules: ["@wxt-dev/module-react"],
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
    permissions: ["activeTab", "identity", "storage", "scripting"],
    host_permissions: ["<all_urls>"],
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
