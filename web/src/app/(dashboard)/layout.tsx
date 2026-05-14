'use client'

import { useEffect, useState } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { AppShell } from '@/components/layout/AppShell'
import { AuthProvider } from '@/components/auth/AuthProvider'

const isLocal = process.env.NEXT_PUBLIC_MODE === 'local'

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
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

  useEffect(() => {
    import('@/lib/supabase/client').then(({ createClient }) => {
      const supabase = createClient()
      supabase.auth.getUser().then(({ data: { user: authUser } }) => {
        if (!authUser) {
          const returnTo = pathname !== '/wikis' ? `?returnTo=${encodeURIComponent(pathname)}` : ''
          router.replace(`/login${returnTo}`)
          return
        }
        setUser({ id: authUser.id, email: authUser.email! })
        setLoading(false)
      })
    }).catch(() => {
      router.replace('/login')
    })
  }, [router, pathname])

  if (loading) return null

  return (
    <AuthProvider userId={user!.id} email={user!.email}>
      <AppShell>{children}</AppShell>
    </AuthProvider>
  )
}
