'use client'

import * as React from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { ArrowUpRight, BookOpen, Loader2, Upload as UploadIcon } from 'lucide-react'
import { KBSidenav } from '@/components/kb/KBSidenav'
import { WikiContent } from '@/components/wiki/WikiContent'
import { useKBDocuments } from '@/hooks/useKBDocuments'
import { apiFetch } from '@/lib/api'
import { useUserStore } from '@/stores'
import type { DocumentListItem, WikiNode } from '@/lib/types'
import {
  enrichTreeWithProgress, findCurrentLesson, flattenLessons, lessonStatus,
} from '@/lib/wikiTree'
import { useCourseProgress } from '@/hooks/useCourseProgress'

function buildTreeFromDocs(docs: DocumentListItem[]): WikiNode[] {
  const sorted = [...docs].sort((a, b) => (a.sort_order ?? 999) - (b.sort_order ?? 999))
  const topLevel: Array<{ title: string; path: string; slug: string; docNumber: number | null }> = []
  const childPages = new Map<string, Array<{ title: string; path: string; docNumber: number | null }>>()

  for (const doc of sorted) {
    const relative = (doc.path + doc.filename).replace(/^\/wiki\/?/, '')
    const parts = relative.split('/')
    const title =
      doc.title ||
      parts[parts.length - 1].replace(/\.(md|txt|json)$/, '').replace(/[-_]/g, ' ')

    if (parts.length === 1) {
      const slug = parts[0].replace(/\.(md|txt|json)$/, '')
      topLevel.push({ title, path: relative, slug, docNumber: doc.document_number })
    } else {
      const folder = parts[0]
      if (!childPages.has(folder)) childPages.set(folder, [])
      childPages.get(folder)!.push({ title, path: relative, docNumber: doc.document_number })
    }
  }

  const tree: WikiNode[] = []
  const usedFolders = new Set<string>()

  for (const parent of topLevel) {
    const children = childPages.get(parent.slug)
    if (children && children.length > 0) {
      usedFolders.add(parent.slug)
      tree.push({
        title: parent.title,
        path: parent.path,
        docNumber: parent.docNumber,
        children: children.map((c) => ({ title: c.title, path: c.path, docNumber: c.docNumber })),
      })
    } else {
      tree.push({ title: parent.title, path: parent.path, docNumber: parent.docNumber })
    }
  }

  for (const [folder, children] of childPages) {
    if (usedFolders.has(folder)) continue
    const folderTitle = folder.replace(/[-_]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
    tree.push({
      title: folderTitle,
      children: children.map((c) => ({ title: c.title, path: c.path, docNumber: c.docNumber })),
    })
  }

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

function enrichTreeWithDocNumbers(tree: WikiNode[], docs: DocumentListItem[]): WikiNode[] {
  const pathToDocNumber = new Map<string, number | null>()
  for (const doc of docs) {
    const relative = (doc.path + doc.filename).replace(/^\/wiki\/?/, '')
    pathToDocNumber.set(relative, doc.document_number)
  }
  function enrich(nodes: WikiNode[]): WikiNode[] {
    return nodes.map((node) => ({
      ...node,
      docNumber: node.path ? (pathToDocNumber.get(node.path) ?? null) : null,
      children: node.children ? enrich(node.children) : undefined,
    }))
  }
  return enrich(tree)
}

function findFirstPath(nodes: WikiNode[]): { path: string; docNumber: number | null } | null {
  for (const node of nodes) {
    if (node.path) return { path: node.path, docNumber: node.docNumber ?? null }
    if (node.children) {
      const found = findFirstPath(node.children)
      if (found) return found
    }
  }
  return null
}

export function WikiOnlyDetail({
  kbId,
  kbSlug,
  kbName,
  kbKind = 'wiki',
}: {
  kbId: string
  kbSlug: string
  kbName: string
  kbKind?: 'wiki' | 'course'
}) {
  const router = useRouter()
  const searchParams = useSearchParams()
  const token = useUserStore((s) => s.accessToken)
  const { documents, setDocuments, loading } = useKBDocuments(kbId)
  const courseMode = kbKind === 'course'
  const { markComplete } = useCourseProgress(setDocuments)

  const updateParam = React.useCallback((key: string, value: string | null) => {
    const url = new URL(window.location.href)
    if (value != null) url.searchParams.set(key, value)
    else url.searchParams.delete(key)
    window.history.replaceState(window.history.state, '', url.pathname + url.search)
  }, [])

  const wikiDocs = React.useMemo(
    () => documents.filter((d) => (d.path === '/wiki/' || d.path.startsWith('/wiki/')) && !d.archived && d.file_type === 'md'),
    [documents],
  )
  const sourceDocs = React.useMemo(
    () => documents.filter((d) => !d.path.startsWith('/wiki/') && !d.archived),
    [documents],
  )

  const pParam = searchParams.get('p')
  const urlWikiDocNumber = pParam ? parseInt(pParam, 10) : null
  const [wikiActivePath, setWikiActivePath] = React.useState<string | null>(null)
  const lastWikiDocNumberRef = React.useRef<number | null>(urlWikiDocNumber)
  const handledUrlDocNumberRef = React.useRef<number | null>(null)

  // Applies ?p= to the active path exactly once per URL value (deep links, back/forward).
  // `documents` churns constantly (WS/poll, optimistic course-progress writes) — re-running
  // on churn would re-assert a stale URL and snap in-app navigation back.
  React.useEffect(() => {
    if (urlWikiDocNumber == null || !documents.length) return
    if (urlWikiDocNumber === handledUrlDocNumberRef.current) return
    const doc = documents.find((d) => d.document_number === urlWikiDocNumber)
    if (!doc) return
    handledUrlDocNumberRef.current = urlWikiDocNumber
    setWikiActivePath((doc.path + doc.filename).replace(/^\/wiki\/?/, ''))
    lastWikiDocNumberRef.current = urlWikiDocNumber
  }, [urlWikiDocNumber, documents])

  const indexDoc = wikiDocs.find((d) => d.filename === 'index.json' && d.path === '/wiki/')
  const scaffoldFiles = React.useMemo(() => new Set(['index.json', 'overview.md', 'log.md']), [])
  const hasNavigableWiki = React.useMemo(
    () => wikiDocs.some((d) => d.path === '/wiki/' ? !scaffoldFiles.has(d.filename) : true),
    [wikiDocs, scaffoldFiles],
  )
  const [wikiTree, setWikiTree] = React.useState<WikiNode[]>([])
  const [indexLoaded, setIndexLoaded] = React.useState(false)
  const wikiDocIds = React.useMemo(() => wikiDocs.map((d) => d.id).join(), [wikiDocs])

  React.useEffect(() => {
    let cancelled = false
    setIndexLoaded(false)
    if (indexDoc && token) {
      apiFetch<{ content: string }>(`/v1/documents/${indexDoc.id}/content`, token)
        .then((res) => {
          if (cancelled) return
          try {
            const parsed = JSON.parse(res.content)
            setWikiTree(enrichTreeWithDocNumbers(parsed.tree || [], wikiDocs))
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
  }, [indexDoc?.id, token, wikiDocIds, wikiDocs])

  React.useEffect(() => {
    if (indexLoaded && !wikiActivePath && urlWikiDocNumber == null && wikiTree.length && !loading) {
      const first = findFirstPath(wikiTree)
      if (first) {
        setWikiActivePath(first.path)
        lastWikiDocNumberRef.current = first.docNumber
        if (first.docNumber != null) updateParam('p', String(first.docNumber))
      }
    }
  }, [indexLoaded, wikiTree, wikiActivePath, urlWikiDocNumber, loading, updateParam])

  const [pageContent, setPageContent] = React.useState('')
  const [pageTitle, setPageTitle] = React.useState('')
  const [pageLoading, setPageLoading] = React.useState(false)
  const [pageLoadedPath, setPageLoadedPath] = React.useState<string | null>(null)

  const activeWikiDoc = React.useMemo(() => {
    if (!wikiActivePath) return null
    return wikiDocs.find((d) => (d.path + d.filename).replace(/^\/wiki\/?/, '') === wikiActivePath) ?? null
  }, [wikiActivePath, wikiDocs])

  const activeWikiVersion = activeWikiDoc?.version ?? -1
  const activeWikiDocId = activeWikiDoc?.id ?? null

  // ─── Course progress (derived from the lessons' metadata.course.status) ─────
  const displayTree = React.useMemo(
    () => (courseMode ? enrichTreeWithProgress(wikiTree, wikiDocs) : wikiTree),
    [courseMode, wikiTree, wikiDocs],
  )
  const lessons = React.useMemo(() => (courseMode ? flattenLessons(displayTree) : []), [courseMode, displayTree])
  const completedCount = React.useMemo(() => lessons.filter((l) => l.status === 'complete').length, [lessons])
  const currentLessonPath = React.useMemo(
    () => (courseMode ? findCurrentLesson(displayTree)?.path ?? null : null),
    [courseMode, displayTree],
  )
  const overviewLesson = React.useMemo(() => {
    if (!courseMode) return null
    const doc = wikiDocs.find((d) => (d.path + d.filename).replace(/^\/wiki\/?/, '') === 'overview.md')
    return doc ? { title: doc.title || 'Overview', path: 'overview.md' } : null
  }, [courseMode, wikiDocs])

  const activeLessonIdx = React.useMemo(
    () => (courseMode && wikiActivePath ? lessons.findIndex((l) => l.path === wikiActivePath) : -1),
    [courseMode, wikiActivePath, lessons],
  )

  const courseView: 'overview' | 'lesson' | null = React.useMemo(() => {
    if (!courseMode) return null
    if (wikiActivePath === 'overview.md') return 'overview'
    return activeLessonIdx >= 0 ? 'lesson' : null
  }, [courseMode, wikiActivePath, activeLessonIdx])

  const prevLesson = React.useMemo(() => {
    if (activeLessonIdx < 0) return null
    if (activeLessonIdx > 0) {
      const l = lessons[activeLessonIdx - 1]
      return l.path ? { title: l.title, path: l.path } : null
    }
    return overviewLesson
  }, [activeLessonIdx, lessons, overviewLesson])

  // The forward control: the next lesson, or "Finish" on the last lesson (returns to the hub).
  const forward = React.useMemo(() => {
    if (activeLessonIdx < 0) return null
    const next = lessons[activeLessonIdx + 1]
    return { label: next?.title ?? 'Finish', path: next?.path ?? 'overview.md' }
  }, [activeLessonIdx, lessons])

  const resumeLesson = React.useMemo(() => {
    if (!courseMode) return null
    const target = findCurrentLesson(displayTree) ?? lessons[0] ?? null
    return target?.path ? { title: target.title, path: target.path } : null
  }, [courseMode, displayTree, lessons])

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
    const isLiveUpdate = pageLoadedPath === wikiActivePath
    if (!isLiveUpdate) {
      setPageLoading(true)
      setPageLoadedPath(null)
    }
    const controller = new AbortController()
    apiFetch<{ content: string }>(`/v1/documents/${activeWikiDoc.id}/content`, token, { signal: controller.signal })
      .then((res) => {
        if (!controller.signal.aborted) setPageContent(res.content || '')
      })
      .catch(() => {
        if (!controller.signal.aborted) setPageContent('Failed to load page content.')
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setPageLoading(false)
          setPageLoadedPath(wikiActivePath)
        }
      })
    return () => controller.abort()
  }, [wikiActivePath, token, activeWikiDocId, activeWikiVersion])

  const handleWikiSelect = React.useCallback((path: string, docNumber?: number | null) => {
    setWikiActivePath(path)
    const num = docNumber ?? wikiDocs.find((d) => (d.path + d.filename).replace(/^\/wiki\/?/, '') === path)?.document_number ?? null
    lastWikiDocNumberRef.current = num
    if (num != null) {
      // Our own URL write — mark handled so the sync effect never re-applies it.
      handledUrlDocNumberRef.current = num
      updateParam('p', String(num))
    }
  }, [updateParam, wikiDocs])

  // Advancing completes the lesson being read (locks are a progression cue, not
  // enforcement — a deep-linked read still counts) and moves to the next.
  const handleForward = React.useCallback(() => {
    if (!forward) return
    if (activeWikiDoc && lessonStatus(activeWikiDoc) !== 'complete') {
      markComplete(activeWikiDoc.id)
    }
    handleWikiSelect(forward.path)
  }, [forward, activeWikiDoc, markComplete, handleWikiSelect])

  const wikiPathSet = React.useMemo(() => {
    const set = new Set<string>()
    for (const d of wikiDocs) {
      set.add((d.path + d.filename).replace(/^\/wiki\/?/, ''))
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
      } else if (!wikiPathSet.has(path) && wikiActivePath) {
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
      handleWikiSelect(nextPath)
    },
    [handleWikiSelect, wikiActivePath, wikiPathSet],
  )

  const openSourceDoc = React.useCallback((doc: DocumentListItem) => {
    const search = doc.document_number != null ? `?doc=${doc.document_number}` : ''
    router.push(`/wikis/${kbSlug}/files${search}`)
  }, [kbSlug, router])

  const handleCitationSourceClick = React.useCallback((filename: string) => {
    const lower = filename.toLowerCase()
    const match = sourceDocs.find((d) => {
      const fn = d.filename.toLowerCase()
      const title = (d.title || '').toLowerCase()
      return fn === lower || title === lower || fn === lower + '.md' || fn.replace(/\.md$/, '') === lower
    })
    if (match) openSourceDoc(match)
  }, [openSourceDoc, sourceDocs])

  const showMainLoading =
    loading ||
    (hasNavigableWiki && !wikiActivePath) ||
    (!!wikiActivePath && pageLoadedPath !== wikiActivePath)

  return (
    <div className="flex h-full flex-col">
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <div className="shrink-0">
          <KBSidenav
            kbId={kbId}
            kbName={kbName}
            wikiTree={displayTree}
            wikiActivePath={wikiActivePath}
            onWikiNavigate={handleWikiSelect}
            sourceDocs={sourceDocs}
            hasWiki={hasNavigableWiki}
            loading={loading}
            onUpload={() => router.push(`/wikis/${kbSlug}/files`)}
            filesViewActive={false}
            onFilesToggle={() => router.push(`/wikis/${kbSlug}/files`)}
            graphViewActive={false}
            onGraphToggle={() => router.push(`/wikis/${kbSlug}/graph`)}
            onOpenSourceDoc={(docId) => {
              const doc = documents.find((d) => d.id === docId)
              if (doc) openSourceDoc(doc)
            }}
            courseMode={courseMode}
            courseCurrentPath={currentLessonPath}
            courseProgress={courseMode ? { completed: completedCount, total: lessons.length } : undefined}
          />
        </div>
        <div className="min-w-0 flex-1">
          {showMainLoading || pageLoading ? (
            <div className="flex h-full items-center justify-center">
              <Loader2 className="size-5 animate-spin text-muted-foreground" />
            </div>
          ) : hasNavigableWiki && wikiActivePath ? (
            <WikiContent
              content={pageContent}
              title={pageTitle}
              path={wikiActivePath}
              documentId={activeWikiDocId}
              onNavigate={handleWikiNavigate}
              onSourceClick={handleCitationSourceClick}
              onGraphClick={() => router.push(`/wikis/${kbSlug}/graph`)}
              documents={documents}
              courseMode={courseMode}
              courseView={courseView}
              isComplete={lessonStatus(activeWikiDoc) === 'complete'}
              prevLesson={prevLesson}
              forwardLabel={forward?.label ?? null}
              onForward={handleForward}
              resumeLesson={resumeLesson}
              onLessonNavigate={handleWikiSelect}
              lessonsTotal={lessons.length}
              lessonsComplete={completedCount}
            />
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-4 px-6">
              <BookOpen className="size-10 text-muted-foreground/20" />
              <div className="max-w-sm text-center">
                <h3 className="mb-1.5 text-base font-medium">No wiki yet</h3>
                <p className="text-sm leading-relaxed text-muted-foreground">
                  Add some sources, then ask Claude to compile a wiki from them.
                </p>
              </div>
              <div className="mt-2 flex items-center gap-3">
                <button
                  onClick={() => router.push(`/wikis/${kbSlug}/files`)}
                  className="inline-flex cursor-pointer items-center gap-2 rounded-full bg-foreground px-5 py-2 text-sm font-medium text-background transition-opacity hover:opacity-90"
                >
                  <UploadIcon className="size-3.5 opacity-60" />
                  Upload Sources
                </button>
                <a
                  href="https://claude.ai"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 rounded-full border border-border px-5 py-2 text-sm font-medium transition-colors hover:bg-accent"
                >
                  Open Claude
                  <ArrowUpRight className="size-3.5 opacity-60" />
                </a>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
