'use client'

import * as React from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ChevronRight, FileText, NotepadText, Library,
  Upload, BookOpen, ArrowUpRight, Search as SearchIcon,
  Lightbulb, Box, ScrollText, Network, Folder, Check, Lock,
  PanelLeftClose, PanelLeftOpen,
} from 'lucide-react'
import {
  CommandDialog, CommandInput, CommandList, CommandItem,
  CommandEmpty, CommandGroup, CommandSeparator,
} from '@/components/ui/command'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'
import { WikiSelector } from '@/components/kb/WikiSelector'
import { SidenavUserMenu } from '@/components/kb/SidenavUserMenu'
import { apiFetch } from '@/lib/api'
import { useUserStore } from '@/stores'
import type { DocumentListItem, WikiNode } from '@/lib/types'

interface Usage {
  total_pages: number
  total_storage_bytes: number
  document_count: number
  max_pages: number
  max_storage_bytes: number
}

const SIDENAV_COLLAPSED_KEY = 'kb-sidenav-collapsed'

// Only normalize all-lowercase names (file slugs); preserve intentional casing like "GRPO" or "LoRA".
function toDisplayTitle(title: string): string {
  if (title !== title.toLowerCase()) return title
  return title.replace(/\b\w/g, (c) => c.toUpperCase())
}


interface KBSidenavProps {
  kbId: string
  kbName: string
  wikiTree: WikiNode[]
  wikiActivePath: string | null
  onWikiNavigate: (path: string, docNumber?: number | null) => void
  sourceDocs: DocumentListItem[]
  hasWiki: boolean
  loading: boolean
  onUpload: () => void
  filesViewActive: boolean
  onFilesToggle: () => void
  graphViewActive: boolean
  onGraphToggle: () => void
  onOpenSourceDoc: (docId: string) => void
  courseMode?: boolean
  courseCurrentPath?: string | null
  courseProgress?: { completed: number; total: number }
}

