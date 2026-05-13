import { createBrowserClient } from "@supabase/ssr";
import { getPublicSupabaseAnonKey, getPublicSupabaseUrl } from "@/lib/public-config";

type CookieOptions = {
  domain?: string;
  expires?: Date | string;
  httpOnly?: boolean;
  maxAge?: number;
  path?: string;
  sameSite?: boolean | "lax" | "strict" | "none";
  secure?: boolean;
};

type CookieToSet = {
  name: string;
  value: string;
  options?: CookieOptions;
};

function parseDocumentCookies() {
  if (typeof document === "undefined") return [];
  return document.cookie
    .split(";")
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const separator = part.indexOf("=");
      const name = separator === -1 ? part : part.slice(0, separator);
      const value = separator === -1 ? "" : part.slice(separator + 1);
      return {
        name: decodeURIComponent(name),
        value: decodeURIComponent(value),
      };
    });
}

function serializeCookie({ name, value, options = {} }: CookieToSet) {
  const parts = [`${encodeURIComponent(name)}=${encodeURIComponent(value)}`];

  if (options.maxAge !== undefined) parts.push(`Max-Age=${Math.floor(options.maxAge)}`);
  if (options.expires) {
    const expires = options.expires instanceof Date ? options.expires : new Date(options.expires);
    parts.push(`Expires=${expires.toUTCString()}`);
  }
  parts.push(`Path=${options.path ?? "/"}`);
  if (options.domain) parts.push(`Domain=${options.domain}`);
  if (options.sameSite) {
    const sameSite = options.sameSite === true ? "Strict" : String(options.sameSite);
    parts.push(`SameSite=${sameSite.charAt(0).toUpperCase()}${sameSite.slice(1).toLowerCase()}`);
  }
  if (options.secure) parts.push("Secure");

  return parts.join("; ");
}

export function createClient() {
  return createBrowserClient(getPublicSupabaseUrl(), getPublicSupabaseAnonKey(), {
    cookies: {
      getAll() {
        return parseDocumentCookies();
      },
      setAll(cookiesToSet: CookieToSet[]) {
        if (typeof document === "undefined") return;
        cookiesToSet.forEach((cookie) => {
          document.cookie = serializeCookie(cookie);
        });
      },
    },
  });
}
