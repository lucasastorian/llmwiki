'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { AppShell } from '@/components/layout/AppShell'
import { AuthProvider } from '@/components/auth/AuthProvider'
import { withAuthTimeout } from '@/lib/auth-errors'
import { ONBOARDING_PREVIEW_ENABLED } from '@/lib/onboarding-preview'

const isLocal = process.env.NEXT_PUBLIC_MODE === 'local'

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()

  if (ONBOARDING_PREVIEW_ENABLED && pathname === '/onboarding') {
    return <AppShell>{children}</AppShell>
  }

  if (isLocal) {
    return (
      <AuthProvider userId="local" email="local@localhost">
        <AppShell>{children}</AppShell>
      </AuthProvider>
    )
  }

  return <HostedDashboard>{children}</HostedDashboard>
}

function HostedDashboard({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const [user, setUser] = useState<{ id: string; email: string } | null>(null)
  const [loading, setLoading] = useState(true)
  const pathnameRef = useRef(pathname)

  useEffect(() => {
    pathnameRef.current = pathname
  }, [pathname])

  useEffect(() => {
    let cancelled = false

    const bounceToLogin = async () => {
      try {
        const { createClient } = await import('@/lib/supabase/client')
        await createClient().auth.signOut()
      } catch { /* signOut best-effort */ }
      const currentPath = pathnameRef.current
      const returnTo = currentPath !== '/wikis' ? `?returnTo=${encodeURIComponent(currentPath)}` : ''
      if (!cancelled) router.replace(`/login${returnTo}`)
    }

    import('@/lib/supabase/client').then(async ({ createClient }) => {
      if (cancelled) return
      const supabase = createClient()
      try {
        const { data: { user: authUser } } = await withAuthTimeout(supabase.auth.getUser())
        if (cancelled) return
        if (!authUser) {
          await bounceToLogin()
          return
        }
        setUser({ id: authUser.id, email: authUser.email! })
        setLoading(false)
      } catch {
        await bounceToLogin()
      }
    }).catch(() => {
      bounceToLogin()
    })

    return () => { cancelled = true }
  }, [router])

  if (loading) return null

  return (
    <AuthProvider userId={user!.id} email={user!.email}>
      <AppShell>{children}</AppShell>
    </AuthProvider>
  )
}
