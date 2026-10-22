'use client'

import * as React from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { ArrowUpRight, BookOpen, Loader2, PlugZap, Upload as UploadIcon } from 'lucide-react'
import { toast } from 'sonner'
import { ConfirmDialog } from '@/components/dialogs/ConfirmDialog'
import { KBSidenav } from '@/components/kb/KBSidenav'
import { PlanProgress } from '@/components/kb/PlanProgress'
import { RecentChanges } from '@/components/kb/RecentChanges'
import { DocumentsLoadError } from '@/components/kb/DocumentsLoadError'
import { openMcpConnectionDock } from '@/components/connections/McpConnectionDock'
import { WikiContent } from '@/components/wiki/WikiContent'
import { useKBDocuments } from '@/hooks/useKBDocuments'
import { apiFetch } from '@/lib/api'
import { useUserStore } from '@/stores'
import type { DocumentListItem, WikiNode } from '@/lib/types'
import {
  enrichTreeWithProgress, findCurrentLesson, findFirstPath, flattenLessons, flattenPages, lessonStatus, resolveWikiHref,
  wikiRelativePath,
} from '@/lib/wikiTree'
import { isOwnWrite } from '@/lib/highlights/ownWrites'
import { parsePlanTasks, type PlanSummary } from '@/lib/planTasks'
import { useCourseProgress } from '@/hooks/useCourseProgress'
import { useWikiTree } from '@/components/kb/kb-detail/useWikiTree'