export function KBSidenav({
  kbId,
  kbName,
  wikiTree,
  wikiActivePath,
  onWikiNavigate,
  sourceDocs,
  hasWiki,
  loading,
  onUpload,
  filesViewActive,
  onFilesToggle,
  graphViewActive,
  onGraphToggle,
  onOpenSourceDoc,
  courseMode = false,
  courseCurrentPath = null,
  courseProgress,
}: KBSidenavProps) {
  const [searchOpen, setSearchOpen] = React.useState(false)
  const [collapsed, setCollapsed] = React.useState(false)

  React.useEffect(() => {
    setCollapsed(localStorage.getItem(SIDENAV_COLLAPSED_KEY) === '1')
  }, [])

  const toggleCollapsed = () => {
    const next = !collapsed
    setCollapsed(next)
    localStorage.setItem(SIDENAV_COLLAPSED_KEY, next ? '1' : '0')
  }

  React.useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setSearchOpen(true)
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [])

  const isMac = React.useMemo(() =>
    typeof navigator !== 'undefined' && /Mac|iPod|iPhone|iPad/.test(navigator.userAgent),
  [])

  const allSearchableItems = React.useMemo(() => {
    const items: { type: 'wiki' | 'source'; title: string; keywords: string; tags: string[]; path?: string; docNumber?: number | null; doc?: DocumentListItem }[] = []
    const addWikiNodes = (nodes: WikiNode[], parentPath = '') => {
      for (const node of nodes) {
        if (node.path) {
          const matchingDoc = sourceDocs.find((d) => d.path === '/wiki/' && d.filename === node.path?.split('/').pop())
          const tags = matchingDoc?.tags ?? []
          items.push({
            type: 'wiki',
            title: node.title,
            keywords: [node.title, node.path, parentPath, ...tags].filter(Boolean).join(' '),
            tags,
            path: node.path,
            docNumber: node.docNumber,
          })
        }
        if (node.children) addWikiNodes(node.children, node.title)
      }
    }
    addWikiNodes(wikiTree)
    for (const doc of sourceDocs) {
      const tags = doc.tags ?? []
      items.push({
        type: 'source',
        title: doc.title || doc.filename,
        keywords: [doc.title, doc.filename, doc.path, doc.file_type, ...tags].filter(Boolean).join(' '),
        tags,
        doc,
      })
    }
    return items
  }, [wikiTree, sourceDocs])

  const sourceCount = sourceDocs.length

  return (
    <div
      className={cn(
        'h-full flex flex-col border-r border-border overflow-hidden transition-[width] duration-200',
        collapsed ? 'w-12' : 'w-[272px]',
      )}
    >
      {collapsed && (
        <div className="flex flex-col items-center gap-1.5 pt-2">
          <button
            onClick={toggleCollapsed}
            title="Expand sidebar"
            className="flex items-center justify-center size-8 rounded-md text-muted-foreground/50 hover:text-muted-foreground hover:bg-accent transition-colors cursor-pointer"
          >
            <PanelLeftOpen className="size-3.5" />
          </button>
          <button
            onClick={() => setSearchOpen(true)}
            title="Search"
            className="flex items-center justify-center size-8 rounded-md text-muted-foreground/50 hover:text-muted-foreground hover:bg-accent transition-colors cursor-pointer"
          >
            <SearchIcon className="size-3.5" />
          </button>
          {!courseMode && (
            <>
              <button
                onClick={onGraphToggle}
                title="Knowledge graph"
                className={cn(
                  'flex items-center justify-center size-8 rounded-md transition-colors cursor-pointer',
                  graphViewActive
                    ? 'bg-accent text-foreground'
                    : 'text-muted-foreground/50 hover:text-muted-foreground hover:bg-accent',
                )}
              >
                <Network className="size-3.5" />
              </button>
              <button
                onClick={onUpload}
                title="Upload files"
                className="flex items-center justify-center size-8 rounded-md text-muted-foreground/50 hover:text-muted-foreground hover:bg-accent transition-colors cursor-pointer"
              >
                <Upload className="size-3.5" />
              </button>
            </>
          )}
        </div>
      )}

      {!collapsed && (
        <>
          {/* Wiki selector */}
          <div className="shrink-0 px-2 pt-2 pb-2 flex items-center gap-1">
            <div className="flex-1 min-w-0">
              <WikiSelector kbId={kbId} kbName={kbName} />
            </div>
            <button
              onClick={toggleCollapsed}
              title="Collapse sidebar"
              className="flex items-center justify-center size-7 shrink-0 rounded-md text-muted-foreground/50 hover:text-muted-foreground hover:bg-accent transition-colors cursor-pointer"
            >
              <PanelLeftClose className="size-3.5" />
            </button>
          </div>
        </>
      )}

      {!collapsed && courseMode && courseProgress && courseProgress.total > 0 && (
        <div className="shrink-0 px-3 pb-2 -mt-1 flex items-center gap-2">
          <div className="flex-1 h-1 rounded-full bg-muted overflow-hidden">
            <div
              className="h-full bg-foreground/30 transition-[width]"
              style={{ width: `${Math.round((courseProgress.completed / courseProgress.total) * 100)}%` }}
            />
          </div>
          <span className="text-[11px] text-muted-foreground/50 tabular-nums">
            {courseProgress.completed}/{courseProgress.total}
          </span>
        </div>
      )}

      {/* Search + Graph */}
      {!collapsed && (
      <div className="shrink-0 px-2 pb-1 flex items-center gap-1.5">
        <button
          onClick={() => setSearchOpen(true)}
          aria-label="Search pages and sources"
          className="flex items-center gap-2 flex-1 px-2.5 h-8 text-xs text-muted-foreground/50 hover:text-muted-foreground border border-border hover:bg-accent rounded-md transition-colors cursor-pointer"
        >
          <SearchIcon className="size-3" />
          <span className="flex-1 text-left">Search</span>
          <kbd className="text-[10px] text-muted-foreground/30 bg-muted px-1 rounded">{isMac ? '⌘K' : 'Ctrl+K'}</kbd>
        </button>
        {!courseMode && (
          <button
            onClick={onGraphToggle}
            className={cn(
              'flex items-center justify-center size-8 shrink-0 border rounded-md transition-colors cursor-pointer',
              graphViewActive
                ? 'bg-accent text-foreground border-border'
                : 'text-muted-foreground/50 hover:text-muted-foreground border-border hover:bg-accent',
            )}
            title="Knowledge graph"
          >
            <Network className="size-3" />
          </button>
        )}
      </div>
      )}

      {/* Search palette */}
      <CommandDialog open={searchOpen} onOpenChange={setSearchOpen}>
        <CommandInput placeholder="Jump to page, source, or action..." aria-label="Search pages and sources" />
        <CommandList>
          <CommandEmpty>No results found.</CommandEmpty>
          {allSearchableItems.some((i) => i.type === 'wiki') && (
            <CommandGroup heading="Wiki">
              {allSearchableItems.filter((i) => i.type === 'wiki').map((item) => (
                <CommandItem
                  key={`wiki-${item.path}`}
                  value={item.keywords}
                  onSelect={() => {
                    setSearchOpen(false)
                    if (item.path) onWikiNavigate(item.path, item.docNumber)
                  }}
                  className="flex items-center"
                >
                  <FileText className="size-3.5 mr-2 opacity-50 shrink-0" />
                  <span className="truncate">{toDisplayTitle(item.title)}</span>
                  {item.tags.length > 0 && (
                    <span className="ml-auto flex items-center gap-1 shrink-0 pl-2">
                      {item.tags.slice(0, 3).map((tag) => (
                        <span key={tag} className="text-[10px] text-muted-foreground/50 bg-muted px-1.5 py-0.5 rounded">
                          {tag}
                        </span>
                      ))}
                    </span>
                  )}
                </CommandItem>
              ))}
            </CommandGroup>
          )}
          {allSearchableItems.some((i) => i.type === 'source') && (
            <CommandGroup heading="Sources">
              {allSearchableItems.filter((i) => i.type === 'source').map((item) => (
                <CommandItem
                  key={`source-${item.doc?.id}`}
                  value={item.keywords}
                  onSelect={() => {
                    setSearchOpen(false)
                    if (item.doc) onOpenSourceDoc(item.doc.id)
                  }}
                  className="flex items-center"
                >
                  <NotepadText className="size-3.5 mr-2 opacity-50 shrink-0" />
                  <span className="truncate">{item.title}</span>
                  {item.tags.length > 0 && (
                    <span className="ml-auto flex items-center gap-1 shrink-0 pl-2">
                      {item.tags.slice(0, 3).map((tag) => (
                        <span key={tag} className="text-[10px] text-muted-foreground/50 bg-muted px-1.5 py-0.5 rounded">
                          {tag}
                        </span>
                      ))}
                    </span>
                  )}
                </CommandItem>
              ))}
            </CommandGroup>
          )}
          <CommandSeparator />
          <CommandGroup heading="Actions">
            <CommandItem onSelect={() => { setSearchOpen(false); onFilesToggle() }}>
              <Folder className="size-3.5 mr-2 opacity-50" />
              Browse Files
            </CommandItem>
            <CommandItem onSelect={() => { setSearchOpen(false); onUpload() }}>
              <Upload className="size-3.5 mr-2 opacity-50" />
              Upload Files
            </CommandItem>
          </CommandGroup>
        </CommandList>
      </CommandDialog>

      {/* Wiki tree — top-level folders render as sections; pages grouped beneath a guide */}
      {!collapsed && (
      <>
      <div className="flex-1 min-h-0 overflow-y-auto no-scrollbar px-2 pt-1.5">
        {loading ? (
          <SidenavSkeleton lines={3} />
        ) : hasWiki ? (
          wikiTree.map((node, i) =>
            node.children && node.children.length > 0 ? (
              <WikiSection
                key={node.path ?? node.title ?? i}
                node={node}
                activePath={wikiActivePath}
                onNavigate={onWikiNavigate}
                courseMode={courseMode}
                currentPath={courseCurrentPath}
              />
            ) : (
              <WikiLeaf
                key={node.path ?? node.title ?? i}
                node={node}
                activePath={wikiActivePath}
                onNavigate={onWikiNavigate}
                courseMode={courseMode}
                currentPath={courseCurrentPath}
              />
            ),
          )
        ) : (
          <div className="px-2 py-4 text-center">
            <BookOpen className="size-6 text-muted-foreground/20 mx-auto mb-2" />
            <p className="text-xs text-muted-foreground mb-2">No wiki yet</p>
            <a
              href="https://claude.ai"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              Open Claude
              <ArrowUpRight className="size-3" />
            </a>
          </div>
        )}
      </div>

      {/* Sources — Upload rides the row */}
      <div className="shrink-0 px-2 pb-1">
        <div className="flex items-center gap-1">
          <button
            onClick={onFilesToggle}
            className={cn(
              'flex items-center gap-2 flex-1 min-w-0 px-2.5 py-2 text-[13px] rounded-md transition-colors cursor-pointer',
              filesViewActive
                ? 'bg-accent text-foreground font-medium'
                : 'text-muted-foreground hover:text-foreground hover:bg-accent/50',
            )}
          >
            <Library className="size-3.5" />
            <span className="flex-1 text-left">Sources</span>
            {sourceCount > 0 && (
              <span className="text-[10px] text-muted-foreground/30">{sourceCount}</span>
            )}
          </button>
          {!courseMode && (
            <button
              onClick={onUpload}
              title="Upload files"
              className="flex items-center justify-center size-7 shrink-0 rounded-md text-muted-foreground/50 hover:text-muted-foreground hover:bg-accent transition-colors cursor-pointer"
            >
              <Upload className="size-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* User menu */}
      <div className="shrink-0 border-t border-border p-2">
        <SidenavUserMenu />
      </div>
      </>
      )}
    </div>
  )
}

function SidenavSkeleton({ lines }: { lines: number }) {
  return (
    <div className="space-y-1 px-2 py-1">
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className="h-5 rounded-md bg-muted/50 animate-pulse"
          style={{ width: `${60 + Math.random() * 30}%` }}
        />
      ))}
    </div>
  )
}

