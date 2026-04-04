'use client'

import * as React from 'react'
import { useRouter } from 'next/navigation'
import { motion } from 'framer-motion'
import Link from 'next/link'
import { useUserStore } from '@/stores'

const ease: [number, number, number, number] = [0.25, 0.1, 0.25, 1]

const PRIMITIVES = ['Search', 'Read', 'Write', 'Organize', 'Connect']

export default function LandingPage() {
  const user = useUserStore((s) => s.user)
  const router = useRouter()

  React.useEffect(() => {
    if (user) router.replace('/kb')
  }, [user, router])

  return (
    <div className="min-h-svh bg-background text-foreground flex flex-col">
      <nav className="fixed top-0 inset-x-0 z-50 flex items-center justify-between px-6 lg:px-8 h-14">
        <span className="flex items-center gap-2 text-sm font-semibold tracking-tight">
          <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 32 32">
            <rect width="32" height="32" rx="7" fill="currentColor" className="text-foreground" />
            <polyline points="11,8 21,16 11,24" fill="none" stroke="currentColor" className="text-background" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          supavault
        </span>
        <div className="flex items-center gap-4">
          <Link
            href="https://github.com/lucasastorian/supavault"
            className="text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            GitHub
          </Link>
          <Link
            href="/login"
            className="text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            Sign in
          </Link>
        </div>
      </nav>

      <main className="relative z-10 flex-1 flex flex-col items-center justify-center px-6 pt-14">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 1, ease }}
          className="flex flex-col items-center text-center max-w-2xl"
        >
          <h1 className="text-3xl sm:text-4xl md:text-5xl font-bold tracking-tight leading-[1.1]">
            Give Claude a hard&nbsp;drive.
          </h1>

          <p className="mt-5 text-base sm:text-lg text-muted-foreground max-w-lg leading-relaxed">
            A persistent knowledge base Claude can read, write, and search &mdash; across every conversation. Free and open&nbsp;source.
          </p>

          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.4, ease }}
            className="mt-9"
          >
            <Link
              href="/signup"
              className="inline-flex items-center gap-2 rounded-full bg-foreground text-background px-6 py-2.5 text-sm font-medium hover:opacity-90 transition-opacity"
            >
              Get started
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" className="opacity-60">
                <path d="M6 3l5 5-5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </Link>
          </motion.div>
        </motion.div>
      </main>

      <footer className="relative z-10 py-8 px-6 text-center">
        <span className="text-xs text-muted-foreground/50">
          Free &amp; open source
        </span>
      </footer>
    </div>
  )
}
