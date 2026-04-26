'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useUserStore } from '@/stores'

export function AuthRedirect() {
  const user = useUserStore((s) => s.user)
  const router = useRouter()

  useEffect(() => {
    if (user) router.replace('/wikis')
  }, [user, router])

  return null
}
