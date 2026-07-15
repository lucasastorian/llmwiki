'use client'

import * as React from 'react'
import { useRouter } from 'next/navigation'
import { AnimatePresence, motion } from 'framer-motion'
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Check,
  ListTree,
  Loader2,
} from 'lucide-react'
import {
  McpConnectionSetup,
  type McpClient,
} from '@/components/connections/McpConnectionSetup'
import { UserMenu } from '@/components/layout/UserMenu'
import { apiFetch } from '@/lib/api'
import { ONBOARDING_PREVIEW_ENABLED } from '@/lib/onboarding-preview'
import { cn } from '@/lib/utils'
import { useKBStore, useUserStore } from '@/stores'

type Step = 'choose' | 'name' | 'connect' | 'done'
type WikiKind = 'wiki' | 'course'

const STEPS: Step[] = ['choose', 'name', 'connect', 'done']
const CLIENT_LABELS: Record<McpClient, string> = {
  claude: 'Claude',
  chatgpt: 'ChatGPT',
  codex: 'Codex',
  other: 'another AI',
}
const isLocal = process.env.NEXT_PUBLIC_MODE === 'local'
const transition = { duration: 0.25, ease: [0.22, 1, 0.36, 1] as const }

export default function OnboardingPage() {
  return isLocal && !ONBOARDING_PREVIEW_ENABLED
    ? <LocalOnboardingRedirect />
    : <HostedOnboardingPage />
}

function LocalOnboardingRedirect() {
  const router = useRouter()

  React.useEffect(() => {
    router.replace('/wikis')
  }, [router])

  return null
}

