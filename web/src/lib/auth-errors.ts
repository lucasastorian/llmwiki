import type { Session, SupabaseClient, User } from '@supabase/supabase-js'

export function getAuthErrorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error ?? 'Unknown error')
  const lower = message.toLowerCase()

  if (lower.includes('unsupported provider') || (lower.includes('provider') && lower.includes('not enabled'))) {
    return "Google sign-in isn't configured on this server. Please sign in with email and password."
  }

  if (
    lower.includes('failed to fetch') ||
    lower.includes('networkerror') ||
    lower.includes('network request failed') ||
    lower.includes('aborted') ||
    lower.includes('timeout')
  ) {
    return 'Cannot reach the auth service right now. Check your Supabase URL and make sure the auth endpoint is online.'
  }

  return message
}

export async function withAuthTimeout<T>(promise: Promise<T>, timeoutMs = 10000): Promise<T> {
  let id: ReturnType<typeof setTimeout> | undefined

  try {
    return await Promise.race([
      promise,
      new Promise<T>((_, reject) => {
        id = setTimeout(() => reject(new Error('Auth request timeout')), timeoutMs)
      }),
    ])
  } finally {
    if (id) clearTimeout(id)
  }
}

const AUTH_REJECTION_STATUSES = new Set([400, 401, 403])

export type AuthCheck =
  | { kind: 'signed_in'; user: User; session: Session }
  | { kind: 'signed_out' }
  | { kind: 'unavailable' }

function isRejection(error: { status?: number } | null): boolean {
  return error?.status !== undefined && AUTH_REJECTION_STATUSES.has(error.status)
}

type UserVerification = ReturnType<SupabaseClient['auth']['getUser']>

// A slow or failing auth server never signs the user out; only an explicit rejection does, even a late one.
export async function checkAuth(supabase: SupabaseClient, onLateRejection: () => void): Promise<AuthCheck> {
  let session: Session | null
  try {
    const { data, error } = await withAuthTimeout(supabase.auth.getSession())
    if (error) return isRejection(error) ? { kind: 'signed_out' } : { kind: 'unavailable' }
    session = data.session
  } catch {
    return { kind: 'unavailable' }
  }
  if (!session) return { kind: 'signed_out' }

  const verification = supabase.auth.getUser()
  try {
    const { data: { user }, error } = await withAuthTimeout(verification)
    if (user) return { kind: 'signed_in', user, session }
    if (isRejection(error)) return { kind: 'signed_out' }
  } catch {
    watchForLateRejection(verification, onLateRejection)
  }
  return { kind: 'signed_in', user: session.user, session }
}

function watchForLateRejection(verification: UserVerification, onRejected: () => void): void {
  verification.then(({ error }) => { if (isRejection(error)) onRejected() }, () => {})
}