function wikiNodeIcon(node: WikiNode, depth: number) {
  const slug = node.path?.replace(/\.(md|txt|json)$/, '').split('/')[0] ?? ''
  const titleLower = node.title.toLowerCase()

  if (slug === 'overview' || (depth === 0 && titleLower === 'overview'))
    return <BookOpen className="size-3 shrink-0 opacity-60" />
  if (slug === 'log' || (depth === 0 && titleLower === 'log'))
    return <ScrollText className="size-3 shrink-0 opacity-60" />
  if (slug === 'concepts' || (depth === 0 && titleLower === 'concepts'))
    return <Lightbulb className="size-3 shrink-0 opacity-60" />
  if (slug === 'entities' || (depth === 0 && titleLower === 'entities'))
    return <Box className="size-3 shrink-0 opacity-60" />

  if (depth > 0)
    return <FileText className="size-3 shrink-0 opacity-40" />

  return <FileText className="size-3 shrink-0 opacity-50" />
}

// Course mode only — the only color in the app is the green completion check.
// `current` (the lesson being read) beats `locked`: a page you're on never shows a lock.
function CourseGlyph({ node, current }: { node: WikiNode; current: boolean }) {
  if (node.status === 'complete') return <Check className="size-3.5 text-emerald-500" />
  if (current) return <span className="size-1.5 rounded-full bg-foreground" />
  if (node.locked) return <Lock className="size-3 text-muted-foreground/40" />
  return <span className="size-2.5 rounded-full border border-border" />
}