function HostedOnboardingPage() {
  const router = useRouter()
  const token = useUserStore((state) => state.accessToken)
  const user = useUserStore((state) => state.user)
  const setOnboarded = useUserStore((state) => state.setOnboarded)
  const knowledgeBases = useKBStore((state) => state.knowledgeBases)
  const createKB = useKBStore((state) => state.createKB)

  const [step, setStep] = React.useState<Step>('choose')
  const [direction, setDirection] = React.useState(1)
  const [wikiKind, setWikiKind] = React.useState<WikiKind | null>(null)
  const [wikiName, setWikiName] = React.useState('')
  const [nameTouched, setNameTouched] = React.useState(false)
  const [creating, setCreating] = React.useState(false)
  const [completing, setCompleting] = React.useState(false)
  const [createdSlug, setCreatedSlug] = React.useState<string | null>(null)
  const [createdName, setCreatedName] = React.useState<string | null>(null)
  const [connectionSkipped, setConnectionSkipped] = React.useState(false)
  const [connectionClient, setConnectionClient] = React.useState<McpClient>('claude')
  const [createError, setCreateError] = React.useState<string | null>(null)
  const [finishError, setFinishError] = React.useState<string | null>(null)
  const [previewNotice, setPreviewNotice] = React.useState<string | null>(null)

  const stepIndex = STEPS.indexOf(step)

  const goToStep = React.useCallback((target: Step) => {
    const currentIndex = STEPS.indexOf(step)
    const targetIndex = STEPS.indexOf(target)
    setDirection(targetIndex >= currentIndex ? 1 : -1)
    setStep(target)
  }, [step])

  const defaultNameFor = React.useCallback((kind: WikiKind) => {
    const suffix = kind === 'course' ? 'Course' : 'Wiki'
    if (ONBOARDING_PREVIEW_ENABLED || !user) return `My ${suffix}`
    const name = user.email.split('@')[0]
    const displayName = name.charAt(0).toUpperCase() + name.slice(1)
    return `${displayName}'s ${suffix}`
  }, [user])

  React.useEffect(() => {
    if (ONBOARDING_PREVIEW_ENABLED || createdSlug || knowledgeBases.length === 0) return
    const existing = knowledgeBases[0]
    setCreatedSlug(existing.slug)
    setCreatedName(existing.name)
    setWikiName(existing.name)
    setWikiKind(existing.kind ?? 'wiki')
    setStep('connect')
  }, [createdSlug, knowledgeBases])

  const handleChooseKind = (kind: WikiKind) => {
    setWikiKind(kind)
    if (!nameTouched) setWikiName(defaultNameFor(kind))
    setCreateError(null)
    goToStep('name')
  }

  const handleCreate = async () => {
    const name = wikiName.trim()
    if (!wikiKind || !name || creating) return
    if (!ONBOARDING_PREVIEW_ENABLED && !token) {
      setCreateError('Your session is still loading. Wait a moment, then try again.')
      return
    }

    setCreating(true)
    setCreateError(null)
    try {
      if (ONBOARDING_PREVIEW_ENABLED) {
        setCreatedSlug('onboarding-preview')
        setCreatedName(name)
        goToStep('connect')
        return
      }
      const kb = await createKB(name, undefined, wikiKind)
      setCreatedSlug(kb.slug)
      setCreatedName(kb.name)
      goToStep('connect')
    } catch (error) {
      setCreateError(error instanceof Error ? error.message : 'Could not create your wiki. Try again.')
    } finally {
      setCreating(false)
    }
  }

  const handleConnectionDecision = (skipped: boolean) => {
    setConnectionSkipped(skipped)
    setFinishError(null)
    goToStep('done')
  }

  const handleComplete = async () => {
    if (completing) return
    if (ONBOARDING_PREVIEW_ENABLED) {
      setPreviewNotice('Preview complete. Nothing was saved.')
      return
    }
    if (!token) {
      setFinishError('Your session is still loading. Wait a moment, then try again.')
      return
    }

    setCompleting(true)
    setFinishError(null)
    try {
      await apiFetch('/v1/onboarding/complete', token, { method: 'POST' })
      setOnboarded(true)
      router.replace(createdSlug ? `/wikis/${createdSlug}` : '/wikis')
    } catch {
      setFinishError('Could not save your setup progress. Check your connection and try again.')
      setCompleting(false)
    }
  }

  const handleRestartPreview = () => {
    setStep('choose')
    setDirection(-1)
    setWikiKind(null)
    setWikiName('')
    setNameTouched(false)
    setCreating(false)
    setCompleting(false)
    setCreatedSlug(null)
    setCreatedName(null)
    setConnectionSkipped(false)
    setConnectionClient('claude')
    setCreateError(null)
    setFinishError(null)
    setPreviewNotice(null)
  }

  const itemLabel = wikiKind === 'course' ? 'course' : 'wiki'

  return (
    <div className="relative flex h-full min-h-0 flex-col bg-background">
      <div className="absolute right-4 top-4 z-10 flex items-center gap-2 text-xs text-muted-foreground">
        {ONBOARDING_PREVIEW_ENABLED ? (
          <span>Local preview · no changes saved</span>
        ) : (
          <>
            {user?.email && <span className="hidden sm:inline">{user.email}</span>}
            <UserMenu />
          </>
        )}
      </div>

      <div className="shrink-0 px-8 pb-0 pt-8">
        <div
          className="mx-auto flex max-w-lg gap-1.5"
          role="progressbar"
          aria-label="Onboarding progress"
          aria-valuemin={1}
          aria-valuemax={STEPS.length}
          aria-valuenow={stepIndex + 1}
          aria-valuetext={`Step ${stepIndex + 1} of ${STEPS.length}`}
        >
          {STEPS.map((item, index) => (
            <div
              key={item}
              className={cn(
                'h-1 flex-1 rounded-full transition-colors duration-200',
                index <= stepIndex ? 'bg-foreground' : 'bg-border',
              )}
            />
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="flex min-h-full items-start justify-center px-6 py-12 sm:px-8 sm:py-16">
          <div className="relative w-full max-w-lg">
            <AnimatePresence initial={false} mode="popLayout" custom={direction}>
              {step === 'choose' && (
                <motion.section
                  key="choose"
                  custom={direction}
                  initial={{ opacity: 0, x: direction * 18 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: direction * -18 }}
                  transition={transition}
                  className="w-full text-center"
                  aria-labelledby="choose-title"
                >
                  <div className="mb-7 inline-flex size-14 items-center justify-center rounded-2xl bg-foreground text-background">
                    <BookOpen className="size-6" />
                  </div>
                  <h1 id="choose-title" className="text-3xl font-bold tracking-tight">
                    What do you want to build?
                  </h1>
                  <p className="mx-auto mt-3 max-w-sm text-sm leading-relaxed text-muted-foreground">
                    Start with a flexible wiki or an ordered course. You can change this later.
                  </p>

                  <div className="mt-8 overflow-hidden rounded-xl border border-border bg-card text-left">
                    {([
                      ['wiki', 'Wiki', 'Explore a topic through connected pages.', BookOpen],
                      ['course', 'Course', 'Follow ordered lessons and resume your progress.', ListTree],
                    ] as const).map(([kind, title, description, Icon], index) => (
                      <button
                        key={kind}
                        type="button"
                        onClick={() => handleChooseKind(kind)}
                        className={cn(
                          'flex w-full items-center gap-4 px-4 py-4 text-left transition-colors hover:bg-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring',
                          index > 0 && 'border-t border-border',
                        )}
                      >
                        <Icon className="size-4 shrink-0 text-muted-foreground" />
                        <span className="min-w-0 flex-1">
                          <span className="block text-sm font-semibold">{title}</span>
                          <span className="mt-0.5 block text-xs text-muted-foreground">{description}</span>
                        </span>
                        <ArrowRight className="size-3.5 shrink-0 text-muted-foreground" />
                      </button>
                    ))}
                  </div>
                </motion.section>
              )}

              {step === 'name' && wikiKind && (
                <motion.section
                  key="name"
                  custom={direction}
                  initial={{ opacity: 0, x: direction * 18 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: direction * -18 }}
                  transition={transition}
                  className="w-full"
                  aria-labelledby="name-title"
                >
                  <StepBack onClick={() => goToStep('choose')} />
                  <h1 id="name-title" className="text-2xl font-bold tracking-tight">
                    Name your {itemLabel}
                  </h1>
                  <p className="mt-2 text-sm text-muted-foreground">
                    You can rename it at any time.
                  </p>

                  <input
                    type="text"
                    value={wikiName}
                    onChange={(event) => {
                      setWikiName(event.target.value)
                      setNameTouched(true)
                      setCreateError(null)
                    }}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') void handleCreate()
                    }}
                    placeholder={wikiKind === 'course' ? 'Intro to reinforcement learning' : 'My research'}
                    maxLength={100}
                    aria-invalid={Boolean(createError)}
                    className="mt-8 w-full rounded-xl border border-border bg-card px-4 py-3.5 text-base outline-none transition-shadow focus:ring-2 focus:ring-foreground/20"
                    autoFocus
                  />

                  {createError && (
                    <p role="alert" className="mt-3 text-sm text-destructive">
                      {createError}
                    </p>
                  )}

                  <button
                    type="button"
                    onClick={() => void handleCreate()}
                    disabled={creating || !wikiName.trim() || (!ONBOARDING_PREVIEW_ENABLED && !token)}
                    className="mt-6 inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-full bg-foreground px-8 text-sm font-medium text-background transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {creating ? <Loader2 className="size-4 animate-spin" /> : null}
                    {creating ? 'Creating…' : `Create ${itemLabel}`}
                    {!creating && <ArrowRight className="size-3.5" />}
                  </button>
                </motion.section>
              )}

              {step === 'connect' && (
                <motion.section
                  key="connect"
                  custom={direction}
                  initial={{ opacity: 0, x: direction * 18 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: direction * -18 }}
                  transition={transition}
                  className="w-full"
                  aria-labelledby="connect-title"
                >
                  <StepBack onClick={() => goToStep('name')} />
                  <h1 id="connect-title" className="text-2xl font-bold tracking-tight">
                    Connect {connectionClient === 'other' ? 'another AI' : CLIENT_LABELS[connectionClient]}
                  </h1>
                  <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                    Add LLM Wiki so your AI can read and write your {itemLabel}.
                  </p>

                  <McpConnectionSetup
                    className="mt-7"
                    defaultClient={connectionClient}
                    wikiName={createdName ?? undefined}
                    showClientHeading={false}
                    showStarterPrompt={false}
                    onClientChange={setConnectionClient}
                  />

                  <div className="mt-7 border-t border-border pt-6">
                    <button
                      type="button"
                      onClick={() => handleConnectionDecision(false)}
                      className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-full bg-foreground px-8 text-sm font-medium text-background transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      Continue
                      <ArrowRight className="size-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={() => handleConnectionDecision(true)}
                      className="mt-3 w-full text-center text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      Skip for now
                    </button>
                  </div>
                </motion.section>
              )}

              {step === 'done' && (
                <motion.section
                  key="done"
                  custom={direction}
                  initial={{ opacity: 0, x: direction * 18 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: direction * -18 }}
                  transition={transition}
                  className="w-full text-center"
                  aria-labelledby="done-title"
                >
                  <div className="mb-7 inline-flex size-14 items-center justify-center rounded-full bg-green-500/10 text-green-600 dark:text-green-400">
                    <Check className="size-6" />
                  </div>
                  <h1 id="done-title" className="text-2xl font-bold tracking-tight">
                    Your {itemLabel} is ready
                  </h1>
                  <p className="mx-auto mt-3 max-w-sm text-sm leading-relaxed text-muted-foreground">
                    {connectionSkipped
                      ? 'Start exploring now. Connect AI later from the lower-right corner of your wiki.'
                      : 'Start with a prompt, web research, or sources, then read and refine what your AI builds.'}
                  </p>

                  {finishError && (
                    <p role="alert" className="mt-5 text-sm text-destructive">
                      {finishError}
                    </p>
                  )}

                  {previewNotice ? (
                    <div className="mt-8">
                      <p role="status" className="text-sm text-muted-foreground">{previewNotice}</p>
                      <button
                        type="button"
                        onClick={handleRestartPreview}
                        className="mt-4 text-sm font-medium underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        Restart preview
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => void handleComplete()}
                      disabled={completing}
                      className="mt-9 inline-flex min-h-11 items-center justify-center gap-2 rounded-full bg-foreground px-8 text-sm font-medium text-background transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-40"
                    >
                      {completing && <Loader2 className="size-4 animate-spin" />}
                      {ONBOARDING_PREVIEW_ENABLED ? 'Finish preview' : `View my ${itemLabel}`}
                      {!completing && <ArrowRight className="size-3.5" />}
                    </button>
                  )}

                  <button
                    type="button"
                    onClick={() => goToStep('connect')}
                    className="mx-auto mt-5 block text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    Back to connection setup
                  </button>
                </motion.section>
              )}
            </AnimatePresence>
          </div>
        </div>
      </div>
    </div>
  )
}

function StepBack({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="mb-7 flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <ArrowLeft className="size-3" />
      Back
    </button>
  )
}
