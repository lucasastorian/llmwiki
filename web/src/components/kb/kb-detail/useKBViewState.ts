import * as React from 'react'
import { useSearchParams } from 'next/navigation'
import type { DocumentListItem } from '@/lib/types'
import type { ViewMode } from '@/components/kb/viewMode'
import { wikiRelativePath } from '@/lib/wikiTree'
import { buildViewUrl, currentSearchParam, type NavigateToView } from './helpers'

export type ActiveView = ViewMode | 'doc'

export interface KBViewState {
  activeView: ActiveView
  setActiveView: React.Dispatch<React.SetStateAction<ActiveView>>
  filesViewActive: boolean
  graphViewActive: boolean
  urlWikiDocNumber: number | null
  wikiActivePath: string | null
  setWikiActivePath: React.Dispatch<React.SetStateAction<string | null>>
  lastWikiDocNumberRef: React.RefObject<number | null>
  activeSourceDocId: string | null
  setActiveSourceDocId: React.Dispatch<React.SetStateAction<string | null>>
  filesInitialPage: number | undefined
  setFilesInitialPage: React.Dispatch<React.SetStateAction<number | undefined>>
  graphFocusNodeId: string | null
  setGraphFocusNodeId: React.Dispatch<React.SetStateAction<string | null>>
  showSourceDoc: (docId: string) => void
  showWikiPage: (path: string, docNumber: number | null) => void
  navigateToView: NavigateToView
  openFilesView: () => void
}

function findWikiDocId(documents: DocumentListItem[], path: string): string | null {
  const doc = documents.find((d) => d.path.startsWith('/wiki/') && wikiRelativePath(d) === path)
  return doc?.id ?? null
}

/** Holds which pane, wiki page, and source document KBDetail shows, seeded from and pushed to the URL. */
export function useKBViewState(kbSlug: string, viewMode: ViewMode, documents: DocumentListItem[]): KBViewState {
  const searchParams = useSearchParams()

  const navigateToView = React.useCallback<NavigateToView>((view, opts) => {
    window.history.pushState(window.history.state, '', buildViewUrl(kbSlug, view, opts))
  }, [kbSlug])

  const [activeView, setActiveView] = React.useState<ActiveView>(viewMode)
  React.useEffect(() => { setActiveView(viewMode) }, [viewMode])

  const pParam = searchParams.get('p')
  const urlWikiDocNumber = pParam ? parseInt(pParam, 10) : null

  const [wikiActivePath, setWikiActivePath] = React.useState<string | null>(null)
  const lastWikiDocNumberRef = React.useRef<number | null>(urlWikiDocNumber)
  const handledUrlDocNumberRef = React.useRef<number | null>(null)

  // Once per URL value: `documents` churn plus useSearchParams lagging replaceState would snap navigation back.
  React.useEffect(() => {
    if (urlWikiDocNumber == null || !documents.length) return
    if (urlWikiDocNumber === handledUrlDocNumberRef.current) return
    if (currentSearchParam('p') !== String(urlWikiDocNumber)) return
    const doc = documents.find((d) => d.document_number === urlWikiDocNumber)
    if (!doc) return
    handledUrlDocNumberRef.current = urlWikiDocNumber
    setWikiActivePath(wikiRelativePath(doc))
    lastWikiDocNumberRef.current = urlWikiDocNumber
  }, [urlWikiDocNumber, documents])

  const documentsRef = React.useRef(documents)
  documentsRef.current = documents
  const activeWikiDocRef = React.useRef<{ id: string; path: string } | null>(null)

  React.useEffect(() => {
    const id = wikiActivePath === null ? null : findWikiDocId(documentsRef.current, wikiActivePath)
    activeWikiDocRef.current = id && wikiActivePath !== null ? { id, path: wikiActivePath } : null
  }, [wikiActivePath])

  React.useEffect(() => {
    const active = activeWikiDocRef.current
    const doc = active ? documents.find((d) => d.id === active.id) : undefined
    if (!active || !doc) return
    const renamedPath = wikiRelativePath(doc)
    if (renamedPath === active.path) return
    activeWikiDocRef.current = { id: active.id, path: renamedPath }
    // Only follow the rename if nothing navigated away from the old path in the meantime.
    setWikiActivePath((path) => (path === active.path ? renamedPath : path))
  }, [documents])

  // ?doc= is read only on mount (bookmarks, back/forward).
  const initialDocParam = React.useRef(searchParams.get('doc'))
  const initialDocNumber = initialDocParam.current ? parseInt(initialDocParam.current, 10) : null

  const [activeSourceDocId, setActiveSourceDocId] = React.useState<string | null>(() => {
    if (initialDocNumber == null) return null
    const doc = documents.find((d) => d.document_number === initialDocNumber)
    return doc?.id ?? null
  })

  const showSourceDoc = React.useCallback((docId: string) => {
    setActiveSourceDocId(docId)
    setActiveView('doc')
  }, [])

  const showWikiPage = React.useCallback((path: string, docNumber: number | null) => {
    setActiveView('wiki')
    setWikiActivePath(path)
    lastWikiDocNumberRef.current = docNumber
  }, [])

  React.useEffect(() => {
    if (initialDocNumber == null || activeSourceDocId) return
    const doc = documents.find((d) => d.document_number === initialDocNumber)
    if (doc) showSourceDoc(doc.id)
  }, [initialDocNumber, documents, activeSourceDocId, showSourceDoc])

  const openFilesView = React.useCallback(() => {
    setActiveView('files')
    navigateToView('files')
  }, [navigateToView])

  const [filesInitialPage, setFilesInitialPage] = React.useState<number | undefined>()
  const [graphFocusNodeId, setGraphFocusNodeId] = React.useState<string | null>(null)

  return {
    activeView,
    setActiveView,
    filesViewActive: activeView === 'files' || activeView === 'doc',
    graphViewActive: activeView === 'graph',
    urlWikiDocNumber,
    wikiActivePath,
    setWikiActivePath,
    lastWikiDocNumberRef,
    activeSourceDocId,
    setActiveSourceDocId,
    filesInitialPage,
    setFilesInitialPage,
    graphFocusNodeId,
    setGraphFocusNodeId,
    showSourceDoc,
    showWikiPage,
    navigateToView,
    openFilesView,
  }
}