const isLocal = process.env.NEXT_PUBLIC_MODE === 'local'

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
  const { documents, setDocuments, loading, loadError, refetchDocuments } = useKBDocuments(kbId)
  const [filesNavPending, setFilesNavPending] = React.useState(false)
  const courseMode = kbKind === 'course'
  const { markComplete } = useCourseProgress(setDocuments)

  const updateParam = React.useCallback((key: string, value: string | null, mode: 'push' | 'replace' = 'replace') => {
    const url = new URL(window.location.href)
    if (url.searchParams.get(key) === value) return
    if (value != null) url.searchParams.set(key, value)
    else url.searchParams.delete(key)
    const next = url.pathname + url.search
    if (mode === 'push') window.history.pushState(window.history.state, '', next)
    else window.history.replaceState(window.history.state, '', next)
  }, [])

  const wikiDocs = React.useMemo(
    () => documents.filter((d) => (d.path === '/wiki/' || d.path.startsWith('/wiki/')) && !d.archived && d.file_type === 'md'),
    [documents],
  )
  const sourceDocs = React.useMemo(
    () => documents.filter((d) => !d.path.startsWith('/wiki/') && !d.archived),
    [documents],
  )
  const wikiPathSet = React.useMemo(() => new Set(wikiDocs.map(wikiRelativePath)), [wikiDocs])

  const pParam = searchParams.get('p')
  const urlWikiDocNumber = pParam ? parseInt(pParam, 10) : null
  const [wikiActivePath, setWikiActivePath] = React.useState<string | null>(null)
  const handledUrlDocNumberRef = React.useRef<number | null>(null)

  // Once per URL value: `documents` churn plus useSearchParams lagging replaceState would snap navigation back.
  React.useEffect(() => {
    if (urlWikiDocNumber == null || !documents.length) return
    if (urlWikiDocNumber === handledUrlDocNumberRef.current) return
    if (new URL(window.location.href).searchParams.get('p') !== String(urlWikiDocNumber)) return
    const doc = documents.find((d) => d.document_number === urlWikiDocNumber)
    if (!doc) {
      if (!courseMode) {
        handledUrlDocNumberRef.current = null
        setWikiActivePath(null)
        updateParam('p', null)
      }
      return
    }
    handledUrlDocNumberRef.current = urlWikiDocNumber
    setWikiActivePath(wikiRelativePath(doc))
  }, [courseMode, documents, updateParam, urlWikiDocNumber])

  // Browser back/forward can return from a page deep link to the wiki root.
  React.useEffect(() => {
    if (courseMode || urlWikiDocNumber != null) return
    if (new URL(window.location.href).searchParams.has('p')) return
    handledUrlDocNumberRef.current = null
    setWikiActivePath(null)
  }, [courseMode, urlWikiDocNumber])

  const { wikiTree, indexLoaded, hasNavigableWiki } = useWikiTree(wikiDocs, token)

  const planDoc = React.useMemo(
    () => wikiDocs.find((d) => d.path === '/wiki/' && d.filename === 'plan.md') ?? null,
    [wikiDocs],
  )
  const [planSummary, setPlanSummary] = React.useState<PlanSummary | null>(null)

  React.useEffect(() => {
    if (courseMode || !planDoc || !token) {
      setPlanSummary(null)
      return
    }
    let cancelled = false
    apiFetch<{ content: string }>(`/v1/documents/${planDoc.id}/content`, token)
      .then((res) => {
        if (!cancelled) setPlanSummary(parsePlanTasks(res.content || ''))
      })
      .catch(() => {
        if (!cancelled) setPlanSummary(null)
      })
    return () => { cancelled = true }
  }, [courseMode, planDoc?.id, planDoc?.version, token])

  React.useEffect(() => {
    if (courseMode && indexLoaded && !wikiActivePath && urlWikiDocNumber == null && wikiTree.length && !loading) {
      const first = findFirstPath(wikiTree)
      if (first) {
        setWikiActivePath(first.path)
        if (first.docNumber != null) updateParam('p', String(first.docNumber))
      }
    }
  }, [courseMode, indexLoaded, wikiTree, wikiActivePath, urlWikiDocNumber, loading, updateParam])

  const [pageContent, setPageContent] = React.useState('')
  const [pageTitle, setPageTitle] = React.useState('')
  const [pageLoading, setPageLoading] = React.useState(false)
  const [pageLoadedPath, setPageLoadedPath] = React.useState<string | null>(null)

  const activeWikiDoc = React.useMemo(() => {
    if (!wikiActivePath) return null
    return wikiDocs.find((d) => wikiRelativePath(d) === wikiActivePath) ?? null
  }, [wikiActivePath, wikiDocs])

  const activeWikiVersion = activeWikiDoc?.version ?? -1
  const activeWikiDocId = activeWikiDoc?.id ?? null

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
    const doc = wikiDocs.find((d) => wikiRelativePath(d) === 'overview.md')
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

  const pagerNeighbors = React.useMemo(() => {
    if (courseMode || !wikiActivePath) return { prev: null, next: null }
    const pages = flattenPages(displayTree)
    const index = pages.findIndex((p) => p.path === wikiActivePath)
    if (index < 0) return { prev: null, next: null }
    const toLink = (node: WikiNode | undefined) =>
      node?.path ? { title: node.title, path: node.path } : null
    return { prev: toLink(pages[index - 1]), next: toLink(pages[index + 1]) }
  }, [courseMode, displayTree, wikiActivePath])

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
    // Highlight saves bump the version without changing content.
    if (isLiveUpdate && isOwnWrite(activeWikiDoc.id, activeWikiDoc.version)) return
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
    const num = docNumber ?? wikiDocs.find((d) => wikiRelativePath(d) === path)?.document_number ?? null
    if (num != null) {
      // Our own URL write — mark handled so the sync effect never re-applies it.
      handledUrlDocNumberRef.current = num
      updateParam('p', String(num), 'push')
    }
  }, [updateParam, wikiDocs])

  const handleRecentSelect = React.useCallback(() => {
    handledUrlDocNumberRef.current = null
    setWikiActivePath(null)
    updateParam('p', null, 'push')
  }, [updateParam])

  // Locks are a progression cue, not enforcement, so a deep-linked read still completes.
  const handleForward = React.useCallback(() => {
    if (!forward) return
    if (activeWikiDoc && lessonStatus(activeWikiDoc) !== 'complete') {
      markComplete(activeWikiDoc.id)
    }
    handleWikiSelect(forward.path)
  }, [forward, activeWikiDoc, markComplete, handleWikiSelect])

  const handleWikiNavigate = React.useCallback(
    (path: string) => {
      handleWikiSelect(resolveWikiHref(path, wikiActivePath, wikiPathSet))
    },
    [handleWikiSelect, wikiActivePath, wikiPathSet],
  )

  const [confirmingDelete, setConfirmingDelete] = React.useState(false)
  const rootRef = React.useRef<HTMLDivElement>(null)

  const restoreFocusToRoot = React.useCallback((event: Event) => {
    event.preventDefault()
    rootRef.current?.focus()
  }, [])
  const [deletingPage, setDeletingPage] = React.useState(false)
  const isStructuralPage = wikiActivePath === 'overview.md' || wikiActivePath === 'log.md'

  const handleDeletePage = React.useCallback(async () => {
    if (!activeWikiDoc || !token) return
    const target = pagerNeighbors.next ?? pagerNeighbors.prev
    setDeletingPage(true)
    try {
      await apiFetch(`/v1/documents/${activeWikiDoc.id}`, token, { method: 'DELETE' })
    } catch {
      toast.error('Failed to delete page')
      return
    } finally {
      setDeletingPage(false)
    }
    setConfirmingDelete(false)
    setDocuments((prev) => prev.filter((d) => d.id !== activeWikiDoc.id))
    if (target) {
      handleWikiSelect(target.path)
      return
    }
    setWikiActivePath(null)
    updateParam('p', null)
  }, [activeWikiDoc, token, pagerNeighbors, setDocuments, handleWikiSelect, updateParam])

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
    (courseMode && hasNavigableWiki && !wikiActivePath) ||
    (!!wikiActivePath && pageLoadedPath !== wikiActivePath)

  const activityRefreshKey = React.useMemo(
    () => documents.map((document) => [
      document.id,
      document.version,
      document.status,
      document.archived,
      document.title,
      document.path,
      document.filename,
    ].join(':')).join('|'),
    [documents],
  )

  return (
    <div ref={rootRef} tabIndex={-1} className="flex h-full flex-col outline-none">
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
            onUpload={() => { setFilesNavPending(true); router.push(`/wikis/${kbSlug}/files`) }}
            filesViewActive={filesNavPending}
            onOpenFiles={() => { setFilesNavPending(true); router.push(`/wikis/${kbSlug}/files`) }}
            graphViewActive={false}
            onGraphToggle={() => router.push(`/wikis/${kbSlug}/graph`)}
            onOpenSourceDoc={(docId) => {
              const doc = documents.find((d) => d.id === docId)
              if (doc) openSourceDoc(doc)
            }}
            recentActive={!courseMode && wikiActivePath == null}
            onRecentSelect={courseMode ? undefined : handleRecentSelect}
            courseMode={courseMode}
            courseCurrentPath={currentLessonPath}
            courseProgress={courseMode ? { completed: completedCount, total: lessons.length } : undefined}
          />
        </div>
        <div className="min-w-0 flex-1">
          {loadError && documents.length === 0 ? (
            <DocumentsLoadError onRetry={refetchDocuments} />
          ) : showMainLoading || pageLoading ? (
            <div className="flex h-full items-center justify-center">
              <Loader2 className="size-5 animate-spin text-muted-foreground" />
            </div>
          ) : !courseMode && !wikiActivePath ? (
            <div className="h-full animate-tab-in">
              <RecentChanges
                kbId={kbId}
                kbSlug={kbSlug}
                kbName={kbName}
                documents={documents}
                refreshKey={activityRefreshKey}
                onWikiNavigate={handleWikiSelect}
                planSlot={planSummary && planSummary.total > 0 ? (
                  <PlanProgress
                    summary={planSummary}
                    onOpen={() => handleWikiSelect('plan.md', planDoc?.document_number ?? null)}
                  />
                ) : null}
              />
            </div>
          ) : hasNavigableWiki && wikiActivePath ? (
            <div key={wikiActivePath} className="h-full animate-tab-in">
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
              prevPage={pagerNeighbors.prev}
              nextPage={pagerNeighbors.next}
              onDelete={isStructuralPage ? null : () => setConfirmingDelete(true)}
            />
            </div>
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-4 px-6 animate-tab-in">
              <BookOpen className="size-10 text-muted-foreground/20" />
              <div className="max-w-sm text-center">
                <h3 className="mb-1.5 text-base font-medium">No wiki yet</h3>
                <p className="text-sm leading-relaxed text-muted-foreground">
                  Connect an AI to create the first pages, or add sources for it to work from.
                </p>
              </div>
              <div className="mt-2 flex items-center gap-3">
                <button
                  onClick={() => router.push(`/wikis/${kbSlug}/files`)}
                  className="inline-flex cursor-pointer items-center gap-2 rounded-full bg-foreground px-5 py-2 text-sm font-medium text-background transition-opacity hover:opacity-90"
                >
                  <UploadIcon className="size-3.5 opacity-60" />
                  Upload sources
                </button>
                {isLocal ? (
                  <a
                    href="https://claude.ai"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-2 rounded-full border border-border px-5 py-2 text-sm font-medium transition-colors hover:bg-accent"
                  >
                    Open Claude
                    <ArrowUpRight className="size-3.5 opacity-60" />
                  </a>
                ) : (
                  <button
                    type="button"
                    onClick={openMcpConnectionDock}
                    className="inline-flex items-center gap-2 rounded-full border border-border px-5 py-2 text-sm font-medium transition-colors hover:bg-accent"
                  >
                    Connect AI
                    <PlugZap className="size-3.5 text-accent-blue" />
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
      <ConfirmDialog
        open={confirmingDelete}
        onOpenChange={setConfirmingDelete}
        title="Delete this page?"
        description={<>&ldquo;{pageTitle}&rdquo; will be removed from this wiki. This can&apos;t be undone.</>}
        confirmLabel="Delete"
        busyLabel="Deleting…"
        busy={deletingPage}
        onConfirm={handleDeletePage}
        destructive
        onCloseAutoFocus={restoreFocusToRoot}
      />
    </div>
  )
}
