const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
const WS_URL = API_URL.replace(/^http/, 'ws')
const isLocal = process.env.NEXT_PUBLIC_MODE === 'local'

/** Thrown by apiFetch on non-2xx responses. Callers can branch on `.status`
 *  for clean retry logic (e.g. 409 conflict reconciliation). */
export class ApiError extends Error {
  status: number
  detail: unknown

  constructor(status: number, message: string, detail: unknown = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

export function isApiError(err: unknown): err is ApiError {
  return err instanceof ApiError
}

export async function apiFetch<T>(
  path: string,
  token: string,
  options?: RequestInit,
): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...options?.headers as Record<string, string>,
  }

  // In local mode, skip Authorization header (API doesn't check it)
  if (!isLocal && token) {
    headers.Authorization = `Bearer ${token}`
  }

  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    const message =
      typeof body?.detail === 'string'
        ? body.detail
        : `API error: ${res.status}`
    throw new ApiError(res.status, message, body)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

export function getDocumentsWsUrl(kbId: string): string {
  return `${WS_URL}/v1/ws/documents/${kbId}`
}
