'use client'

import { useEffect } from 'react'

export function OpenReplayTracker() {
  useEffect(() => {
    const key = process.env.NEXT_PUBLIC_OPENREPLAY_KEY
    if (!key) return

    import('@openreplay/tracker').then(({ default: Tracker }) => {
      const tracker = new Tracker({
        projectKey: key,
        __DISABLE_SECURE_MODE: process.env.NODE_ENV === 'development',
      })
      tracker.start()
    })
  }, [])

  return null
}
