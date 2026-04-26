'use client'

import * as React from 'react'
import { useRouter } from 'next/navigation'
import { useKBStore, useUserStore } from '@/stores'
import {
  Plus, Loader2, Upload, LogOut, Moon, Sun, BookOpen,
} from 'lucide-react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog'
import {
  DropdownMenu, DropdownMenuTrigger, DropdownMenuContent,
  DropdownMenuItem, DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import { useTheme } from 'next-themes'
const isLocal = process.env.NEXT_PUBLIC_MODE === 'local'

function relativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return 'Just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  const months = Math.floor(days / 30)
  if (months < 12) return `${months}mo ago`
  return `${Math.floor(months / 12)}y ago`
}

export default function WikisPage() {
  const router = useRouter()
  const knowledgeBases = useKBStore((s) => s.knowledgeBases)
  const loading = useKBStore((s) => s.loading)
  const createKB = useKBStore((s) => s.createKB)
  const user = useUserStore((s) => s.user)
  const [creating, setCreating] = React.useState(false)
  const [dialogOpen, setDialogOpen] = React.useState(false)
  const [name, setName] = React.useState('')

  const handleQuickCreate = async () => {
    setCreating(true)
    try {
      const email = user?.email || 'My'
      const displayName = email.split('@')[0].charAt(0).toUpperCase() + email.split('@')[0].slice(1)
      const kb = await createKB(`${displayName}'s Wiki`)
      router.push(`/wikis/${kb.slug}`)
    } catch (err) {
      console.error('Failed to create KB:', err)
    } finally {
      setCreating(false)
    }
  }

  const handleCreate = async () => {
    if (!name.trim()) return
    setCreating(true)
    try {
      const kb = await createKB(name.trim())
      setDialogOpen(false)
      setName('')
      router.push(`/wikis/${kb.slug}`)
    } catch (err) {
      console.error('Failed to create KB:', err)
    } finally {
      setCreating(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (knowledgeBases.length === 0) {
    return (
      <div className="h-full flex flex-col">
        <PageHeader onNew={() => setDialogOpen(true)} />
        <div className="flex-1 flex flex-col items-center justify-center p-8">
          <div className="w-full max-w-2xl">
            <div className="text-center mb-12">
              <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-foreground mb-6">
                <BookOpen size={24} className="text-background" />
              </div>
              <h1 className="text-3xl font-bold tracking-tight">
                Create your first wiki
              </h1>
              <p className="mt-3 text-base text-muted-foreground leading-relaxed max-w-md mx-auto">
                Upload sources, connect Claude, and let it compile a structured wiki automatically.
              </p>
            </div>

            <div className="grid sm:grid-cols-3 gap-4 mb-10">
              {[
                {
                  step: '1',
                  title: 'Create a wiki',
                  desc: 'Name your knowledge space. You can have as many as you need.',
                },
                {
                  step: '2',
                  title: 'Add sources',
                  desc: 'Upload PDFs, notes, transcripts — anything you want Claude to learn from.',
                },
                {
                  step: '3',
                  title: 'Ask Claude',
                  desc: 'Claude reads your sources and compiles a wiki with cross-references and summaries.',
                },
              ].map((item) => (
                <div key={item.step} className="rounded-xl border border-border p-5 bg-card">
                  <div className="flex items-center justify-center w-7 h-7 rounded-full bg-foreground text-background text-xs font-bold mb-3">
                    {item.step}
                  </div>
                  <h3 className="text-sm font-semibold mb-1">{item.title}</h3>
                  <p className="text-xs text-muted-foreground leading-relaxed">{item.desc}</p>
                </div>
              ))}
            </div>

            <div className="flex flex-col items-center gap-3">
              <button
                onClick={handleQuickCreate}
                disabled={creating}
                className="inline-flex items-center justify-center gap-2.5 rounded-full bg-foreground text-background px-8 py-3 text-sm font-medium hover:opacity-90 transition-opacity cursor-pointer disabled:opacity-50"
              >
                {creating ? (
                  <><Loader2 size={15} className="animate-spin" /> Setting up...</>
                ) : (
                  <><Plus size={15} /> Get started</>
                )}
              </button>
              <button
                onClick={() => setDialogOpen(true)}
                className="text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
              >
                or create with a custom name
              </button>
            </div>
          </div>
        </div>

        <CreateWikiDialog
          open={dialogOpen}
          onOpenChange={setDialogOpen}
          name={name}
          onNameChange={setName}
          creating={creating}
          onCreate={handleCreate}
        />
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col">
      <PageHeader onNew={() => setDialogOpen(true)} />

      <div className="flex-1 overflow-y-auto">
        <div className="max-w-4xl mx-auto px-8 py-6">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {knowledgeBases.map((kb) => {
              const stats: string[] = []
              if (kb.source_count > 0) stats.push(`${kb.source_count} source${kb.source_count !== 1 ? 's' : ''}`)
              if (kb.wiki_page_count > 0) stats.push(`${kb.wiki_page_count} page${kb.wiki_page_count !== 1 ? 's' : ''}`)

              return (
                <button
                  key={kb.id}
                  onClick={() => router.push(`/wikis/${kb.slug}`)}
                  className="flex flex-col items-start gap-3 p-5 rounded-xl border border-border bg-card hover:bg-accent/50 transition-colors cursor-pointer text-left group overflow-hidden"
                >
                  <div className="flex items-center gap-3 min-w-0 w-full">
                    <div className="flex items-center justify-center w-9 h-9 rounded-lg bg-muted group-hover:bg-accent transition-colors flex-shrink-0">
                      <BookOpen size={16} className="text-muted-foreground group-hover:text-foreground transition-colors" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <h2 className="text-sm font-medium text-foreground truncate">{kb.name}</h2>
                      {kb.description && (
                        <p className="text-xs text-muted-foreground mt-0.5 truncate">{kb.description}</p>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 text-[11px] text-muted-foreground/50 w-full">
                    {stats.length > 0 ? (
                      <span>{stats.join(' \u00B7 ')}</span>
                    ) : (
                      <span className="text-muted-foreground/30">No sources yet</span>
                    )}
                    <span className="ml-auto text-muted-foreground/30 shrink-0">
                      {relativeTime(kb.updated_at)}
                    </span>
                  </div>
                </button>
              )
            })}

            <button
              onClick={() => setDialogOpen(true)}
              className="flex flex-col items-center justify-center gap-2 p-5 rounded-xl border border-dashed border-border hover:border-primary/50 hover:bg-accent/30 transition-colors cursor-pointer min-h-[112px]"
            >
              <Plus size={16} className="text-muted-foreground" />
              <span className="text-xs text-muted-foreground">New Wiki</span>
            </button>
          </div>
        </div>
      </div>

      <CreateWikiDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        name={name}
        onNameChange={setName}
        creating={creating}
        onCreate={handleCreate}
      />
    </div>
  )
}

function PageHeader({ onNew }: { onNew?: () => void }) {
  return (
    <div className="shrink-0 flex items-center justify-between px-6 h-12 border-b border-border">
      <span className="text-sm font-medium text-foreground tracking-tight">LLM Wiki</span>
      <div className="flex items-center gap-1">
        {onNew && (
          <button
            onClick={onNew}
            className="flex items-center gap-1.5 px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground hover:bg-accent rounded-md transition-colors cursor-pointer"
          >
            <Plus className="size-3" />
            New
          </button>
        )}
        <UserMenu />
      </div>
    </div>
  )
}

function UserMenu() {
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
        <button className="h-6 w-6 bg-muted border border-border rounded-full flex items-center justify-center cursor-pointer hover:bg-accent transition-colors">
          <span className="text-[9px] font-medium text-muted-foreground">{initials}</span>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-44">
        <div className="px-2 py-1.5 text-xs text-muted-foreground truncate">
          {user.email}
        </div>
        <DropdownMenuSeparator />
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

function CreateWikiDialog({
  open,
  onOpenChange,
  name,
  onNameChange,
  creating,
  onCreate,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  name: string
  onNameChange: (name: string) => void
  creating: boolean
  onCreate: () => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create wiki</DialogTitle>
        </DialogHeader>
        <input
          value={name}
          onChange={(e) => onNameChange(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && onCreate()}
          placeholder="My Research"
          className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm"
          autoFocus
        />
        <DialogFooter>
          <button
            onClick={onCreate}
            disabled={creating || !name.trim()}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50 cursor-pointer"
          >
            {creating ? 'Creating...' : 'Create'}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