function WikiLeaf({
  node,
  activePath,
  onNavigate,
  courseMode = false,
  currentPath = null,
}: {
  node: WikiNode
  activePath: string | null
  onNavigate: (path: string, docNumber?: number | null) => void
  courseMode?: boolean
  currentPath?: string | null
}) {
  const isActive = node.path != null && node.path === activePath
  const locked = courseMode && !!node.locked && !isActive
  return (
    <button
      onClick={() => { if (node.path) onNavigate(node.path, node.docNumber) }}
      title={locked ? 'Ahead of your current lesson' : undefined}
      className={cn(
        'flex items-center gap-2.5 w-full text-left text-[13px] rounded-md px-2 py-1.5 transition-colors cursor-pointer',
        locked
          ? 'text-muted-foreground/40 hover:text-muted-foreground'
          : isActive ? 'bg-accent text-foreground font-medium' : 'text-muted-foreground hover:text-foreground hover:bg-accent/50',
      )}
    >
      {courseMode
        ? <span className="grid place-items-center size-4 shrink-0"><CourseGlyph node={node} current={node.path === currentPath || isActive} /></span>
        : wikiNodeIcon(node, 0)}
      <span className="truncate flex-1 min-w-0">{toDisplayTitle(node.title)}</span>
    </button>
  )
}

