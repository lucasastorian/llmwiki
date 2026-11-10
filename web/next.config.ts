import type { NextConfig } from "next";
import path from "path";
import { withSentryConfig } from "@sentry/nextjs";

const nextConfig: NextConfig = {
  output: "standalone",
  outputFileTracingRoot: path.join(__dirname),
  webpack(config) {
    // PDF.js's unminified bundle reuses Webpack runtime names, which collide
    // with Next's eval-based development bundles (vercel/next.js#89177).
    config.resolve.alias = {
      ...config.resolve.alias,
      "pdfjs-dist$": "pdfjs-dist/build/pdf.min.mjs",
    };
    return config;
  },
  experimental: {
    // The /api rewrite proxies uploads; the API accepts 100 MiB, so the
    // proxy cap (default 10 MiB) must sit above it.
    proxyClientMaxBodySize: 110 * 1024 * 1024,
  },
  async rewrites() {
    // Single-port local deployment: the standalone server proxies /api to the
    // FastAPI process on the container's loopback.
    if (process.env.NEXT_PUBLIC_MODE !== "local") return [];
    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8000/:path*",
      },
      {
        source: "/mcp",
        destination: "http://127.0.0.1:8100/mcp",
      },
    ];
  },
  async headers() {
    return [
      {
        source: "/sw.js",
        headers: [
          {
            key: "Content-Type",
            value: "application/javascript; charset=utf-8",
          },
          {
            key: "Cache-Control",
            value: "no-cache, no-store, must-revalidate",
          },
          {
            key: "Content-Security-Policy",
            value: "default-src 'self'; script-src 'self'",
          },
        ],
      },
      {
        source: "/manifest.webmanifest",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=0, must-revalidate",
          },
        ],
      },
    ];
  },
};

const sentryOptions = {
  silent: true,
  disableLogger: true,
};

export default process.env.NODE_ENV === "development"
  ? nextConfig
  : withSentryConfig(nextConfig, sentryOptions);
