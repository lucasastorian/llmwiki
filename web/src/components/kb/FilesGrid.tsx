'use client'

import * as React from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  Folder, FileText, NotepadText, Loader2, Trash2,
  Upload, Plus, FolderPlus, ExternalLink, Pencil,
  ChevronLeft, ChevronRight, ArrowUp, ArrowDown, MoreHorizontal,
  Image, Sheet, Presentation, FileCode, Search, X,
} from 'lucide-react'
import {
  ContextMenu, ContextMenuTrigger, ContextMenuContent,
  ContextMenuItem, ContextMenuSeparator,
} from '@/components/ui/context-menu'
import {
  DropdownMenu, DropdownMenuTrigger, DropdownMenuContent,
  DropdownMenuItem, DropdownMenuSeparator, DropdownMenuSub,
  DropdownMenuSubTrigger, DropdownMenuSubContent,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'
import { NoteEditor } from '@/components/editor/NoteEditor'
import { NoteFormattingButtons } from '@/components/editor/NoteToolbar'
import type { Editor } from '@tiptap/react'
import {
  PdfDocViewer, ImageViewer, HtmlDocViewer, ContentViewer,
  UnsupportedViewer, ProcessingViewer, FailedViewer,
} from '@/components/kb/DocViewers'
import type { DocumentListItem } from '@/lib/types'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type SortField = 'name' | 'date' | 'type'
type SortDir = 'asc' | 'desc'

interface FolderNode {
  name: string
  path: string
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function getChildFolders(docs: DocumentListItem[], currentPath: string): FolderNode[] {
  const folders = new Map<string, FolderNode>()
  for (const doc of docs) {
    const docPath = doc.path || '/'
    if (!docPath.startsWith(currentPath) || docPath === currentPath) continue
    const rest = docPath.slice(currentPath.length)
    const nextSlash = rest.indexOf('/')
    if (nextSlash <= 0) continue
    const segment = rest.slice(0, nextSlash)
    const folderPath = currentPath + segment + '/'
    if (!folders.has(folderPath)) {
      folders.set(folderPath, { name: segment, path: folderPath })
    }
  }
  return Array.from(folders.values()).sort((a, b) => a.name.localeCompare(b.name))
}

function getDocsInFolder(docs: DocumentListItem[], currentPath: string): DocumentListItem[] {
  return docs.filter((d) => (d.path || '/') === currentPath)
}

function sortDocs(docs: DocumentListItem[], field: SortField, dir: SortDir): DocumentListItem[] {
  const sorted = [...docs]
  sorted.sort((a, b) => {
    let cmp = 0
    switch (field) {
      case 'name': cmp = (a.title || a.filename).localeCompare(b.title || b.filename); break
      case 'date': cmp = new Date(a.updated_at).getTime() - new Date(b.updated_at).getTime(); break
      case 'type': cmp = a.file_type.localeCompare(b.file_type); break
    }
    return dir === 'asc' ? cmp : -cmp
  })
  return sorted
}

function parseBreadcrumbs(path: string): { label: string; path: string }[] {
  const segments: { label: string; path: string }[] = [{ label: 'Files', path: '/' }]
  if (path === '/') return segments
  const parts = path.replace(/^\//, '').replace(/\/$/, '').split('/')
  let accumulated = '/'
  for (const part of parts) {
    accumulated += part + '/'
    segments.push({ label: part, path: accumulated })
  }
  return segments
}

function isNoteFile(doc: DocumentListItem): boolean {
  const ft = doc.file_type
  return ft === 'md' || ft === 'txt' || ft === 'note'
}

function docIcon(ft: string) {
  if (ft === 'pdf') return <FileText className="size-8 text-red-400/70" />
  if (['png', 'jpg', 'jpeg', 'webp', 'gif'].includes(ft)) return <Image className="size-8 text-violet-400/70" />
  if (['xlsx', 'xls', 'csv'].includes(ft)) return <Sheet className="size-8 text-emerald-500/70" />
  if (['pptx', 'ppt', 'docx', 'doc'].includes(ft)) return <Presentation className="size-8 text-orange-400/70" />
  if (['html', 'htm'].includes(ft)) return <FileCode className="size-8 text-sky-400/70" />
  if (['md', 'txt'].includes(ft)) return <NotepadText className="size-8 text-muted-foreground/50" />
  return <FileText className="size-8 text-muted-foreground/40" />
}

function docIconSmall(ft: string) {
  if (ft === 'pdf') return <FileText className="size-3.5 text-red-400/70" />
  if (['png', 'jpg', 'jpeg', 'webp', 'gif'].includes(ft)) return <Image className="size-3.5 text-violet-400/70" />
  if (['xlsx', 'xls', 'csv'].includes(ft)) return <Sheet className="size-3.5 text-emerald-500/70" />
  if (['pptx', 'ppt', 'docx', 'doc'].includes(ft)) return <Presentation className="size-3.5 text-orange-400/70" />
  if (['html', 'htm'].includes(ft)) return <FileCode className="size-3.5 text-sky-400/70" />
  if (['md', 'txt'].includes(ft)) return <NotepadText className="size-3.5 text-muted-foreground/50" />
  return <FileText className="size-3.5 text-muted-foreground/40" />
}

/* ------------------------------------------------------------------ */
/*  FilesGrid — unified file browser + viewer                         */
/* ------------------------------------------------------------------ */

interface FilesGridProps {
  documents: DocumentListItem[]
  onDeleteDocument: (id: string) => void
  onRenameDocument: (id: string, newTitle: string) => void
  onUpload: () => void
  onCreateNote: () => void
  onCreateFolder: (name: string) => void
  /** If set, open this doc on mount (e.g. from a citation click) */
  initialDocId?: string | null
  initialPage?: number
}

export function FilesGrid({
  documents,
  onDeleteDocument,
  onRenameDocument,
  onUpload,
  onCreateNote,
  onCreateFolder,
  initialDocId,
  initialPage,
}: FilesGridProps) {
  // Navigation state
  const [currentPath, setCurrentPath] = React.useState('/')
  const [history, setHistory] = React.useState<string[]>(['/'])
  const [historyIdx, setHistoryIdx] = React.useState(0)

  // Active document (null = browsing grid)
  const [activeDocId, setActiveDocId] = React.useState<string | null>(initialDocId ?? null)
  const [docInitialPage, setDocInitialPage] = React.useState<number | undefined>(initialPage)

  // Grid state
  const [sortField, setSortField] = React.useState<SortField>('name')
  const [sortDir, setSortDir] = React.useState<SortDir>('asc')
  const [searchQuery, setSearchQuery] = React.useState('')
  const [searchOpen, setSearchOpen] = React.useState(false)
  const searchInputRef = React.useRef<HTMLInputElement>(null)
  const [folderDialogOpen, setFolderDialogOpen] = React.useState(false)
  const [folderName, setFolderName] = React.useState('')

  // Note editor instance (for rendering formatting buttons in the toolbar)
  const [noteEditor, setNoteEditor] = React.useState<Editor | null>(null)
  // Reset editor when switching docs
  React.useEffect(() => { setNoteEditor(null) }, [activeDocId])

  // Source docs only (exclude wiki)
  const sourceDocs = React.useMemo(
    () => documents.filter((d) => !d.path.startsWith('/wiki/') && !d.archived),
    [documents],
  )

  const activeDoc = React.useMemo(
    () => activeDocId ? sourceDocs.find((d) => d.id === activeDocId) ?? null : null,
    [activeDocId, sourceDocs],
  )

  const isBrowsing = !activeDoc

  // Navigation
  const navigateTo = React.useCallback((path: string) => {
    setActiveDocId(null)
    setDocInitialPage(undefined)
    setCurrentPath(path)
    setHistory((prev) => {
      const next = prev.slice(0, historyIdx + 1)
      next.push(path)
      return next
    })
    setHistoryIdx((prev) => prev + 1)
  }, [historyIdx])

  const openDoc = React.useCallback((doc: DocumentListItem) => {
    setActiveDocId(doc.id)
    setDocInitialPage(undefined)
  }, [])

  const closeDoc = React.useCallback(() => {
    setActiveDocId(null)
    setDocInitialPage(undefined)
  }, [])

  const canGoBack = isBrowsing ? historyIdx > 0 : true
  const canGoForward = isBrowsing ? historyIdx < history.length - 1 : false

  const goBack = React.useCallback(() => {
    if (!isBrowsing) {
      closeDoc()
      return
    }
    if (historyIdx <= 0) return
    const newIdx = historyIdx - 1
    setHistoryIdx(newIdx)
    setCurrentPath(history[newIdx])
  }, [isBrowsing, closeDoc, historyIdx, history])

  const goForward = React.useCallback(() => {
    if (!isBrowsing || !canGoForward) return
    const newIdx = historyIdx + 1
    setHistoryIdx(newIdx)
    setCurrentPath(history[newIdx])
  }, [isBrowsing, canGoForward, historyIdx, history])

  // Grid data
  const folders = React.useMemo(() => getChildFolders(sourceDocs, currentPath), [sourceDocs, currentPath])
  const docsInFolder = React.useMemo(() => sortDocs(getDocsInFolder(sourceDocs, currentPath), sortField, sortDir), [sourceDocs, currentPath, sortField, sortDir])

  const filteredFolders = React.useMemo(() => {
    if (!searchQuery) return folders
    const q = searchQuery.toLowerCase()
    return folders.filter((f) => f.name.toLowerCase().includes(q))
  }, [folders, searchQuery])

  const filteredDocs = React.useMemo(() => {
    if (!searchQuery) return docsInFolder
    const q = searchQuery.toLowerCase()
    return docsInFolder.filter((d) => (d.title || d.filename).toLowerCase().includes(q) || d.file_type.toLowerCase().includes(q))
  }, [docsInFolder, searchQuery])

  const isActiveNote = activeDoc ? isNoteFile(activeDoc) : false

  // Breadcrumbs — adapt to browsing vs viewing
  // For notes, skip the doc name since NoteToolbar shows the editable title
  const breadcrumbs = React.useMemo(() => {
    const crumbs = parseBreadcrumbs(activeDoc ? (activeDoc.path || '/') : currentPath)
    if (activeDoc && !isActiveNote) {
      crumbs.push({ label: activeDoc.title || activeDoc.filename, path: '__doc__' })
    }
    return crumbs
  }, [currentPath, activeDoc, isActiveNote])

  const handleCreateFolder = () => {
    if (!folderName.trim()) return
    onCreateFolder(folderName.trim())
    setFolderName('')
    setFolderDialogOpen(false)
  }

  React.useEffect(() => {
    if (searchOpen) {
      const t = setTimeout(() => searchInputRef.current?.focus(), 50)
      return () => clearTimeout(t)
    }
  }, [searchOpen])

  const sortLabels: Record<SortField, string> = { name: 'Name', date: 'Modified', type: 'Kind' }
  const isEmpty = filteredFolders.length === 0 && filteredDocs.length === 0

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* ── Toolbar (always mounted, never flashes) ── */}
      <div className="shrink-0 flex items-center gap-1.5 px-4 py-2 border-b border-border">
        {/* Back / Forward */}
        <button
          onClick={goBack}
          disabled={!canGoBack}
          className={cn(
            'p-1 rounded-md transition-colors cursor-pointer',
            canGoBack ? 'text-muted-foreground hover:text-foreground hover:bg-accent' : 'text-muted-foreground/30 cursor-default'
          )}
        >
          <ChevronLeft className="size-4" />
        </button>
        {isBrowsing && (
          <button
            onClick={goForward}
            disabled={!canGoForward}
            className={cn(
              'p-1 rounded-md transition-colors cursor-pointer',
              canGoForward ? 'text-muted-foreground hover:text-foreground hover:bg-accent' : 'text-muted-foreground/30 cursor-default'
            )}
          >
            <ChevronRight className="size-4" />
          </button>
        )}

        {/* Breadcrumbs */}
        <nav className="flex items-center gap-1 text-sm min-w-0 mr-auto overflow-hidden ml-1">
          {breadcrumbs.map((seg, i) => {
            const isLast = i === breadcrumbs.length - 1
            const isDocLeaf = seg.path === '__doc__'
            return (
              <React.Fragment key={`${seg.path}-${i}`}>
                {i > 0 && <span className="text-muted-foreground/50 flex-shrink-0">/</span>}
                {isDocLeaf ? (
                  <span className="flex items-center gap-1.5 font-medium text-foreground truncate">
                    {activeDoc && docIconSmall(activeDoc.file_type)}
                    {seg.label}
                  </span>
                ) : isLast ? (
                  <span className="font-medium text-foreground truncate">{seg.label}</span>
                ) : (
                  <button
                    onClick={() => navigateTo(seg.path)}
                    className="truncate cursor-pointer rounded px-1 -mx-1 transition-colors text-muted-foreground hover:text-foreground"
                  >
                    {seg.label}
                  </button>
                )}
              </React.Fragment>
            )
          })}
        </nav>

        {/* Right side — grid controls when browsing, file info when viewing */}
        {isBrowsing ? (
          <>
            {/* Search */}
            <div className={cn(
              'relative flex items-center rounded-md transition-all duration-200 ease-in-out overflow-hidden',
              searchOpen ? 'w-48 bg-muted/50 border border-border' : 'w-7'
            )}>
              <button
                onClick={() => !searchOpen && setSearchOpen(true)}
                className={cn(
                  'flex-shrink-0 p-1.5 text-muted-foreground transition-colors cursor-pointer',
                  !searchOpen && 'hover:text-foreground hover:bg-accent rounded-md'
                )}
              >
                <Search className="size-3.5" />
              </button>
              {searchOpen && (
                <>
                  <input
                    ref={searchInputRef}
                    type="text"
                    placeholder="Filter..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Escape') { setSearchQuery(''); setSearchOpen(false) } }}
                    onBlur={() => { if (!searchQuery) setSearchOpen(false) }}
                    className="flex-1 min-w-0 pr-6 py-1 text-sm bg-transparent placeholder:text-muted-foreground/60 focus:outline-none"
                  />
                  <button
                    onClick={() => { setSearchQuery(''); setSearchOpen(false) }}
                    className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground cursor-pointer"
                  >
                    <X className="size-3" />
                  </button>
                </>
              )}
            </div>

            <button onClick={onUpload} className="flex items-center gap-1.5 p-1.5 text-muted-foreground hover:text-foreground hover:bg-accent rounded-md transition-colors cursor-pointer">
              <Upload className="size-3.5" />
              <span className="text-xs">Upload</span>
            </button>

            <button
              onClick={() => setSortDir((d) => d === 'asc' ? 'desc' : 'asc')}
              className="p-1.5 text-muted-foreground hover:text-foreground hover:bg-accent rounded-md transition-colors cursor-pointer"
              title={sortDir === 'asc' ? 'Ascending' : 'Descending'}
            >
              {sortDir === 'asc' ? <ArrowUp className="size-3.5" /> : <ArrowDown className="size-3.5" />}
            </button>

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button className="p-1.5 text-muted-foreground hover:text-foreground hover:bg-accent rounded-md transition-colors cursor-pointer">
                  <MoreHorizontal className="size-3.5" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => setFolderDialogOpen(true)}>
                  <FolderPlus className="size-3.5 mr-2" />
                  New Folder
                </DropdownMenuItem>
                <DropdownMenuItem onClick={onCreateNote}>
                  <NotepadText className="size-3.5 mr-2" />
                  New Note
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuSub>
                  <DropdownMenuSubTrigger>
                    {sortDir === 'asc' ? <ArrowUp className="size-3.5 mr-2" /> : <ArrowDown className="size-3.5 mr-2" />}
                    Sort by {sortLabels[sortField]}
                  </DropdownMenuSubTrigger>
                  <DropdownMenuSubContent>
                    {(Object.keys(sortLabels) as SortField[]).map((field) => (
                      <DropdownMenuItem key={field} onClick={() => setSortField(field)}>
                        {sortLabels[field]}
                        {sortField === field && (
                          <span className="ml-auto text-xs text-muted-foreground">
                            {sortDir === 'asc' ? '\u2191' : '\u2193'}
                          </span>
                        )}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuSubContent>
                </DropdownMenuSub>
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        ) : activeDoc && isActiveNote ? (
          <NoteFormattingButtons editor={noteEditor} />
        ) : activeDoc ? (
          <span className="text-[10px] text-muted-foreground/50 uppercase shrink-0">
            {activeDoc.file_type}
            {activeDoc.page_count ? ` · ${activeDoc.page_count} pages` : ''}
          </span>
        ) : null}
      </div>

      {/* ── Content area ── */}
      <div className="flex-1 min-h-0">
        {activeDoc ? (
          /* ── Document viewer ── */
          isNoteFile(activeDoc) ? (
            <NoteEditor
              key={activeDoc.id}
              documentId={activeDoc.id}
              initialTitle={activeDoc.title ?? activeDoc.filename}
              initialTags={activeDoc.tags}
              initialDate={activeDoc.date}
              initialProperties={activeDoc.metadata?.properties as Record<string, unknown> | undefined}
              embedded
              hideToolbar
              onEditorReady={setNoteEditor}
            />
          ) : activeDoc.status === 'pending' || activeDoc.status === 'processing' ? (
            <ProcessingViewer title={activeDoc.title || activeDoc.filename} />
          ) : activeDoc.status === 'failed' ? (
            <FailedViewer title={activeDoc.title || activeDoc.filename} errorMessage={activeDoc.error_message} />
          ) : ['pdf', 'pptx', 'ppt', 'docx', 'doc'].includes(activeDoc.file_type) ? (
            <PdfDocViewer documentId={activeDoc.id} title={activeDoc.title || activeDoc.filename} initialPage={docInitialPage} />
          ) : ['png', 'jpg', 'jpeg', 'webp', 'gif'].includes(activeDoc.file_type) ? (
            <ImageViewer documentId={activeDoc.id} title={activeDoc.title || activeDoc.filename} />
          ) : ['html', 'htm'].includes(activeDoc.file_type) ? (
            <HtmlDocViewer documentId={activeDoc.id} title={activeDoc.title || activeDoc.filename} />
          ) : ['xlsx', 'xls', 'csv'].includes(activeDoc.file_type) ? (
            <ContentViewer documentId={activeDoc.id} title={activeDoc.title || activeDoc.filename} fileType={activeDoc.file_type} />
          ) : (
            <UnsupportedViewer title={activeDoc.title || activeDoc.filename} />
          )
        ) : (
          /* ── File grid ── */
          <ContextMenu>
            <ContextMenuTrigger asChild>
              <div className="h-full overflow-y-auto p-4">
                {isEmpty ? (
                  <EmptyState isRoot={currentPath === '/'} onUpload={onUpload} onCreateNote={onCreateNote} />
                ) : (
                  <div className="min-h-full">
                    <div className="grid grid-cols-4 sm:grid-cols-5 lg:grid-cols-6 xl:grid-cols-8 gap-3">
                      <AnimatePresence initial={false} mode="popLayout">
                        <motion.div key="add-new" layout transition={{ layout: { duration: 0.15, ease: 'easeOut' } }} className="h-full">
                          <NewCard onCreateNote={onCreateNote} onUpload={onUpload} onCreateFolder={() => setFolderDialogOpen(true)} />
                        </motion.div>
                        {filteredFolders.map((folder) => (
                          <motion.div key={`folder-${folder.path}`} layout exit={{ opacity: 0, scale: 0.95 }} transition={{ layout: { duration: 0.15, ease: 'easeOut' }, opacity: { duration: 0.1 } }} className="h-full">
                            <FolderCard name={folder.name} onNavigate={() => navigateTo(folder.path)} />
                          </motion.div>
                        ))}
                        {filteredDocs.map((doc) => (
                          <motion.div key={doc.id} layout exit={{ opacity: 0, scale: 0.95 }} transition={{ layout: { duration: 0.15, ease: 'easeOut' }, opacity: { duration: 0.1 } }} className="h-full">
                            <DocumentCard doc={doc} onOpen={() => openDoc(doc)} onDelete={() => onDeleteDocument(doc.id)} onRename={(t) => onRenameDocument(doc.id, t)} />
                          </motion.div>
                        ))}
                      </AnimatePresence>
                    </div>
                  </div>
                )}
              </div>
            </ContextMenuTrigger>
            <ContextMenuContent>
              <ContextMenuItem onClick={onCreateNote}><NotepadText className="size-3.5 mr-2" />New Note</ContextMenuItem>
              <ContextMenuItem onClick={() => setFolderDialogOpen(true)}><FolderPlus className="size-3.5 mr-2" />New Folder</ContextMenuItem>
              <ContextMenuSeparator />
              <ContextMenuItem onClick={onUpload}><Upload className="size-3.5 mr-2" />Upload Files</ContextMenuItem>
            </ContextMenuContent>
          </ContextMenu>
        )}
      </div>

      {/* New folder dialog */}
      {folderDialogOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setFolderDialogOpen(false)}>
          <div className="bg-background border border-border rounded-lg p-6 w-80 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-sm font-medium mb-3">New folder</h3>
            <input value={folderName} onChange={(e) => setFolderName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && handleCreateFolder()} placeholder="Folder name" className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm mb-3" autoFocus />
            <div className="flex justify-end gap-2">
              <button onClick={() => setFolderDialogOpen(false)} className="rounded-lg px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors cursor-pointer">Cancel</button>
              <button onClick={handleCreateFolder} disabled={!folderName.trim()} className="rounded-lg bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50 cursor-pointer">Create</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Cards                                                              */
/* ------------------------------------------------------------------ */

function FolderCard({ name, onNavigate }: { name: string; onNavigate: () => void }) {
  return (
    <div onClick={onNavigate} className="group relative rounded-lg border border-border hover:bg-muted/50 cursor-pointer transition-colors flex flex-col overflow-hidden h-full">
      <div className="flex items-center justify-center aspect-square">
        <Folder className="size-12 text-muted-foreground/70" />
      </div>
      <div className="px-2 py-1.5">
        <span className="text-xs font-medium text-foreground truncate block">{name}</span>
      </div>
    </div>
  )
}

function DocumentCard({ doc, onOpen, onDelete, onRename }: { doc: DocumentListItem; onOpen: () => void; onDelete: () => void; onRename: (t: string) => void }) {
  const [renaming, setRenaming] = React.useState(false)
  const [renameValue, setRenameValue] = React.useState('')
  const inputRef = React.useRef<HTMLInputElement>(null)
  const isProcessing = doc.status === 'processing' || doc.status === 'pending'

  const startRename = () => {
    setRenameValue(doc.title || doc.filename)
    setRenaming(true)
    requestAnimationFrame(() => { inputRef.current?.focus(); inputRef.current?.select() })
  }

  const commitRename = () => {
    const trimmed = renameValue.trim()
    if (trimmed && trimmed !== (doc.title || doc.filename)) onRename(trimmed)
    setRenaming(false)
  }

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>
        <div onClick={onOpen} className="group relative rounded-lg border border-border hover:bg-accent/40 cursor-pointer transition-colors flex flex-col overflow-hidden h-full">
          <div className="relative flex items-center justify-center bg-muted/30 aspect-square overflow-hidden">
            <span className={cn('text-muted-foreground/40', isProcessing && 'opacity-40')}>{docIcon(doc.file_type)}</span>
            {isProcessing && <div className="absolute inset-0 flex items-center justify-center"><Loader2 className="size-5 text-muted-foreground animate-spin" /></div>}
          </div>
          <div className="px-2 py-1.5 flex flex-col gap-0.5">
            {renaming ? (
              <input ref={inputRef} type="text" value={renameValue} onChange={(e) => setRenameValue(e.target.value)} onKeyDown={(e) => { e.stopPropagation(); if (e.key === 'Enter') commitRename(); if (e.key === 'Escape') setRenaming(false) }} onBlur={commitRename} onClick={(e) => e.stopPropagation()} className="text-xs font-medium text-foreground bg-transparent border-b border-foreground/30 outline-none w-full" />
            ) : (
              <span className="text-xs text-foreground line-clamp-2 leading-tight">{doc.title || doc.filename}</span>
            )}
            <div className="flex items-center gap-1">
              <span className="text-[9px] text-muted-foreground/50 uppercase">{doc.file_type}</span>
              {doc.page_count && <span className="text-[9px] text-muted-foreground/40">· {doc.page_count}p</span>}
            </div>
            {doc.status === 'failed' && <span className="text-[9px] font-medium text-destructive/80">Failed</span>}
          </div>
        </div>
      </ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem onClick={onOpen}><ExternalLink className="size-3.5 mr-2" />Open</ContextMenuItem>
        <ContextMenuItem onClick={startRename}><Pencil className="size-3.5 mr-2" />Rename</ContextMenuItem>
        <ContextMenuSeparator />
        <ContextMenuItem variant="destructive" onClick={onDelete}><Trash2 className="size-3.5 mr-2" />Delete</ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  )
}

function NewCard({ onCreateNote, onUpload, onCreateFolder }: { onCreateNote: () => void; onUpload: () => void; onCreateFolder: () => void }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <div className="group rounded-lg border border-dashed border-border hover:border-foreground/20 cursor-pointer transition-colors flex flex-col overflow-hidden hover:bg-muted/30 h-full">
          <div className="flex items-center justify-center aspect-square">
            <Plus className="size-5 text-muted-foreground/40 group-hover:text-muted-foreground/60 transition-colors" />
          </div>
          <div className="px-2 py-1.5 text-center">
            <span className="text-xs font-medium text-muted-foreground/50">New</span>
          </div>
        </div>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuItem onClick={onCreateNote}><NotepadText className="size-3.5 mr-2" />Note</DropdownMenuItem>
        <DropdownMenuItem onClick={onCreateFolder}><FolderPlus className="size-3.5 mr-2" />Folder</DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={onUpload}><Upload className="size-3.5 mr-2" />Upload Files</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function EmptyState({ isRoot, onUpload, onCreateNote }: { isRoot: boolean; onUpload: () => void; onCreateNote: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 gap-6">
      <div className="text-center">
        <p className="text-sm text-muted-foreground">{isRoot ? 'No files yet' : 'This folder is empty'}</p>
        <p className="text-xs text-muted-foreground/60 mt-1">Upload documents or create notes to get started</p>
      </div>
      <div className="flex gap-3">
        <button onClick={onUpload} className="flex flex-col items-center gap-2 px-6 py-4 rounded-lg border border-dashed border-border hover:border-foreground/20 hover:bg-muted/50 transition-colors cursor-pointer">
          <Upload className="size-5 text-muted-foreground" /><span className="text-xs text-muted-foreground">Upload files</span>
        </button>
        <button onClick={onCreateNote} className="flex flex-col items-center gap-2 px-6 py-4 rounded-lg border border-dashed border-border hover:border-foreground/20 hover:bg-muted/50 transition-colors cursor-pointer">
          <NotepadText className="size-5 text-muted-foreground" /><span className="text-xs text-muted-foreground">New note</span>
        </button>
      </div>
    </div>
  )
}
