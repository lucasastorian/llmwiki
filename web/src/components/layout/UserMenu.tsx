'use client'

import * as React from 'react'
import { useRouter } from 'next/navigation'
import { useTheme } from 'next-themes'
import { useUserStore } from '@/stores'
import { Settings, LogOut, Moon, Sun } from 'lucide-react'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
const isLocal = process.env.NEXT_PUBLIC_MODE === 'local'

export function UserMenu() {
  const router = useRouter()
  const { theme, setTheme } = useTheme()
  const user = useUserStore((s) => s.user)
  const signOutLocal = useUserStore((s) => s.signOut)
  const [mounted, setMounted] = React.useState(false)

  React.useEffect(() => { setMounted(true) }, [])

  const handleSignOut = async () => {
    if (!isLocal) {
      const { createClient } = await import('@/lib/supabase/client')
      const supabase = createClient()
      await supabase.auth.signOut()
    }
    signOutLocal()
    if (isLocal) return
    router.push('/login')
  }

  if (!user) return null

  const initials = user.email.slice(0, 2).toUpperCase()

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button className="h-6 w-6 bg-muted border border-border rounded flex items-center justify-center cursor-pointer hover:bg-accent transition-colors flex-shrink-0">
          <span className="text-[9px] font-medium text-foreground">{initials}</span>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-48">
        <DropdownMenuLabel className="text-xs font-normal text-muted-foreground truncate">
          {user.email}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => router.push('/settings')}>
          <Settings className="mr-2 h-4 w-4" />
          Settings
        </DropdownMenuItem>
        {mounted && (
          <DropdownMenuItem onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
            {theme === 'dark' ? (
              <><Sun className="mr-2 h-4 w-4" />Light Mode</>
            ) : (
              <><Moon className="mr-2 h-4 w-4" />Dark Mode</>
            )}
          </DropdownMenuItem>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={handleSignOut}>
          <LogOut className="mr-2 h-4 w-4" />
          Sign Out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
