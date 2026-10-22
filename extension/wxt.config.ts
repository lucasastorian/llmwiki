import { defineConfig } from "wxt";
import packageJson from "./package.json";

function requiredEnv(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`${name} must be set before building the extension`);
  }
  return value;
}

function origin(name: string, value: string): string {
  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") throw new Error();
    return url.origin;
  } catch {
    throw new Error(`${name} must be an absolute HTTP(S) URL`);
  }
}

export default defineConfig({
  srcDir: "src",
  publicDir: "src/public",
  modules: ["@wxt-dev/module-react"],
  // WXT's default target makes the pinned esbuild downlevel Supabase Auth with an unsupported transform.
  vite: () => ({
    build: { target: "chrome109" },
  }),
  // WXT loads dotenv after importing this config, so env must be read lazily.
  manifest: () => {
    const apiOrigin = origin(
      "VITE_API_BASE_URL",
      process.env.VITE_API_BASE_URL ?? "https://api.llmwiki.app",
    );
    const supabaseOrigin = origin(
      "VITE_SUPABASE_URL",
      requiredEnv("VITE_SUPABASE_URL"),
    );
    requiredEnv("VITE_SUPABASE_ANON_KEY");

    return {
      name: "LLM Wiki",
      description: "Save any web page or PDF to your LLM Wiki knowledge base",
      version: packageJson.version,
      minimum_chrome_version: "109",
      permissions: ["activeTab", "identity", "offscreen", "storage", "scripting"],
      // activeTab covers the page; extension pages still need host access for API/Auth requests.
      host_permissions: [
        `${apiOrigin}/*`,
        `${supabaseOrigin}/*`,
        "http://localhost/*",
      ],
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
    };
  },
});
