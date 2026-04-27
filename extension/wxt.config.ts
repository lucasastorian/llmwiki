import { defineConfig } from "wxt";

export default defineConfig({
  srcDir: "src",
  modules: ["@wxt-dev/module-react"],
  manifest: {
    name: "LLM Wiki",
    description: "Save any web page or PDF to your LLM Wiki knowledge base",
    version: "0.1.0",
    permissions: ["activeTab", "identity", "storage", "scripting"],
    host_permissions: ["<all_urls>"],
  },
});
