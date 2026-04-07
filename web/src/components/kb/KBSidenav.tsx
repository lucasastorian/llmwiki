'use client'

import * as React from 'react'
import {
  ChevronRight, FileText, FolderOpen, NotepadText, Folder, Loader2,
  Upload, BookOpen, ArrowUpRight, Plus, Search as SearchIcon,
  Image, Sheet, Presentation, FileCode,
  Lightbulb, Landmark, ScrollText,
} from 'lucide-react'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import {
  CommandDialog, CommandInput, CommandList, CommandItem,
  CommandEmpty, CommandGroup, CommandSeparator,
} from '@/components/ui/command'
import { cn } from '@/lib/utils'
import { SourceContextMenu, SourceAreaContextMenu } from '@/components/kb/ContextMenus'
import { WikiSelector } from '@/components/kb/WikiSelector'
import { SidenavUserMenu } from '@/components/kb/SidenavUserMenu'
import { apiFetch } from '@/lib/api'
import { useUserStore } from '@/stores'
import type { DocumentListItem, WikiNode, WikiSubsection } from '@/lib/types'

interface Usage {
  total_pages: number
  total_storage_bytes: number
  document_count: number
  max_pages: number
  max_storage_bytes: number
}

interface SourceNode {
  type: 'folder' | 'document'
  name: string
  doc?: DocumentListItem
  children?: SourceNode[]
}

