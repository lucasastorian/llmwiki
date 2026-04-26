import { redirect } from 'next/navigation'
import { AppShell } from '@/components/layout/AppShell'
import { AuthProvider } from '@/components/auth/AuthProvider'

const isLocal = process.env.NEXT_PUBLIC_MODE === 'local'

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  if (isLocal) {
    return (
      <AuthProvider userId="local" email="local@localhost">
        <AppShell>{children}</AppShell>
      </AuthProvider>
    )
  }

  // Hosted mode: require Supabase session
  const { createClient } = await import('@/lib/supabase/server')
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) redirect('/login')

  return (
    <AuthProvider userId={user.id} email={user.email!}>
      <AppShell>{children}</AppShell>
    </AuthProvider>
  )
}
