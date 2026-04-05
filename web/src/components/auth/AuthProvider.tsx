'use client'

import * as React from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { useUserStore, useKBStore } from '@/stores'
import { createClient } from '@/lib/supabase/client'
import { apiFetch } from '@/lib/api'

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

    const supabase = createClient()
    supabase.auth.getSession().then(async ({ data: { session } }) => {
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
        setOnboarded(true)
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
  }, [userId, email, setUser, setAccessToken, setOnboarded, fetchKBs, router, pathname, signOut])

  React.useEffect(() => {
    if (onboarded === false && pathname !== '/onboarding') {
      router.replace('/onboarding')
    }
  }, [onboarded, pathname, router])

  return <>{children}</>
}