function buildSourceTree(docs: DocumentListItem[]): SourceNode[] {
  const folders = new Map<string, SourceNode>()
  const root: SourceNode[] = []

  const getOrCreateFolder = (path: string): SourceNode[] => {
    if (path === '/') return root
    if (folders.has(path)) return folders.get(path)!.children!

    const parts = path.replace(/^\//, '').replace(/\/$/, '').split('/')
    let current = root
    let accumulated = '/'

    for (const part of parts) {
      accumulated += part + '/'
      if (!folders.has(accumulated)) {
        const folder: SourceNode = {
          type: 'folder',
          name: part,
          children: [],
        }
        folders.set(accumulated, folder)
        current.push(folder)
      }
      current = folders.get(accumulated)!.children!
    }
    return current
  }

  for (const doc of docs) {
    const parent = getOrCreateFolder(doc.path ?? '/')
    parent.push({
      type: 'document',
      name: doc.title || doc.filename,
      doc,
    })
  }

  const sortNodes = (nodes: SourceNode[]) => {
    nodes.sort((a, b) => {
      if (a.type !== b.type) return a.type === 'folder' ? -1 : 1
      return a.name.localeCompare(b.name)
    })
    for (const n of nodes) {
      if (n.children) sortNodes(n.children)
    }
  }
  sortNodes(root)
  return root
}

interface KBSidenavProps {
  kbName: string
  wikiTree: WikiNode[]
  wikiActivePath: string | null
  onWikiNavigate: (path: string) => void
  wikiActiveSubsections?: WikiSubsection[]
  onWikiSubsectionClick?: (id: string) => void
  sourceDocs: DocumentListItem[]
  activeSourceDocId: string | null
  onSourceSelect: (doc: DocumentListItem) => void
  hasWiki: boolean
  loading: boolean
  onCreateNote: () => void
  onCreateFolder: (name: string) => void
  onUpload: () => void
  onDeleteDocument: (id: string) => void
  onRenameDocument: (id: string, newTitle: string) => void
  onMoveDocument: (docId: string, targetPath: string) => void
  selectedIds?: Set<string>
  onSelect?: (docId: string, e: React.MouseEvent) => void
}

export function KBSidenav({
  kbName,
  wikiTree,
  wikiActivePath,
  onWikiNavigate,
  wikiActiveSubsections = [],
  onWikiSubsectionClick,
  sourceDocs,
  activeSourceDocId,
  onSourceSelect,
  hasWiki,
  loading,
  onCreateNote,
  onCreateFolder,
  onUpload,
  onDeleteDocument,
  onRenameDocument,
  onMoveDocument,
  selectedIds = new Set(),
  onSelect,
}: KBSidenavProps) {
  const [sourcesExpanded, setSourcesExpanded] = React.useState(() => {
    if (typeof window === 'undefined') return false
    return localStorage.getItem('llmwiki:sources-expanded') === 'true'
  })

  const prevSourceCount = React.useRef(sourceDocs.length)
  React.useEffect(() => {
    if (sourceDocs.length > prevSourceCount.current && !sourcesExpanded) {
      setSourcesExpanded(true)
      localStorage.setItem('llmwiki:sources-expanded', 'true')
    }
    prevSourceCount.current = sourceDocs.length
  }, [sourceDocs.length, sourcesExpanded])

  const toggleSources = () => {
    const next = !sourcesExpanded
    setSourcesExpanded(next)
    localStorage.setItem('llmwiki:sources-expanded', String(next))
  }

  const sourceTree = React.useMemo(() => buildSourceTree(sourceDocs), [sourceDocs])

  const [folderDialogOpen, setFolderDialogOpen] = React.useState(false)
  const [folderName, setFolderName] = React.useState('')
  const [allSourcesOpen, setAllSourcesOpen] = React.useState(false)

  const handleCreateFolder = () => {
    if (!folderName.trim()) return
    onCreateFolder(folderName.trim())
    setFolderName('')
    setFolderDialogOpen(false)
  }

  const [areaContextOpen, setAreaContextOpen] = React.useState(false)
  const [areaContextPos, setAreaContextPos] = React.useState<{ x: number; y: number } | null>(null)

  const handleSourcesAreaContext = (e: React.MouseEvent) => {
    e.preventDefault()
    setAreaContextPos({ x: e.clientX, y: e.clientY })
    setAreaContextOpen(true)
  }

  const [searchOpen, setSearchOpen] = React.useState(false)

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

  const allSearchableItems = React.useMemo(() => {
    const items: { type: 'wiki' | 'source'; title: string; path?: string; doc?: DocumentListItem }[] = []
    const addWikiNodes = (nodes: WikiNode[]) => {
      for (const node of nodes) {
        if (node.path) items.push({ type: 'wiki', title: node.title, path: node.path })
        if (node.children) addWikiNodes(node.children)
      }
    }
    addWikiNodes(wikiTree)
    for (const doc of sourceDocs) {
      items.push({ type: 'source', title: doc.title || doc.filename, doc })
    }
    return items
  }, [wikiTree, sourceDocs])

  return (
    <div className="h-full flex flex-col border-r border-border">
      {/* Wiki selector */}
      <div className="shrink-0 px-2 pt-2 pb-1">
        <WikiSelector kbName={kbName} />
      </div>

      {/* Search + Upload */}
      <div className="shrink-0 px-2 pb-1 flex items-center gap-1.5">
        <button
          onClick={() => setSearchOpen(true)}
          className="flex items-center gap-2 flex-1 px-2.5 py-1.5 text-xs text-muted-foreground/50 hover:text-muted-foreground border border-border hover:bg-accent rounded-md transition-colors cursor-pointer"
        >
          <SearchIcon className="size-3" />
          <span className="flex-1 text-left">Search</span>
          <kbd className="text-[10px] text-muted-foreground/30 bg-muted px-1 rounded">⌘K</kbd>
        </button>
        <button
          onClick={onUpload}
          className="flex items-center justify-center px-2.5 py-1.5 text-muted-foreground/50 hover:text-muted-foreground border border-border hover:bg-accent rounded-md transition-colors cursor-pointer"
          title="Upload files"
        >
          <Upload className="size-3" />
        </button>
      </div>

      {/* Search palette */}
      <CommandDialog open={searchOpen} onOpenChange={setSearchOpen}>
        <CommandInput placeholder="Search pages and sources..." />
        <CommandList>
          <CommandEmpty>No results found.</CommandEmpty>
          {allSearchableItems.some((i) => i.type === 'wiki') && (
            <CommandGroup heading="Wiki">
              {allSearchableItems.filter((i) => i.type === 'wiki').map((item) => (
                <CommandItem
                  key={`wiki-${item.path}`}
                  value={item.title}
                  onSelect={() => {
                    setSearchOpen(false)
                    if (item.path) onWikiNavigate(item.path)
                  }}
                >
                  <FileText className="size-3.5 mr-2 opacity-50" />
                  {item.title}
                </CommandItem>
              ))}
            </CommandGroup>
          )}
          {allSearchableItems.some((i) => i.type === 'source') && (
            <CommandGroup heading="Sources">
              {allSearchableItems.filter((i) => i.type === 'source').map((item) => (
                <CommandItem
                  key={`source-${item.doc?.id}`}
                  value={item.title}
                  onSelect={() => {
                    setSearchOpen(false)
                    if (item.doc) onSourceSelect(item.doc)
                  }}
                >
                  <NotepadText className="size-3.5 mr-2 opacity-50" />
                  {item.title}
                </CommandItem>
              ))}
            </CommandGroup>
          )}
          <CommandSeparator />
          <CommandGroup heading="Actions">
            <CommandItem onSelect={() => { setSearchOpen(false); onCreateNote() }}>
              <NotepadText className="size-3.5 mr-2 opacity-50" />
              New Note
            </CommandItem>
            <CommandItem onSelect={() => { setSearchOpen(false); setFolderDialogOpen(true) }}>
              <Folder className="size-3.5 mr-2 opacity-50" />
              New Folder
            </CommandItem>
            <CommandItem onSelect={() => { setSearchOpen(false); onUpload() }}>
              <Upload className="size-3.5 mr-2 opacity-50" />
              Upload Files
            </CommandItem>
          </CommandGroup>
        </CommandList>
      </CommandDialog>

      {/* Wiki + Sources — share remaining space, each scrollable */}
      <div className="flex-1 min-h-0 flex flex-col">
        {/* Wiki section */}
        <div className="flex flex-col min-h-0 px-2 pt-1" style={{ maxHeight: '50%' }}>
          <div className="flex items-center px-2 mb-1 shrink-0">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/50">
              Wiki
            </span>
          </div>
          {loading ? (
            <SidenavSkeleton lines={3} />
          ) : hasWiki ? (
            <div className="overflow-y-auto no-scrollbar space-y-0.5">
              {wikiTree.map((node, i) => (
                <WikiTreeNode
                  key={node.path ?? node.title ?? i}
                  node={node}
                  depth={0}
                  activePath={wikiActivePath}
                  onNavigate={onWikiNavigate}
                />
              ))}
            </div>
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

        {/* Sources section */}
        <div
          className="flex-1 min-h-0 flex flex-col px-2 mt-2"
          onContextMenu={handleSourcesAreaContext}
        >
        <div className="flex items-center shrink-0">
          <button
            onClick={toggleSources}
            className="flex items-center gap-1 px-2 py-1 flex-1 text-left cursor-pointer group"
          >
            <ChevronRight
              className={cn(
                'size-3 text-muted-foreground/40 transition-transform duration-150',
                sourcesExpanded && 'rotate-90',
              )}
            />
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/50 group-hover:text-muted-foreground transition-colors">
              Sources
            </span>
            {sourceDocs.length > 0 && (
              <span className="text-[10px] text-muted-foreground/30 ml-1">
                {sourceDocs.length}
              </span>
            )}
          </button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button className="p-1 rounded-md text-muted-foreground/40 hover:text-muted-foreground hover:bg-accent transition-colors cursor-pointer mr-1">
                <Plus className="size-3" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" side="bottom">
              <DropdownMenuItem onClick={onCreateNote}>
                <NotepadText className="size-3.5 mr-2" />
                New Note
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => setFolderDialogOpen(true)}>
                <Folder className="size-3.5 mr-2" />
                New Folder
              </DropdownMenuItem>
              <DropdownMenuItem onClick={onUpload}>
                <Upload className="size-3.5 mr-2" />
                Upload Files
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        {sourcesExpanded && (
          <div className="flex-1 overflow-y-auto no-scrollbar mt-0.5">
            <div className="space-y-0.5">
              {loading ? (
                <SidenavSkeleton lines={6} />
              ) : sourceTree.length > 0 ? (
                sourceTree.map((node, i) => (
                  <SourceTreeNode
                    key={node.doc?.id ?? node.name ?? i}
                    node={node}
                    depth={0}
                    activeDocId={activeSourceDocId}
                    parentPath="/"
                    onSelect={onSourceSelect}
                    onDelete={onDeleteDocument}
                    onRename={onRenameDocument}
                    onMove={onMoveDocument}
                    selectedIds={selectedIds}
                    onMultiSelect={onSelect}
                  />
                ))
              ) : (
                <div className="px-2 py-4 text-center">
                  <p className="text-xs text-muted-foreground/40 mb-2">No sources yet</p>
                  <button
                    onClick={onUpload}
                    className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
                  >
                    <Upload className="size-3" />
                    Upload files
                  </button>
                </div>
              )}
              {sourceDocs.length > 8 && (
                <button
                  onClick={() => setAllSourcesOpen(true)}
                  className="w-full px-2 py-1.5 text-[10px] text-muted-foreground/50 hover:text-muted-foreground transition-colors cursor-pointer text-center"
                >
                  View all {sourceDocs.length} sources
                </button>
              )}
            </div>
          </div>
        )}
        </div>
      </div>

      {/* Area-level context menu (right-click anywhere in sources) */}
      <SourceAreaContextMenu
        open={areaContextOpen}
        x={areaContextPos?.x ?? 0}
        y={areaContextPos?.y ?? 0}
        onNewNote={() => { setAreaContextOpen(false); onCreateNote() }}
        onNewFolder={() => {
          setAreaContextOpen(false)
          setFolderDialogOpen(true)
        }}
        onUpload={() => { setAreaContextOpen(false); onUpload() }}
        onClose={() => setAreaContextOpen(false)}
      />

      {/* Page usage + user menu at bottom */}
      <div className="shrink-0 border-t border-border p-2 space-y-1">
        <PageUsageBar />
        <SidenavUserMenu />
      </div>

      {/* New folder dialog */}
      <Dialog open={folderDialogOpen} onOpenChange={setFolderDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New folder</DialogTitle>
          </DialogHeader>
          <input
            value={folderName}
            onChange={(e) => setFolderName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleCreateFolder()}
            placeholder="Folder name"
            className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm"
            autoFocus
          />
          <DialogFooter>
            <button
              onClick={handleCreateFolder}
              disabled={!folderName.trim()}
              className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50 cursor-pointer"
            >
              Create
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* All sources dialog */}
      <Dialog open={allSourcesOpen} onOpenChange={setAllSourcesOpen}>
        <DialogContent className="max-w-2xl max-h-[80vh] flex flex-col">
          <DialogHeader>
            <DialogTitle>All Sources ({sourceDocs.length})</DialogTitle>
          </DialogHeader>
          <div className="flex-1 overflow-y-auto -mx-6 px-6">
            <div className="grid grid-cols-1 gap-0.5">
              {sourceDocs
                .sort((a, b) => (a.title || a.filename).localeCompare(b.title || b.filename))
                .map((doc) => (
                <button
                  key={doc.id}
                  onClick={() => {
                    setAllSourcesOpen(false)
                    onSourceSelect(doc)
                  }}
                  className={cn(
                    'flex items-center gap-2.5 w-full text-left px-3 py-2 rounded-md transition-colors cursor-pointer',
                    doc.id === activeSourceDocId
                      ? 'bg-accent text-foreground'
                      : 'hover:bg-accent/50 text-muted-foreground hover:text-foreground',
                  )}
                >
                  {(() => {
                    const ft = doc.file_type || ''
                    if (ft === 'pdf') return <FileText className="size-4 shrink-0 text-red-400/70" />
                    if (['png','jpg','jpeg','webp','gif'].includes(ft)) return <Image className="size-4 shrink-0 text-violet-400/70" />
                    if (['xlsx','xls','csv'].includes(ft)) return <Sheet className="size-4 shrink-0 text-emerald-500/70" />
                    if (['pptx','ppt'].includes(ft)) return <Presentation className="size-4 shrink-0 text-orange-400/70" />
                    if (['html','htm'].includes(ft)) return <FileCode className="size-4 shrink-0 text-sky-400/70" />
                    return <NotepadText className="size-4 shrink-0 opacity-50" />
                  })()}
                  <div className="flex-1 min-w-0">
                    <div className="text-sm truncate">{doc.title || doc.filename}</div>
                    <div className="text-[10px] text-muted-foreground/50">{doc.file_type.toUpperCase()}{doc.page_count ? ` · ${doc.page_count} pages` : ''}</div>
                  </div>
                </button>
              ))}
            </div>
          </div>
        </DialogContent>
      </Dialog>
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
    return <Landmark className="size-3 shrink-0 opacity-60" />

  if (depth > 0)
    return <FileText className="size-3 shrink-0 opacity-40" />

  return <FileText className="size-3 shrink-0 opacity-50" />
}

function WikiTreeNode({
  node,
  depth,
  activePath,
  onNavigate,
}: {
  node: WikiNode
  depth: number
  activePath: string | null
  onNavigate: (path: string) => void
}) {
  const hasChildren = node.children && node.children.length > 0
  const isActive = node.path != null && node.path === activePath
  const hasActiveChild = hasChildren && node.children!.some((c) => c.path === activePath)
  const [expanded, setExpanded] = React.useState(true)

  return (
    <div>
      <div
        className={cn(
          'flex items-center gap-0.5 w-full text-left text-xs rounded-md px-2 py-1 transition-colors',
          isActive
            ? 'bg-accent text-foreground font-medium'
            : 'text-muted-foreground hover:text-foreground hover:bg-accent/50',
        )}
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
      >
        {hasChildren ? (
          <button
            onClick={() => setExpanded((e) => !e)}
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
        <button
          onClick={() => node.path && onNavigate(node.path)}
          className="flex items-center gap-1.5 flex-1 min-w-0 cursor-pointer"
        >
          {wikiNodeIcon(node, depth)}
          <span className="truncate">{node.title}</span>
        </button>
      </div>
      {hasChildren && (expanded || hasActiveChild) && (
        <div className="mt-0.5">
          {node.children!.map((child, i) => (
            <WikiTreeNode
              key={child.path ?? child.title ?? i}
              node={child}
              depth={depth + 1}
              activePath={activePath}
              onNavigate={onNavigate}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function SourceTreeNode({
  node,
  depth,
  activeDocId,
  parentPath,
  onSelect,
  onDelete,
  onRename,
  onMove,
  selectedIds = new Set(),
  onMultiSelect,
}: {
  node: SourceNode
  depth: number
  activeDocId: string | null
  parentPath: string
  onSelect: (doc: DocumentListItem) => void
  onDelete: (id: string) => void
  onRename: (id: string, newTitle: string) => void
  onMove: (docId: string, targetPath: string) => void
  selectedIds?: Set<string>
  onMultiSelect?: (docId: string, e: React.MouseEvent) => void
}) {
  const [expanded, setExpanded] = React.useState(depth === 0)
  const [renaming, setRenaming] = React.useState(false)
  const [renameValue, setRenameValue] = React.useState('')
  const renameInputRef = React.useRef<HTMLInputElement>(null)
  const [contextOpen, setContextOpen] = React.useState(false)
  const [contextPos, setContextPos] = React.useState<{ x: number; y: number } | null>(null)

  const startRename = () => {
    if (!node.doc) return
    setRenameValue(node.name)
    setRenaming(true)
    setTimeout(() => renameInputRef.current?.select(), 0)
  }

  const commitRename = () => {
    const trimmed = renameValue.trim()
    if (trimmed && trimmed !== node.name && node.doc) {
      onRename(node.doc.id, trimmed)
    }
    setRenaming(false)
  }

  const folderPath = node.type === 'folder' ? parentPath + node.name + '/' : parentPath

  if (node.type === 'folder') {
    const [dragOver, setDragOver] = React.useState(false)

    return (
      <div>
        <div
          onClick={() => setExpanded((e) => !e)}
          onDragOver={(e) => {
            if (e.dataTransfer.types.includes('application/x-llmwiki-doc')) {
              e.preventDefault()
              e.dataTransfer.dropEffect = 'move'
              setDragOver(true)
            }
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragOver(false)
            const docId = e.dataTransfer.getData('application/x-llmwiki-doc')
            if (docId) onMove(docId, folderPath)
          }}
          className={cn(
            'flex items-center gap-1.5 w-full text-left text-xs rounded-md px-2 py-1 transition-colors cursor-pointer',
            dragOver
              ? 'bg-primary/10 ring-1 ring-primary'
              : 'text-muted-foreground hover:text-foreground hover:bg-accent/50',
          )}
          style={{ paddingLeft: `${depth * 12 + 8}px` }}
        >
          <ChevronRight
            className={cn(
              'size-3 shrink-0 transition-transform duration-150',
              expanded && 'rotate-90',
            )}
          />
          <FolderOpen className="size-3 shrink-0 opacity-50" />
          <span className="truncate">{node.name}</span>
        </div>
        {expanded && node.children && (
          <div className="mt-0.5">
            {node.children.map((child, i) => (
              <SourceTreeNode
                key={child.doc?.id ?? child.name ?? i}
                node={child}
                depth={depth + 1}
                activeDocId={activeDocId}
                parentPath={folderPath}
                onSelect={onSelect}
                onDelete={onDelete}
                onRename={onRename}
                onMove={onMove}
                selectedIds={selectedIds}
                onMultiSelect={onMultiSelect}
              />
            ))}
          </div>
        )}
      </div>
    )
  }

  const isActive = node.doc?.id != null && node.doc.id === activeDocId
  const isMultiSelected = node.doc?.id != null && selectedIds.has(node.doc.id)

  if (renaming) {
    return (
      <div
        className="flex items-center gap-1.5 px-2 py-0.5"
        style={{ paddingLeft: `${depth * 12 + 8 + 16}px` }}
      >
        <NotepadText className="size-3 shrink-0 opacity-50" />
        <input
          ref={renameInputRef}
          type="text"
          value={renameValue}
          onChange={(e) => setRenameValue(e.target.value)}
          onBlur={commitRename}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commitRename()
            if (e.key === 'Escape') setRenaming(false)
          }}
          className="flex-1 min-w-0 text-xs bg-background border border-border rounded px-1 py-0.5 outline-none focus:ring-1 focus:ring-ring"
          autoFocus
        />
      </div>
    )
  }

  return (
    <div
      draggable
      onDragStart={(e) => {
        if (node.doc) {
          e.dataTransfer.setData('application/x-llmwiki-doc', node.doc.id)
          e.dataTransfer.effectAllowed = 'move'
        }
      }}
      className={cn(
        'flex items-center gap-1.5 w-full text-left text-xs rounded-md px-2 py-1 transition-colors cursor-pointer group',
        isMultiSelected
          ? 'bg-primary/10 text-foreground ring-1 ring-primary/30'
          : isActive
            ? 'bg-accent text-foreground font-medium'
            : 'text-muted-foreground hover:text-foreground hover:bg-accent/50',
      )}
      style={{ paddingLeft: `${depth * 12 + 8 + 16}px` }}
      onClick={(e: React.MouseEvent) => {
        if (!node.doc) return
        if ((e.metaKey || e.ctrlKey || e.shiftKey) && onMultiSelect) {
          onMultiSelect(node.doc.id, e)
        } else {
          onSelect(node.doc)
        }
      }}
      onContextMenu={(e) => {
        e.preventDefault()
        e.stopPropagation()
        setContextPos({ x: e.clientX, y: e.clientY })
        setContextOpen(true)
      }}
    >
      {node.doc?.status === 'pending' || node.doc?.status === 'processing' ? (
        <Loader2 className="size-3 shrink-0 animate-spin text-muted-foreground/50" />
      ) : node.doc?.status === 'failed' ? (
        <FileText className="size-3 shrink-0 text-destructive/60" />
      ) : (() => {
        const ft = node.doc?.file_type || ''
        if (ft === 'pdf') return <FileText className="size-3 shrink-0 text-red-400/70" />
        if (['png','jpg','jpeg','webp','gif'].includes(ft)) return <Image className="size-3 shrink-0 text-violet-400/70" />
        if (['xlsx','xls','csv'].includes(ft)) return <Sheet className="size-3 shrink-0 text-emerald-500/70" />
        if (['pptx','ppt'].includes(ft)) return <Presentation className="size-3 shrink-0 text-orange-400/70" />
        if (['html','htm'].includes(ft)) return <FileCode className="size-3 shrink-0 text-sky-400/70" />
        return <NotepadText className="size-3 shrink-0 opacity-50" />
      })()}
      <span className="truncate flex-1">{node.name}</span>
      <SourceContextMenu
        open={contextOpen}
        x={contextPos?.x ?? 0}
        y={contextPos?.y ?? 0}
        onRename={() => { setContextOpen(false); startRename() }}
        onDelete={() => { setContextOpen(false); node.doc && onDelete(node.doc.id) }}
        onClose={() => setContextOpen(false)}
      />
    </div>
  )
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

  const pct = Math.min(100, (usage.total_pages / usage.max_pages) * 100)
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
              Pages
            </span>
            <span className="text-[10px] font-mono text-muted-foreground/40 group-hover:text-muted-foreground/60 transition-colors">
              {usage.total_pages} / {usage.max_pages}
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
            <DialogTitle>Page Usage</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 text-sm text-muted-foreground">
            <p>
              You've used <span className="font-medium text-foreground">{usage.total_pages.toLocaleString()}</span> of
              your <span className="font-medium text-foreground">{usage.max_pages.toLocaleString()}</span> page limit.
            </p>
            <div className="h-2 rounded-full bg-muted overflow-hidden">
              <div
                className={cn('h-full rounded-full transition-all', color)}
                style={{ width: `${pct}%` }}
              />
            </div>
            <p>
              Each PDF or office document consumes pages based on its length. Notes and wiki pages are free and unlimited.
            </p>
            <p className="text-xs text-muted-foreground/60">
              Individual documents are limited to 300 pages. Need more capacity? Contact us.
            </p>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}

