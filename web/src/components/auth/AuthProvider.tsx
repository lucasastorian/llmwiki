'use client'

import * as React from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { useUserStore, useKBStore } from '@/stores'
import { apiFetch } from '@/lib/api'

const isLocal = process.env.NEXT_PUBLIC_MODE === 'local'

interface AuthProviderProps {
  userId: string
  email: string
  children: React.ReactNode
}

export function AuthProvider({ userId, email, children }: AuthProviderProps) {
  const router = useRouter()
  const pathname = usePathname()
  const setUser = useUserStore((s) => s.setUser)
  const setAccessToken = useUserStore((s) => s.setAccessToken)
  const setOnboarded = useUserStore((s) => s.setOnboarded)
  const signOut = useUserStore((s) => s.signOut)
  const onboarded = useUserStore((s) => s.onboarded)
  const fetchKBs = useKBStore((s) => s.fetchKBs)
  const initialized = React.useRef(false)

  React.useEffect(() => {
    if (initialized.current) return
    initialized.current = true

    if (isLocal) {
      // Local mode: static session, no Supabase
      setUser({ id: userId, email })
      setAccessToken('local')
      setOnboarded(true)
      fetchKBs()
      return
    }

    // Hosted mode: Supabase session
    import('@/lib/supabase/client').then(({ createClient }) => {
      const supabase = createClient()
      supabase.auth.getUser().then(async ({ data: { user: authUser } }) => {
        if (!authUser) {
          signOut()
          useKBStore.setState({ knowledgeBases: [], loading: false, error: null })
          return
        }
        // Still need the session for the access_token
        const { data: { session } } = await supabase.auth.getSession()
        if (!session) {
          signOut()
          useKBStore.setState({ knowledgeBases: [], loading: false, error: null })
          return
        }
        setUser({ id: userId, email })
        setAccessToken(session.access_token)
        fetchKBs()

        try {
          const me = await apiFetch<{ onboarded: boolean }>('/v1/me', session.access_token)
          setOnboarded(me.onboarded)
          if (!me.onboarded && pathname !== '/onboarding') {
            router.replace('/onboarding')
          }
        } catch {
          const stored = useUserStore.getState().onboarded
          if (stored === null) setOnboarded(true)
        }
      })

      const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
        if (session) {
          useUserStore.getState().setAccessToken(session.access_token)
        } else {
          signOut()
          useKBStore.setState({ knowledgeBases: [], loading: false, error: null })
          router.replace('/login')
        }
      })

      return () => subscription.unsubscribe()
    })
  }, [userId, email, setUser, setAccessToken, setOnboarded, fetchKBs, router, pathname, signOut])

  React.useEffect(() => {
    if (!isLocal && onboarded === false && pathname !== '/onboarding') {
      router.replace('/onboarding')
    }
  }, [onboarded, pathname, router])

  return <>{children}</>
}