function WikiSectionItem({
  node,
  activePath,
  onNavigate,
  courseMode = false,
  currentPath = null,
}: {
  node: WikiNode
  activePath: string | null
  onNavigate: (path: string, docNumber?: number | null) => void
  courseMode?: boolean
  currentPath?: string | null
}) {
  const isActive = node.path != null && node.path === activePath
  const locked = courseMode && !!node.locked && !isActive
  return (
    <button
      onClick={() => { if (node.path) onNavigate(node.path, node.docNumber) }}
      title={locked ? 'Ahead of your current lesson' : undefined}
      className={cn(
        'relative block w-full text-left text-[13px] rounded-md pl-8 pr-2 py-1.5 truncate transition-colors cursor-pointer',
        locked
          ? 'text-muted-foreground/40 hover:text-muted-foreground'
          : isActive ? 'bg-accent text-foreground font-medium' : 'text-muted-foreground hover:text-foreground hover:bg-accent/50',
      )}
    >
      {courseMode && (
        <span className="absolute left-[7px] top-1/2 -translate-y-1/2 grid place-items-center size-4 rounded-full bg-background">
          <CourseGlyph node={node} current={node.path === currentPath || isActive} />
        </span>
      )}
      {toDisplayTitle(node.title)}
    </button>
  )
}

function nodeContainsPath(node: WikiNode, activePath: string | null): boolean {
  if (activePath == null) return false
  if (node.path === activePath) return true
  return (node.children ?? []).some((c) => nodeContainsPath(c, activePath))
}

