'use client'

import * as React from 'react'
import { useRouter } from 'next/navigation'
import {
  Copy, Check, Loader2, ExternalLink, ArrowRight,
  FileText, BookOpen, PenTool,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { apiFetch } from '@/lib/api'
import { MCP_URL } from '@/lib/mcp'
import { useUserStore, useKBStore } from '@/stores'

export default function OnboardingPage() {
  const router = useRouter()
  const token = useUserStore((s) => s.accessToken)
  const user = useUserStore((s) => s.user)
  const setOnboarded = useUserStore((s) => s.setOnboarded)
  const createKB = useKBStore((s) => s.createKB)

  const [phase, setPhase] = React.useState<'intro' | 'setup'>('intro')

  // Setup state
  const [urlCopied, setUrlCopied] = React.useState(false)
  const [creatingWiki, setCreatingWiki] = React.useState(false)
  const [wikiCreated, setWikiCreated] = React.useState(false)
  const [createdSlug, setCreatedSlug] = React.useState<string | null>(null)

  const handleCopyUrl = async () => {
    try {
      await navigator.clipboard.writeText(MCP_URL)
      setUrlCopied(true)
      setTimeout(() => setUrlCopied(false), 2000)
    } catch {
      console.error('Failed to copy')
    }
  }

  const handleCreateWiki = async () => {
    if (!token || !user) return
    setCreatingWiki(true)
    try {
      const displayName = user.email.split('@')[0]
      const name = `${displayName.charAt(0).toUpperCase() + displayName.slice(1)}'s Wiki`
      const kb = await createKB(name)
      setCreatedSlug(kb.slug)
      setWikiCreated(true)
    } catch (err) {
      console.error('Failed to create wiki:', err)
    } finally {
      setCreatingWiki(false)
    }
  }

  const handleComplete = async () => {
    if (!token) return
    try {
      await apiFetch('/v1/onboarding/complete', token, { method: 'POST' })
    } catch { /* continue anyway */ }
    setOnboarded(true)
    router.replace(createdSlug ? `/wikis/${createdSlug}` : '/wikis')
  }

  // Phase 1: Intro
  if (phase === 'intro') {
    return (
      <div className="min-h-full flex flex-col items-center justify-center p-8">
        <div className="w-full max-w-xl text-center">
          <h1 className="text-3xl sm:text-4xl font-bold tracking-tight leading-tight">
            Welcome to LLM Wiki
          </h1>
          <p className="mt-4 text-base text-muted-foreground leading-relaxed max-w-md mx-auto">
            Your LLM compiles and maintains a structured wiki from raw sources.
            You rarely write the wiki yourself &mdash; that&apos;s the LLM&apos;s job.
          </p>

          <div className="grid sm:grid-cols-3 gap-4 mt-10 text-left">
            {[
              {
                icon: FileText,
                title: 'Raw Sources',
                body: 'PDFs, articles, notes, transcripts. Your source of truth. The LLM reads them but never modifies them.',
              },
              {
                icon: BookOpen,
                title: 'The Wiki',
                body: 'LLM-generated pages with summaries, entities, cross-references. The LLM owns this layer.',
              },
              {
                icon: PenTool,
                title: 'The Tools',
                body: 'Search, read, and write. Claude connects via MCP and does the rest.',
              },
            ].map((item) => (
              <div key={item.title} className="rounded-xl border border-border p-5">
                <item.icon className="size-4 text-muted-foreground mb-3" strokeWidth={1.5} />
                <h3 className="font-semibold text-sm mb-1.5">{item.title}</h3>
                <p className="text-xs text-muted-foreground leading-relaxed">{item.body}</p>
              </div>
            ))}
          </div>

          <button
            onClick={() => setPhase('setup')}
            className="mt-10 inline-flex items-center gap-2 rounded-full bg-foreground text-background px-7 py-2.5 text-sm font-medium hover:opacity-90 transition-opacity cursor-pointer"
          >
            Get set up
            <ArrowRight className="size-3.5 opacity-60" />
          </button>
        </div>
      </div>
    )
  }

  // Phase 2: Setup
  return (
    <div className="min-h-full flex flex-col items-center justify-center p-8">
      <div className="w-full max-w-lg space-y-10">

        {/* Step 1: Connect Claude */}
        <section>
          <div className="flex items-center gap-3 mb-3">
            <span className={cn(
              'flex items-center justify-center w-6 h-6 rounded-full text-xs font-medium',
              urlCopied ? 'bg-foreground text-background' : 'bg-foreground text-background',
            )}>
              {urlCopied ? <Check size={12} /> : '1'}
            </span>
            <h2 className="text-base font-semibold">Connect Claude</h2>
          </div>
          <p className="text-sm text-muted-foreground mb-4 ml-9">
            Copy the URL below, add it as a connector in Claude, and sign in with Supabase when prompted.
          </p>
          <div className="ml-9 space-y-4">
            {/* MCP URL */}
            <div className="flex items-center gap-2">
              <code className="flex-1 text-sm font-mono bg-muted rounded-lg px-3 py-2.5 border border-border select-all truncate">
                {MCP_URL}
              </code>
              <button
                onClick={handleCopyUrl}
                className={cn(
                  'shrink-0 flex items-center gap-1.5 rounded-lg px-3 py-2.5 text-xs font-medium transition-colors cursor-pointer',
                  urlCopied
                    ? 'bg-green-500/10 text-green-600 dark:text-green-400'
                    : 'bg-primary text-primary-foreground hover:opacity-90'
                )}
              >
                {urlCopied ? <><Check size={12} />Copied</> : <><Copy size={12} />Copy</>}
              </button>
            </div>

            {/* Instructions */}
            <div className="rounded-lg border border-border p-3 space-y-2">
              <p className="text-xs font-medium text-foreground">In Claude:</p>
              <ol className="text-xs text-muted-foreground space-y-1 list-decimal list-inside">
                <li>Open <span className="font-medium text-foreground">Settings</span></li>
                <li>Go to <span className="font-medium text-foreground">Connectors</span></li>
                <li>Click <span className="font-medium text-foreground">Add custom connector</span></li>
                <li>Paste the URL above and approve access</li>
                <li>Sign in with your Supabase account when Claude opens the auth flow</li>
              </ol>
            </div>
          </div>
        </section>

        <div className="h-px bg-border" />

        {/* Step 2: Create wiki */}
        <section>
          <div className="flex items-center gap-3 mb-3">
            <span className={cn(
              'flex items-center justify-center w-6 h-6 rounded-full text-xs font-medium',
              wikiCreated ? 'bg-foreground text-background' : 'bg-muted text-muted-foreground',
            )}>
              {wikiCreated ? <Check size={12} /> : '2'}
            </span>
            <h2 className="text-base font-semibold">
              Create your wiki
            </h2>
          </div>
          <p className="text-sm text-muted-foreground mb-4 ml-9">
            This creates your knowledge space. You can upload source files and rename it later.
          </p>
          <div className="ml-9">
            {wikiCreated ? (
              <p className="text-sm text-green-600 dark:text-green-400 flex items-center gap-1.5">
                <Check size={14} />
                Wiki created
              </p>
            ) : (
              <button
                onClick={handleCreateWiki}
                disabled={creatingWiki}
                className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 transition-opacity cursor-pointer disabled:opacity-50"
              >
                {creatingWiki && <Loader2 size={14} className="animate-spin" />}
                {creatingWiki ? 'Creating...' : 'Create Wiki'}
              </button>
            )}
          </div>
        </section>

        <div className="h-px bg-border" />

        {/* Step 3: Ask Claude */}
        <section>
          <div className="flex items-center gap-3 mb-3">
            <span className={cn(
              'flex items-center justify-center w-6 h-6 rounded-full text-xs font-medium',
              wikiCreated ? 'bg-foreground text-background' : 'bg-muted text-muted-foreground',
            )}>
              3
            </span>
            <h2 className={cn('text-base font-semibold', !wikiCreated && 'text-muted-foreground')}>
              Ask Claude to build it
            </h2>
          </div>
          <p className={cn('text-sm text-muted-foreground mb-4 ml-9', !wikiCreated && 'opacity-50')}>
            Upload your sources, then ask Claude to read them and compile a wiki.
            Claude will create an overview, topic pages, and cross-references automatically.
          </p>
          <div className="ml-9">
            <a
              href="https://claude.ai"
              target="_blank"
              rel="noopener noreferrer"
              className={cn(
                'inline-flex items-center gap-2 rounded-lg border border-input bg-background px-4 py-2 text-sm font-medium hover:bg-accent transition-colors cursor-pointer',
                !wikiCreated && 'opacity-50 pointer-events-none'
              )}
            >
              <ExternalLink size={14} />
              Open Claude
            </a>
          </div>
        </section>

        <div className="h-px bg-border" />

        {/* Finish */}
        <button
          onClick={handleComplete}
          className="w-full flex items-center justify-center gap-2 rounded-lg bg-foreground text-background px-4 py-2.5 text-sm font-medium hover:opacity-90 transition-opacity cursor-pointer"
        >
          {wikiCreated ? 'Go to my wiki' : 'Go to dashboard'}
          <ArrowRight size={14} className="opacity-60" />
        </button>
      </div>
    </div>
  )
}
