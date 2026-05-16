export function getAuthErrorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error ?? 'Unknown error')
  const lower = message.toLowerCase()

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
