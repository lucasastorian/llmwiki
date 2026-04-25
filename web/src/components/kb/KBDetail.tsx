'use client'

import * as React from 'react'
import { useSearchParams, useRouter } from 'next/navigation'
import { Upload as UploadIcon, BookOpen, ArrowUpRight, Loader2 } from 'lucide-react'
import * as tus from 'tus-js-client'
import { useUserStore } from '@/stores'
import { useKBDocuments } from '@/hooks/useKBDocuments'
import { apiFetch } from '@/lib/api'
import { toast } from 'sonner'
import { KBSidenav } from '@/components/kb/KBSidenav'
import { FilesGrid } from '@/components/kb/FilesGrid'
import { SelectionActionBar } from '@/components/kb/SelectionActionBar'
import { WikiContent, extractTocFromMarkdown } from '@/components/wiki/WikiContent'
import type { DocumentListItem, WikiNode, WikiSubsection } from '@/lib/types'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

const wikiPathCache = new Map<string, string>()

function getWikiPathStorageKey(kbId: string): string {
  return `llmwiki:active-wiki-path:${kbId}`
}

function readCachedWikiPath(kbId: string): string | null {
  const cached = wikiPathCache.get(kbId)
  if (cached) return cached
  if (typeof window === 'undefined') return null

  try {
    return window.sessionStorage.getItem(getWikiPathStorageKey(kbId))
  } catch {
    return null
  }
}

function writeCachedWikiPath(kbId: string, path: string | null): void {
  if (path) {
    wikiPathCache.set(kbId, path)
  } else {
    wikiPathCache.delete(kbId)
  }

  if (typeof window === 'undefined') return

  try {
    if (path) {
      window.sessionStorage.setItem(getWikiPathStorageKey(kbId), path)
    } else {
      window.sessionStorage.removeItem(getWikiPathStorageKey(kbId))
    }
  } catch {
    // Ignore storage failures and fall back to in-memory cache only.
  }
}


