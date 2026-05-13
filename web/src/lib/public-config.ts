const PLACEHOLDER_HOSTS = new Set(['KOBE_IP', 'MAC_MINI_IP'])

function cleanConfiguredUrl(value?: string): string | undefined {
  if (!value) return undefined
  const trimmed = value.trim().replace(/\/+$/, '')
  if (!trimmed) return undefined
  try {
    const url = new URL(trimmed)
    if (PLACEHOLDER_HOSTS.has(url.hostname)) return undefined
    if (url.pathname === '/auth/v1') {
      url.pathname = ''
      url.search = ''
      url.hash = ''
      return url.toString().replace(/\/+$/, '')
    }
    return trimmed
  } catch {
    return undefined
  }
}

export function getBrowserOrigin(): string | undefined {
  if (typeof window === 'undefined') return undefined
  return window.location.origin.replace(/\/+$/, '')
}

export function getPublicSupabaseUrl(origin?: string): string {
  return (
    cleanConfiguredUrl(process.env.SUPABASE_URL) ||
    cleanConfiguredUrl(process.env.NEXT_PUBLIC_SUPABASE_URL) ||
    cleanConfiguredUrl(origin) ||
    getBrowserOrigin() ||
    'http://localhost'
  )
}

export function getPublicSupabaseAnonKey(): string {
  return process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || 'public-anon-key'
}

export function getPublicApiUrl(origin?: string): string {
  const configured = cleanConfiguredUrl(process.env.NEXT_PUBLIC_API_URL)
  if (configured) return configured
  const base = cleanConfiguredUrl(origin) || getBrowserOrigin()
  return base ? `${base}/api` : 'http://localhost:8000'
}

export function getPublicMcpUrl(origin?: string): string {
  const configured = cleanConfiguredUrl(process.env.NEXT_PUBLIC_MCP_URL)
  if (configured) return configured
  const base = cleanConfiguredUrl(origin) || getBrowserOrigin()
  return base ? `${base}/mcp` : 'http://localhost:8080/mcp'
}