function WikiSection({
  node,
  activePath,
  onNavigate,
  courseMode = false,
  currentPath = null,
}: {
  node: WikiNode
  activePath: string | null
  onNavigate: (path: string, docNumber?: number | null) => void
  courseMode?: boolean
  currentPath?: string | null
}) {
  const hasActiveChild = (node.children ?? []).some((c) => nodeContainsPath(c, activePath))
  const [expanded, setExpanded] = React.useState(true)

  React.useEffect(() => {
    if (hasActiveChild) setExpanded(true)
  }, [hasActiveChild])

  return (
    <div className="mt-3 first:mt-0">
      <button
        onClick={() => setExpanded((prev) => !prev)}
        className="group w-full flex items-center gap-1 px-2 h-6 cursor-pointer"
      >
        <ChevronRight
          className={cn(
            'size-3 shrink-0 text-muted-foreground/30 group-hover:text-muted-foreground/60 transition-transform duration-150',
            expanded && 'rotate-90',
          )}
        />
        <span className="truncate text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/50 group-hover:text-muted-foreground/70 transition-colors">
          {toDisplayTitle(node.title)}
        </span>
      </button>
      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15, ease: [0.25, 0.1, 0.25, 1] }}
            style={{ overflow: 'hidden' }}
          >
            <div className="relative mt-0.5">
              <div className="absolute left-[15px] top-1 bottom-1 w-px bg-border" aria-hidden />
              {node.children!.map((child, i) =>
                child.children && child.children.length > 0 ? (
                  <WikiTreeNode
                    key={child.path ?? child.title ?? i}
                    node={child}
                    depth={1}
                    activePath={activePath}
                    onNavigate={onNavigate}
                    courseMode={courseMode}
                    currentPath={currentPath}
                  />
                ) : (
                  <WikiSectionItem
                    key={child.path ?? child.title ?? i}
                    node={child}
                    activePath={activePath}
                    onNavigate={onNavigate}
                    courseMode={courseMode}
                    currentPath={currentPath}
                  />
                ),
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function WikiTreeNode({
  node,
  depth,
  activePath,
  onNavigate,
  courseMode = false,
  currentPath = null,
}: {
  node: WikiNode
  depth: number
  activePath: string | null
  onNavigate: (path: string, docNumber?: number | null) => void
  courseMode?: boolean
  currentPath?: string | null
}) {
  const hasChildren = node.children && node.children.length > 0
  const isActive = node.path != null && node.path === activePath
  const hasActiveChild = hasChildren && node.children!.some((c) => c.path === activePath)
  const locked = courseMode && !!node.locked && !isActive
  const [expanded, setExpanded] = React.useState(true)

  React.useEffect(() => {
    if (hasActiveChild) setExpanded(true)
  }, [hasActiveChild])

  return (
    <div>
      <div
        className={cn(
          'flex items-center gap-1.5 w-full text-left text-[13px] rounded-md px-2 py-1.5 transition-colors cursor-pointer',
          locked
            ? 'text-muted-foreground/40 hover:text-muted-foreground'
            : isActive
              ? 'bg-accent text-foreground font-medium'
              : 'text-muted-foreground hover:text-foreground hover:bg-accent/50',
        )}
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
        title={locked ? 'Ahead of your current lesson' : undefined}
        onClick={() => {
          if (node.path) {
            onNavigate(node.path, node.docNumber)
          } else if (hasChildren) {
            const first = node.children!.find((c) => c.path)
            if (first) onNavigate(first.path!, first.docNumber)
          }
        }}
      >
        {hasChildren ? (
          <button
            onClick={(e) => { e.stopPropagation(); setExpanded((prev) => !prev) }}
            className="p-0.5 -ml-0.5 cursor-pointer"
          >
            <ChevronRight
              className={cn(
                'size-2.5 transition-transform duration-150',
                expanded && 'rotate-90',
              )}
            />
          </button>
        ) : (
          <span className="w-3.5" />
        )}
        {courseMode && node.path
          ? <span className="grid place-items-center size-4 shrink-0"><CourseGlyph node={node} current={node.path === currentPath || isActive} /></span>
          : wikiNodeIcon(node, depth)}
        <span className="truncate flex-1 min-w-0">{toDisplayTitle(node.title)}</span>
      </div>
      <AnimatePresence initial={false}>
        {hasChildren && expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15, ease: [0.25, 0.1, 0.25, 1] }}
            style={{ overflow: 'hidden' }}
            className=""
          >
            {node.children!.map((child, i) => (
              <WikiTreeNode
                key={child.path ?? child.title ?? i}
                node={child}
                depth={depth + 1}
                activePath={activePath}
                onNavigate={onNavigate}
                courseMode={courseMode}
                currentPath={currentPath}
              />
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}


function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1073741824) return `${(bytes / 1048576).toFixed(1)} MB`
  return `${(bytes / 1073741824).toFixed(1)} GB`
}

function PageUsageBar() {
  const token = useUserStore((s) => s.accessToken)
  const [usage, setUsage] = React.useState<Usage | null>(null)
  const [modalOpen, setModalOpen] = React.useState(false)

  React.useEffect(() => {
    if (!token) return
    apiFetch<Usage>('/v1/usage', token)
      .then(setUsage)
      .catch(() => {})
  }, [token])

  if (!usage) return null

  const pct = Math.min(100, (usage.total_storage_bytes / usage.max_storage_bytes) * 100)
  const color =
    pct > 90 ? 'bg-destructive' : pct > 70 ? 'bg-yellow-500' : 'bg-primary'

  return (
    <>
      <button
        onClick={() => setModalOpen(true)}
        className="flex items-center gap-2 w-full px-2 py-1 rounded-md hover:bg-accent transition-colors cursor-pointer group"
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between mb-0.5">
            <span className="text-[10px] text-muted-foreground/60 group-hover:text-muted-foreground transition-colors">
              Storage
            </span>
            <span className="text-[10px] font-mono text-muted-foreground/40 group-hover:text-muted-foreground/60 transition-colors">
              {formatBytes(usage.total_storage_bytes)} / {formatBytes(usage.max_storage_bytes)}
            </span>
          </div>
          <div className="h-1 rounded-full bg-muted overflow-hidden">
            <div
              className={cn('h-full rounded-full transition-all', color)}
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
      </button>

      <Dialog open={modalOpen} onOpenChange={setModalOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Storage Usage</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 text-sm text-muted-foreground">
            <p>
              You've used <span className="font-medium text-foreground">{formatBytes(usage.total_storage_bytes)}</span> of
              your <span className="font-medium text-foreground">{formatBytes(usage.max_storage_bytes)}</span> storage limit.
            </p>
            <div className="h-2 rounded-full bg-muted overflow-hidden">
              <div
                className={cn('h-full rounded-full transition-all', color)}
                style={{ width: `${pct}%` }}
              />
            </div>
            <p>
              Storage is consumed by uploaded files (PDFs, images, office documents). Notes and wiki pages are free and unlimited.
            </p>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}

