export function isAllowedApiFetchUrl(targetUrl: string, configuredApiUrl: string): boolean {
  try {
    const target = new URL(targetUrl);
    if (!["http:", "https:"].includes(target.protocol)) return false;
    const configured = new URL(configuredApiUrl);
    return target.origin === configured.origin;
  } catch {
    return false;
  }
}