function buildTreeFromDocs(docs: DocumentListItem[]): WikiNode[] {
  // Sort all docs by sort_order first
  const sorted = [...docs].sort((a, b) => (a.sort_order ?? 999) - (b.sort_order ?? 999))

  // Separate top-level pages (/wiki/X.md) and child pages (/wiki/folder/X.md)
  const topLevel: Array<{ title: string; path: string; slug: string }> = []
  const childPages = new Map<string, Array<{ title: string; path: string }>>()

  for (const doc of sorted) {
    const relative = (doc.path + doc.filename).replace(/^\/wiki\/?/, '')
    const parts = relative.split('/')
    const title =
      doc.title ||
      parts[parts.length - 1].replace(/\.(md|txt|json)$/, '').replace(/[-_]/g, ' ')

    if (parts.length === 1) {
      // Top-level: overview.md → slug "overview", path "overview.md"
      const slug = parts[0].replace(/\.(md|txt|json)$/, '')
      topLevel.push({ title, path: relative, slug })
    } else {
      // Child: overview/investment-philosophy.md → folder "overview"
      const folder = parts[0]
      if (!childPages.has(folder)) childPages.set(folder, [])
      childPages.get(folder)!.push({ title, path: relative })
    }
  }

  // Build tree: parent pages with matching child folders become expandable
  const tree: WikiNode[] = []
  const usedFolders = new Set<string>()

  for (const parent of topLevel) {
    const children = childPages.get(parent.slug)
    if (children && children.length > 0) {
      usedFolders.add(parent.slug)
      tree.push({
        title: parent.title,
        path: parent.path,
        children: children.map((c) => ({ title: c.title, path: c.path })),
      })
    } else {
      tree.push({ title: parent.title, path: parent.path })
    }
  }

  // Orphan folders without a parent page
  for (const [folder, children] of childPages) {
    if (usedFolders.has(folder)) continue
    const folderTitle = folder.replace(/[-_]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
    tree.push({ title: folderTitle, children: children.map((c) => ({ title: c.title, path: c.path })) })
  }

  // Sort: Overview first, Log last, everything else alphabetical
  const slug = (n: WikiNode) => n.path?.replace(/\.(md|txt|json)$/, '').split('/')[0] ?? ''
  tree.sort((a, b) => {
    const sa = slug(a), sb = slug(b)
    if (sa === 'overview') return -1
    if (sb === 'overview') return 1
    if (sa === 'log') return 1
    if (sb === 'log') return -1
    return a.title.localeCompare(b.title)
  })

  return tree
}

function findFirstPath(nodes: WikiNode[]): string | null {
  for (const node of nodes) {
    if (node.path) return node.path
    if (node.children) {
      const found = findFirstPath(node.children)
      if (found) return found
    }
  }
  return null
}

type Props = {
  kbId: string
  kbSlug?: string
  kbName: string
}

export function KBDetail({ kbId, kbName }: Props) {
  const router = useRouter()
  const searchParams = useSearchParams()
  const token = useUserStore((s) => s.accessToken)
  const userId = useUserStore((s) => s.user?.id)
  const { documents, setDocuments, loading } = useKBDocuments(kbId)

  // Split documents into wiki and sources
  const wikiDocs = React.useMemo(
    () => documents.filter((d) => (d.path === '/wiki/' || d.path.startsWith('/wiki/')) && !d.archived && d.file_type === 'md'),
    [documents],
  )
  const sourceDocs = React.useMemo(
    () => documents.filter((d) => !d.path.startsWith('/wiki/') && !d.archived),
    [documents],
  )

  // Wiki state
  const indexDoc = wikiDocs.find((d) => d.filename === 'index.json' && d.path === '/wiki/')
  const SCAFFOLD_FILES = new Set(['index.json', 'overview.md', 'log.md'])
  const hasNavigableWiki = React.useMemo(
    () => wikiDocs.some((d) => d.path === '/wiki/' ? !SCAFFOLD_FILES.has(d.filename) : true),
    [wikiDocs],
  )
  const [wikiTree, setWikiTree] = React.useState<WikiNode[]>([])
  const [wikiActivePath, setWikiActivePath] = React.useState<string | null>(null)
  const [pageContent, setPageContent] = React.useState('')
  const [pageTitle, setPageTitle] = React.useState('')
  const [pageLoading, setPageLoading] = React.useState(false)
  const [pageLoadedPath, setPageLoadedPath] = React.useState<string | null>(null)
  const [indexLoaded, setIndexLoaded] = React.useState(false)
  const [selectionHydrated, setSelectionHydrated] = React.useState(false)

  // Files grid view state
  const [filesViewActive, setFilesViewActive] = React.useState(false)
  const [filesInitialDocId, setFilesInitialDocId] = React.useState<string | null>(null)
  const [filesInitialPage, setFilesInitialPage] = React.useState<number | undefined>()

  const docParam = searchParams.get('doc')
  const pageParam = searchParams.get('page')

  // Token helper (used by multiple handlers below)
  const getToken = () => {
    const t = useUserStore.getState().accessToken
    if (!t) { toast.error('Not authenticated'); return null }
    return t
  }

  // Multi-selection state
  const [selectedIds, setSelectedIds] = React.useState<Set<string>>(new Set())
  const lastSelectedIdRef = React.useRef<string | null>(null)

  // Flat ordered list of source doc IDs for shift-select range
  const sourceDocIds = React.useMemo(() => sourceDocs.map((d) => d.id), [sourceDocs])

  const handleSelect = React.useCallback((docId: string, e: React.MouseEvent) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)

      if (e.shiftKey && lastSelectedIdRef.current) {
        // Range select
        const lastIdx = sourceDocIds.indexOf(lastSelectedIdRef.current)
        const currIdx = sourceDocIds.indexOf(docId)
        if (lastIdx !== -1 && currIdx !== -1) {
          const [start, end] = lastIdx < currIdx ? [lastIdx, currIdx] : [currIdx, lastIdx]
          for (let i = start; i <= end; i++) {
            next.add(sourceDocIds[i])
          }
        } else {
          next.add(docId)
        }
      } else if (e.metaKey || e.ctrlKey) {
        // Toggle single
        if (next.has(docId)) {
          next.delete(docId)
        } else {
          next.add(docId)
        }
      } else {
        // Plain click — select only this one
        next.clear()
        next.add(docId)
      }

      lastSelectedIdRef.current = docId
      return next
    })
  }, [sourceDocIds])

  const clearSelection = React.useCallback(() => {
    setSelectedIds(new Set())
    lastSelectedIdRef.current = null
  }, [])

  // ESC clears selection
  React.useEffect(() => {
    if (selectedIds.size === 0) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') clearSelection()
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [selectedIds.size, clearSelection])

  const handleDeleteSelected = async () => {
    const t = getToken()
    if (!t) return
    const ids = Array.from(selectedIds)
    const count = ids.length
    if (!window.confirm(`Delete ${count} selected document${count > 1 ? 's' : ''}?`)) return

    const results = await Promise.allSettled(
      ids.map((id) => apiFetch(`/v1/documents/${id}`, t, { method: 'DELETE' }))
    )

    const succeeded = ids.filter((_, i) => results[i].status === 'fulfilled')
    const failed = ids.filter((_, i) => results[i].status === 'rejected')

    if (succeeded.length > 0) {
      setDocuments((prev) => prev.filter((d) => !succeeded.includes(d.id)))
    }
    if (failed.length > 0) {
      toast.error(`Failed to delete ${failed.length} document${failed.length > 1 ? 's' : ''}`)
    }
    clearSelection()
  }

  // Restore from URL on initial load
  const hasSelectionParam = !!docParam || !!pageParam
  const [urlRestored, setUrlRestored] = React.useState(!hasSelectionParam)
  React.useEffect(() => {
    if (urlRestored || loading) return

    if (docParam) {
      if (!documents.length) return
      const num = parseInt(docParam, 10)
      const doc = documents.find((d) => d.document_number === num)
      setFilesViewActive(true)
      setFilesInitialDocId(doc?.id ?? null)
      setWikiActivePath(null)
      setUrlRestored(true)
      return
    }

    if (pageParam) {
      setFilesViewActive(false)
      setWikiActivePath(pageParam.replace(/^\/wiki\/?/, ''))
      setUrlRestored(true)
      return
    }

    if (!documents.length) return
    setUrlRestored(true)
  }, [docParam, pageParam, loading, documents, urlRestored])

  // Sync selection to URL
  const updateUrl = React.useCallback((selection: { docNumber?: number | null; pagePath?: string | null }) => {
    const { docNumber = null, pagePath = null } = selection
    const url = new URL(window.location.href)
    if (docNumber) {
      url.searchParams.set('doc', String(docNumber))
    } else {
      url.searchParams.delete('doc')
    }
    if (pagePath) {
      url.searchParams.set('page', pagePath)
    } else {
      url.searchParams.delete('page')
    }
    router.replace(url.pathname + url.search, { scroll: false })
  }, [router])

  const handleWikiSelect = React.useCallback((path: string) => {
    setWikiActivePath(path)

    setFilesViewActive(false)
    updateUrl({ pagePath: path })
  }, [updateUrl])

  const handleFilesToggle = React.useCallback(() => {
    setFilesViewActive((prev) => {
      if (!prev) {
        // Entering files view — clear deep-link state but preserve wiki path
        setFilesInitialDocId(null)
        setFilesInitialPage(undefined)
      }
      return !prev
    })
  }, [])

  const handleOpenSourceDoc = React.useCallback((docId: string) => {
    setFilesViewActive(true)
    setFilesInitialDocId(docId)
    setFilesInitialPage(undefined)
  }, [])

  const handleCitationSourceClick = React.useCallback((filename: string, page?: number) => {
    const lower = filename.toLowerCase()
    const match = sourceDocs.find((d) => {
      const fn = d.filename.toLowerCase()
      const title = (d.title || '').toLowerCase()
      return fn === lower || title === lower || fn === lower + '.md' || fn.replace(/\.md$/, '') === lower
    })
    setFilesViewActive(true)
    setFilesInitialDocId(match?.id ?? null)
    setFilesInitialPage(page)
  }, [sourceDocs])

  // Restore the last-opened wiki page after a hard reload.
  React.useEffect(() => {
    if (!docParam && !pageParam) {
      const cachedPath = readCachedWikiPath(kbId)
      if (cachedPath) setWikiActivePath((prev) => prev ?? cachedPath)
    }
    setSelectionHydrated(true)
  }, [kbId, docParam, pageParam])

  // Cache active path
  React.useEffect(() => {
    if (!selectionHydrated) return
    writeCachedWikiPath(kbId, wikiActivePath)
  }, [kbId, wikiActivePath, selectionHydrated])

  // Build wiki tree
  React.useEffect(() => {
    let cancelled = false
    setIndexLoaded(false)

    if (indexDoc && token) {
      apiFetch<{ content: string }>(`/v1/documents/${indexDoc.id}/content`, token)
        .then((res) => {
          if (cancelled) return
          try {
            const parsed = JSON.parse(res.content)
            setWikiTree(parsed.tree || [])
          } catch {
            setWikiTree(buildTreeFromDocs(wikiDocs.filter((d) => d.id !== indexDoc.id)))
          }
          setIndexLoaded(true)
        })
        .catch(() => {
          if (cancelled) return
          setWikiTree(buildTreeFromDocs(wikiDocs.filter((d) => d.id !== indexDoc.id)))
          setIndexLoaded(true)
        })
    } else {
      setWikiTree(buildTreeFromDocs(wikiDocs))
      setIndexLoaded(true)
    }

    return () => { cancelled = true }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [indexDoc?.id, token, wikiDocs.length, wikiDocs.map((d) => d.id).join()])

  // Auto-select first wiki page
  React.useEffect(() => {
    if (indexLoaded && urlRestored && !filesViewActive && !wikiActivePath && wikiTree.length) {
      const first = findFirstPath(wikiTree)
      if (first) {
        setWikiActivePath(first)
        updateUrl({ pagePath: first })
      }
    }
  }, [indexLoaded, wikiTree, wikiActivePath, filesViewActive, urlRestored, updateUrl])

  // Track the active wiki doc's version to avoid re-fetching on unrelated updates
  const activeWikiDoc = React.useMemo(() => {
    if (!wikiActivePath) return null
    return wikiDocs.find((d) => {
      const relative = (d.path + d.filename).replace(/^\/wiki\/?/, '')
      return relative === wikiActivePath
    }) ?? null
  }, [wikiActivePath, wikiDocs])

  const activeWikiVersion = activeWikiDoc?.version ?? -1
  const activeWikiDocId = activeWikiDoc?.id ?? null

  // Fetch wiki page content — only when path changes or version bumps
  React.useEffect(() => {
    if (!wikiActivePath || !token) {
      setPageLoadedPath(null)
      return
    }

    if (!activeWikiDoc) {
      setPageContent(`Page not found: ${wikiActivePath}`)
      setPageTitle('')
      setPageLoadedPath(wikiActivePath)
      return
    }

    setPageTitle(activeWikiDoc.title || activeWikiDoc.filename.replace(/\.(md|txt)$/, ''))

    // Skip loading state on version bumps (live updates from MCP) to avoid flash
    const isLiveUpdate = pageLoadedPath === wikiActivePath
    if (!isLiveUpdate) {
      setPageLoading(true)
      setPageLoadedPath(null)
    }

    apiFetch<{ content: string }>(`/v1/documents/${activeWikiDoc.id}/content`, token)
      .then((res) => setPageContent(res.content || ''))
      .catch(() => setPageContent('Failed to load page content.'))
      .finally(() => {
        setPageLoading(false)
        setPageLoadedPath(wikiActivePath)
      })
  }, [wikiActivePath, token, activeWikiDocId, activeWikiVersion])

  const wikiPathSet = React.useMemo(() => {
    const set = new Set<string>()
    for (const d of wikiDocs) {
      const relative = (d.path + d.filename).replace(/^\/wiki\/?/, '')
      set.add(relative)
    }
    return set
  }, [wikiDocs])

  const handleWikiNavigate = React.useCallback(
    (path: string) => {
      let nextPath = path
  
      if (path.startsWith('/wiki/')) {
        nextPath = path.replace(/^\/wiki\/?/, '')
      } else if (path.startsWith('/')) {
        nextPath = path.slice(1)
      } else if (wikiPathSet.has(path)) {
        // Path directly matches an existing wiki doc — use as-is
        nextPath = path
      } else if (wikiActivePath) {
        // Resolve relative to current page's directory
        const dir = wikiActivePath.includes('/')
          ? wikiActivePath.substring(0, wikiActivePath.lastIndexOf('/'))
          : ''
        let resolved = path.startsWith('./')
          ? (dir ? dir + '/' : '') + path.slice(2)
          : (dir ? dir + '/' : '') + path

        while (resolved.includes('../')) {
          resolved = resolved.replace(/[^/]*\/\.\.\//, '')
        }
        nextPath = resolved
      }
      setWikiActivePath(nextPath)
      updateUrl({ pagePath: nextPath })
    },
    [wikiActivePath, wikiPathSet, updateUrl],
  )

  // Document actions
  const handleCreateNote = async (targetPath: string = '/') => {
    const t = getToken()
    if (!t || !userId) return
    try {
      const data = await apiFetch<DocumentListItem>(`/v1/knowledge-bases/${kbId}/documents/note`, t, {
        method: 'POST',
        body: JSON.stringify({ filename: 'Untitled.md', path: targetPath }),
      })
      setDocuments((prev) => [data, ...prev])
      if (!filesViewActive) {
        setFilesViewActive(true)
        setWikiActivePath(null)
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to create note')
    }
  }

  const handleCreateFolder = (folderName: string, parentPath: string = '/') => {
    const t = getToken()
    if (!t || !userId) return
    const path = parentPath.replace(/\/$/, '') + '/' + folderName + '/'
    apiFetch<DocumentListItem>(`/v1/knowledge-bases/${kbId}/documents/note`, t, {
      method: 'POST',
      body: JSON.stringify({ filename: 'Untitled.md', path }),
    })
      .then((data) => {
        setDocuments((prev) => [data, ...prev])
        if (!filesViewActive) {
          setFilesViewActive(true)
          setWikiActivePath(null)
        }
      })
      .catch((err: Error) => toast.error(err.message || 'Failed to create folder'))
  }

  const handleMoveDocument = async (docId: string, targetPath: string) => {
    const t = getToken()
    if (!t) return
    try {
      await apiFetch(`/v1/documents/${docId}`, t, {
        method: 'PATCH',
        body: JSON.stringify({ path: targetPath }),
      })
      setDocuments((prev) => prev.map((d) => d.id === docId ? { ...d, path: targetPath } : d))
    } catch {
      toast.error('Failed to move document')
    }
  }

  const handleDeleteDocument = async (docId: string) => {
    const t = getToken()
    if (!t) return
    try {
      await apiFetch(`/v1/documents/${docId}`, t, { method: 'DELETE' })
      setDocuments((prev) => prev.filter((d) => d.id !== docId))
    } catch {
      toast.error('Failed to delete document')
    }
  }

  const handleRenameDocument = async (docId: string, newTitle: string) => {
    const t = getToken()
    if (!t) return
    try {
      await apiFetch(`/v1/documents/${docId}`, t, {
        method: 'PATCH',
        body: JSON.stringify({ title: newTitle }),
      })
      setDocuments((prev) => prev.map((d) => d.id === docId ? { ...d, title: newTitle } : d))
    } catch {
      toast.error('Failed to rename document')
    }
  }

  const uploadPathRef = React.useRef('/')
  const handleUploadClick = (targetPath: string = '/') => {
    uploadPathRef.current = targetPath
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.md,.txt,.pdf,.pptx,.ppt,.docx,.doc,.png,.jpg,.jpeg,.webp,.gif,.svg,.xlsx,.xls,.csv,.html,.htm'
    input.multiple = true
    input.onchange = () => {
      if (input.files) uploadFiles(Array.from(input.files), uploadPathRef.current)
    }
    input.click()
  }

  const tusUploadFile = React.useCallback((file: File): Promise<void> => {
    const t = getToken()
    if (!t) return Promise.reject(new Error('Not authenticated'))

    return new Promise((resolve, reject) => {
      const upload = new tus.Upload(file, {
        endpoint: `${API_URL}/v1/uploads`,
        retryDelays: [0, 1000, 3000, 5000],
        metadata: {
          filename: file.name,
          knowledge_base_id: kbId,
        },
        headers: { Authorization: `Bearer ${t}` },
        onError: (error) => {
          toast.error(`Upload failed: ${file.name}`)
          reject(error)
        },
        onSuccess: () => {
          toast.success(`${file.name} uploaded, processing...`)
          resolve()
        },
      })
      upload.start()
    })
  }, [kbId])

  const uploadFiles = React.useCallback((files: File[], targetPath: string = '/') => {
    const t = getToken()
    if (!t || !userId) return

    const uploads = files.map(async (file) => {
      const ext = file.name.split('.').pop()?.toLowerCase()
      if (ext === 'md' || ext === 'txt') {
        const content = await file.text()
        const title = file.name.replace(/\.(md|txt)$/i, '')
        try {
          const data = await apiFetch<DocumentListItem>(`/v1/knowledge-bases/${kbId}/documents/note`, t, {
            method: 'POST',
            body: JSON.stringify({ filename: file.name, title, content, path: targetPath }),
          })
          setDocuments((prev) => [data, ...prev])
        } catch {
          toast.error(`Failed to import ${file.name}`)
        }
      } else {
        const supportedTypes = new Set(['pdf', 'pptx', 'ppt', 'docx', 'doc', 'png', 'jpg', 'jpeg', 'webp', 'gif', 'xlsx', 'xls', 'csv', 'html', 'htm'])
        if (ext && supportedTypes.has(ext)) {
          if (process.env.NEXT_PUBLIC_MODE === 'local') {
            // Local mode: simple multipart upload
            const formData = new FormData()
            formData.append('file', file)
            formData.append('path', targetPath)
            try {
              const res = await fetch(`${API_URL}/v1/upload`, {
                method: 'POST',
                body: formData,
              })
              if (!res.ok) throw new Error(`Upload failed: ${res.status}`)
              const data = await res.json()
              setDocuments((prev) => [data, ...prev])
              toast.success(`${file.name} uploaded`)
            } catch {
              toast.error(`Upload failed: ${file.name}`)
            }
          } else {
            await tusUploadFile(file)
          }
        } else {
          toast.info(`${ext} files not yet supported`)
        }
      }
    })

    Promise.all(uploads).then(() => {
      const textFiles = files.filter((f) => /\.(md|txt)$/i.test(f.name))
      if (textFiles.length > 0) toast.success(`Imported ${textFiles.length} file${textFiles.length > 1 ? 's' : ''}`)
    })
  }, [kbId, userId, tusUploadFile])

  // Extract H2 subsections from wiki page content for the sidenav
  const wikiActiveSubsections: WikiSubsection[] = React.useMemo(() => {
    if (!pageContent || !wikiActivePath) return []
    const toc = extractTocFromMarkdown(pageContent)
    return toc
      .filter((item) => item.level === 2)
      .map((item) => ({ id: item.id, title: item.text }))
  }, [pageContent, wikiActivePath])

  const handleSubsectionClick = React.useCallback((id: string) => {
    const el = document.getElementById(id)
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [])

  // File drag-and-drop
  const [fileDragOver, setFileDragOver] = React.useState(false)
  const dragCounterRef = React.useRef(0)

  const handleFileDragEnter = (e: React.DragEvent) => {
    if (e.dataTransfer.types.includes('application/x-llmwiki-item')) return
    e.preventDefault()
    dragCounterRef.current++
    if (dragCounterRef.current === 1) setFileDragOver(true)
  }
  const handleFileDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    dragCounterRef.current--
    if (dragCounterRef.current === 0) setFileDragOver(false)
  }
  const handleFileDragOver = (e: React.DragEvent) => {
    if (e.dataTransfer.types.includes('application/x-llmwiki-item')) return
    e.preventDefault()
    e.dataTransfer.dropEffect = 'copy'
  }
  const handleFileDrop = (e: React.DragEvent) => {
    if (e.dataTransfer.types.includes('application/x-llmwiki-item')) return
    e.preventDefault()
    dragCounterRef.current = 0
    setFileDragOver(false)
    const files = Array.from(e.dataTransfer.files)
    if (files.length > 0) uploadFiles(files)
  }

  const showMainLoading =
    loading ||
    !selectionHydrated ||
    !urlRestored ||
    (!filesViewActive && hasNavigableWiki && !wikiActivePath) ||
    (!filesViewActive && !!wikiActivePath && pageLoadedPath !== wikiActivePath)

  return (
    <div
      className="flex flex-col h-full relative"
      onDragEnter={handleFileDragEnter}
      onDragLeave={handleFileDragLeave}
      onDragOver={handleFileDragOver}
      onDrop={handleFileDrop}
    >
      {fileDragOver && (
        <div className="absolute inset-0 z-50 bg-background/80 backdrop-blur-sm flex items-center justify-center pointer-events-none">
          <div className="flex flex-col items-center gap-3 border-2 border-dashed border-primary rounded-xl px-12 py-10">
            <UploadIcon className="size-8 text-primary" />
            <p className="text-sm font-medium text-primary">Drop files to upload</p>
            <p className="text-xs text-muted-foreground">PDF, Word, PowerPoint, images, and more</p>
          </div>
        </div>
      )}

      <div className="flex-1 overflow-hidden flex">
        <div className="w-64 shrink-0">
          <KBSidenav
            kbId={kbId}
            kbName={kbName}
            wikiTree={wikiTree}
            wikiActivePath={filesViewActive ? null : wikiActivePath}
            onWikiNavigate={handleWikiSelect}
            wikiActiveSubsections={wikiActiveSubsections}
            onWikiSubsectionClick={handleSubsectionClick}
            sourceDocs={sourceDocs}
            hasWiki={hasNavigableWiki}
            loading={loading}
            onUpload={() => handleUploadClick()}
            filesViewActive={filesViewActive}
            onFilesToggle={handleFilesToggle}
            onOpenSourceDoc={handleOpenSourceDoc}
          />
        </div>
        <div className="flex-1 min-w-0">
          {showMainLoading ? (
            <div className="flex items-center justify-center h-full">
              <Loader2 className="size-5 animate-spin text-muted-foreground" />
            </div>
          ) : filesViewActive ? (
            <FilesGrid
              key={filesInitialDocId ?? 'browse'}
              documents={documents}
              onDeleteDocument={handleDeleteDocument}
              onRenameDocument={handleRenameDocument}
              onUpload={handleUploadClick}
              onCreateNote={handleCreateNote}
              onCreateFolder={handleCreateFolder}
              initialDocId={filesInitialDocId}
              initialPage={filesInitialPage}
            />
          ) : pageLoading ? (
            <div className="flex items-center justify-center h-full">
              <Loader2 className="size-5 animate-spin text-muted-foreground" />
            </div>
          ) : hasNavigableWiki && wikiActivePath ? (
            <WikiContent
              content={pageContent}
              title={pageTitle}
              onNavigate={handleWikiNavigate}
              onSourceClick={handleCitationSourceClick}
              documents={documents}
            />
          ) : (
            <div className="flex flex-col items-center justify-center h-full gap-4 px-6">
              <BookOpen className="size-10 text-muted-foreground/20" />
              <div className="text-center max-w-sm">
                <h3 className="text-base font-medium mb-1.5">No wiki yet</h3>
                <p className="text-sm text-muted-foreground leading-relaxed">
                  Add some sources, then ask Claude to compile a wiki from them.
                </p>
              </div>
              <div className="flex items-center gap-3 mt-2">
                <button
                  onClick={() => handleUploadClick()}
                  className="inline-flex items-center gap-2 rounded-full bg-foreground text-background px-5 py-2 text-sm font-medium hover:opacity-90 transition-opacity cursor-pointer"
                >
                  <UploadIcon className="size-3.5 opacity-60" />
                  Upload Sources
                </button>
                <a
                  href="https://claude.ai"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 rounded-full border border-border px-5 py-2 text-sm font-medium hover:bg-accent transition-colors"
                >
                  Open Claude
                  <ArrowUpRight className="size-3.5 opacity-60" />
                </a>
              </div>
            </div>
          )}
        </div>
      </div>

      <SelectionActionBar
        count={selectedIds.size}
        onDelete={handleDeleteSelected}
        onClear={clearSelection}
      />
    </div>
  )
}


