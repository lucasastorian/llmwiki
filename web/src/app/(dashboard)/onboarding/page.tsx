'use client'

import * as React from 'react'
import { useRouter } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Copy, Check, Loader2, ArrowRight, ArrowLeft,
  FileText, BookOpen, PenTool, ExternalLink,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { apiFetch } from '@/lib/api'
import { MCP_URL } from '@/lib/mcp'
import { useUserStore, useKBStore } from '@/stores'

type Step = 'welcome' | 'create' | 'connect' | 'done'
const STEPS: Step[] = ['welcome', 'create', 'connect', 'done']

export default function OnboardingPage() {
  const router = useRouter()
  const token = useUserStore((s) => s.accessToken)
  const user = useUserStore((s) => s.user)
  const setOnboarded = useUserStore((s) => s.setOnboarded)
  const createKB = useKBStore((s) => s.createKB)

  const [step, setStep] = React.useState<Step>('welcome')
  const [direction, setDirection] = React.useState(1)
  const [wikiName, setWikiName] = React.useState('')
  const [creating, setCreating] = React.useState(false)
  const [createdSlug, setCreatedSlug] = React.useState<string | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [urlCopied, setUrlCopied] = React.useState(false)

  const stepIndex = STEPS.indexOf(step)

  const goToStep = React.useCallback((target: Step) => {
    const from = STEPS.indexOf(step)
    const to = STEPS.indexOf(target)
    setDirection(to >= from ? 1 : -1)
    setStep(target)
  }, [step])

  React.useEffect(() => {
    if (user) {
      const name = user.email.split('@')[0]
      setWikiName(`${name.charAt(0).toUpperCase() + name.slice(1)}'s Wiki`)
    }
  }, [user])

  const handleCreateWiki = async () => {
    if (!token || !wikiName.trim()) return
    setCreating(true)
    setError(null)
    try {
      const kb = await createKB(wikiName.trim())
      setCreatedSlug(kb.slug)
      goToStep('connect')
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to create wiki'
      setError(msg)
    } finally {
      setCreating(false)
    }
  }

  const handleCopyUrl = async () => {
    try {
      await navigator.clipboard.writeText(MCP_URL)
      setUrlCopied(true)
      setTimeout(() => setUrlCopied(false), 2000)
    } catch { /* */ }
  }

  const handleComplete = async () => {
    if (!token) return
    try {
      await apiFetch('/v1/onboarding/complete', token, { method: 'POST' })
    } catch { /* continue anyway */ }
    setOnboarded(true)
    router.replace(createdSlug ? `/wikis/${createdSlug}` : '/wikis')
  }

  return (
    <div className="h-full min-h-0 flex flex-col bg-background">
      {/* Progress bar */}
      <div className="shrink-0 px-8 pt-8 pb-0">
        <div className="max-w-lg mx-auto flex gap-1.5">
          {STEPS.map((s, i) => (
            <div
              key={s}
              className={cn(
                'h-1 flex-1 rounded-full transition-colors duration-300',
                i <= stepIndex ? 'bg-foreground' : 'bg-border',
              )}
            />
          ))}
        </div>
      </div>

      {/* Step content */}
      <div className="flex-1 min-h-0 flex items-center justify-center p-8">
        <div className="w-full max-w-lg">
          <AnimatePresence mode="wait" custom={direction}>

          {step === 'welcome' && (
            <motion.div
              key="welcome"
              custom={direction}
              initial={{ opacity: 0, x: direction * 40 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: direction * -40 }}
              transition={{ duration: 0.25, ease: [0.25, 0.1, 0.25, 1] }}
              className="text-center"
            >
              <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-foreground mb-8">
                <BookOpen size={28} className="text-background" />
              </div>
              <h1 className="text-3xl font-bold tracking-tight">
                Welcome to LLM Wiki
              </h1>
              <p className="mt-4 text-base text-muted-foreground leading-relaxed max-w-sm mx-auto">
                Your LLM compiles and maintains a structured wiki from your raw sources.
              </p>

              <div className="grid grid-cols-3 gap-3 mt-10 text-left">
                {[
                  { icon: FileText, title: 'Sources', desc: 'PDFs, notes, transcripts' },
                  { icon: BookOpen, title: 'Wiki', desc: 'Auto-generated pages' },
                  { icon: PenTool, title: 'Tools', desc: 'Search, read, write via MCP' },
                ].map((item) => (
                  <div key={item.title} className="rounded-xl border border-border p-4 bg-card">
                    <item.icon className="size-4 text-muted-foreground mb-2.5" strokeWidth={1.5} />
                    <h3 className="text-sm font-semibold">{item.title}</h3>
                    <p className="text-[11px] text-muted-foreground mt-0.5">{item.desc}</p>
                  </div>
                ))}
              </div>

              <button
                onClick={() => goToStep('create')}
                className="mt-10 inline-flex items-center gap-2 rounded-full bg-foreground text-background px-8 py-3 text-sm font-medium hover:opacity-90 transition-opacity cursor-pointer"
              >
                Get started
                <ArrowRight className="size-3.5" />
              </button>
            </motion.div>
          )}

          {step === 'create' && (
            <motion.div
              key="create"
              custom={direction}
              initial={{ opacity: 0, x: direction * 40 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: direction * -40 }}
              transition={{ duration: 0.25, ease: [0.25, 0.1, 0.25, 1] }}
            >
              <button
                onClick={() => goToStep('welcome')}
                className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer mb-8"
              >
                <ArrowLeft className="size-3" />
                Back
              </button>

              <h1 className="text-2xl font-bold tracking-tight">
                Name your wiki
              </h1>
              <p className="mt-2 text-sm text-muted-foreground">
                This is your knowledge space. You can rename it anytime.
              </p>

              <div className="mt-8">
                <input
                  type="text"
                  value={wikiName}
                  onChange={(e) => setWikiName(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleCreateWiki()}
                  placeholder="My Research"
                  className="w-full rounded-xl border border-border bg-card px-4 py-3.5 text-base focus:outline-none focus:ring-2 focus:ring-foreground/20 transition-shadow"
                  autoFocus
                />
              </div>

              {error && (
                <p className="mt-3 text-sm text-red-500">{error}</p>
              )}

              <button
                onClick={handleCreateWiki}
                disabled={creating || !wikiName.trim() || !token}
                className="mt-6 w-full inline-flex items-center justify-center gap-2 rounded-full bg-foreground text-background px-8 py-3 text-sm font-medium hover:opacity-90 transition-opacity cursor-pointer disabled:opacity-40"
              >
                {creating ? (
                  <><Loader2 size={15} className="animate-spin" /> Creating...</>
                ) : (
                  <>Create wiki <ArrowRight className="size-3.5" /></>
                )}
              </button>
            </motion.div>
          )}

          {step === 'connect' && (
            <motion.div
              key="connect"
              custom={direction}
              initial={{ opacity: 0, x: direction * 40 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: direction * -40 }}
              transition={{ duration: 0.25, ease: [0.25, 0.1, 0.25, 1] }}
            >
              <button
                onClick={() => goToStep('create')}
                className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer mb-8"
              >
                <ArrowLeft className="size-3" />
                Back
              </button>

              <h1 className="text-2xl font-bold tracking-tight">
                Connect Claude
              </h1>
              <p className="mt-2 text-sm text-muted-foreground">
                Add LLM Wiki as a connector so Claude can read and write to your wiki.
              </p>

              <div className="mt-8 space-y-6">
                {/* MCP URL */}
                <div className="flex items-center gap-2">
                  <code className="flex-1 text-sm font-mono bg-muted rounded-xl px-4 py-3 border border-border select-all truncate">
                    {MCP_URL}
                  </code>
                  <button
                    onClick={handleCopyUrl}
                    className={cn(
                      'shrink-0 flex items-center gap-1.5 rounded-xl px-4 py-3 text-sm font-medium transition-colors cursor-pointer',
                      urlCopied
                        ? 'bg-green-500/10 text-green-600 dark:text-green-400'
                        : 'bg-foreground text-background hover:opacity-90'
                    )}
                  >
                    {urlCopied ? <><Check size={14} /> Copied</> : <><Copy size={14} /> Copy</>}
                  </button>
                </div>

                {/* Steps */}
                <div className="rounded-xl border border-border bg-card p-5">
                  <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground/50 mb-3">
                    In Claude
                  </p>
                  <ol className="space-y-2.5">
                    {[
                      <>Open <strong>Settings</strong></>,
                      <>Go to <strong>Connectors</strong></>,
                      <>Click <strong>Add custom connector</strong></>,
                      'Paste the URL above and approve access',
                      'Sign in with your account when prompted',
                    ].map((text, i) => (
                      <li key={i} className="flex items-start gap-3 text-sm">
                        <span className="flex items-center justify-center w-5 h-5 rounded-full bg-muted text-[10px] font-bold text-muted-foreground shrink-0 mt-0.5">
                          {i + 1}
                        </span>
                        <span className="text-foreground/80">{text}</span>
                      </li>
                    ))}
                  </ol>
                </div>
              </div>

              <div className="flex gap-3 mt-8">
                <button
                  onClick={() => goToStep('done')}
                  className="flex-1 inline-flex items-center justify-center gap-2 rounded-full bg-foreground text-background px-8 py-3 text-sm font-medium hover:opacity-90 transition-opacity cursor-pointer"
                >
                  Continue
                  <ArrowRight className="size-3.5" />
                </button>
              </div>

              <button
                onClick={() => goToStep('done')}
                className="mt-3 w-full text-center text-xs text-muted-foreground/50 hover:text-muted-foreground transition-colors cursor-pointer"
              >
                Skip — I&apos;ll set this up later
              </button>
            </motion.div>
          )}

          {step === 'done' && (
            <motion.div
              key="done"
              custom={direction}
              initial={{ opacity: 0, x: direction * 40 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: direction * -40 }}
              transition={{ duration: 0.25, ease: [0.25, 0.1, 0.25, 1] }}
              className="text-center"
            >
              <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-green-500/10 mb-8">
                <Check size={28} className="text-green-600 dark:text-green-400" />
              </div>
              <h1 className="text-2xl font-bold tracking-tight">
                You&apos;re all set
              </h1>
              <p className="mt-3 text-sm text-muted-foreground leading-relaxed max-w-sm mx-auto">
                Upload some sources to your wiki, then ask Claude to compile them into structured pages.
              </p>

              <button
                onClick={handleComplete}
                className="mt-10 inline-flex items-center justify-center gap-2 rounded-full bg-foreground text-background px-8 py-3 text-sm font-medium hover:opacity-90 transition-opacity cursor-pointer"
              >
                Go to my wiki
                <ArrowRight className="size-3.5" />
              </button>

              <div className="mt-6">
                <a
                  href="https://claude.ai"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
                >
                  <ExternalLink size={12} />
                  Open Claude
                </a>
              </div>
            </motion.div>
          )}

          </AnimatePresence>
        </div>
      </div>
    </div>
  )
}
