import * as React from 'react'
import { findFirstPath, resolveWikiHref, wikiRelativePath } from '@/lib/wikiTree'
import type { DocumentListItem, WikiNode } from '@/lib/types'
import { findWikiDocByPath, replaceSearchParam } from './helpers'
import type { KBViewState } from './useKBViewState'

type Params = {
  kbSlug: string
  view: KBViewState
  wikiDocs: DocumentListItem[]
  wikiTree: WikiNode[]
  indexLoaded: boolean
  loading: boolean
}

export interface WikiNavigation {
  handleWikiSelect: (path: string, docNumber?: number | null) => void
  handleWikiNavigate: (path: string) => void
}

/** Wiki page selection from the sidenav and in-page links, plus opening the first page by default. */
export function useWikiNavigation({ kbSlug, view, wikiDocs, wikiTree, indexLoaded, loading }: Params): WikiNavigation {
  const { activeView, urlWikiDocNumber, wikiActivePath, setWikiActivePath, lastWikiDocNumberRef, showWikiPage, navigateToView } = view

  React.useEffect(() => {
    if (!indexLoaded || activeView !== 'wiki' || wikiActivePath || urlWikiDocNumber != null || !wikiTree.length || loading) return
    const first = findFirstPath(wikiTree)
    if (!first) return
    setWikiActivePath(first.path)
    lastWikiDocNumberRef.current = first.docNumber
    if (first.docNumber != null) replaceSearchParam('p', String(first.docNumber))
  }, [indexLoaded, wikiTree, wikiActivePath, activeView, urlWikiDocNumber, loading, setWikiActivePath, lastWikiDocNumberRef])

  const wikiPathSet = React.useMemo(() => new Set(wikiDocs.map(wikiRelativePath)), [wikiDocs])

  const handleWikiSelect = React.useCallback((path: string, docNumber?: number | null) => {
    const num = docNumber ?? findWikiDocByPath(wikiDocs, path)?.document_number ?? null
    showWikiPage(path, num)
    // Off the wiki route the pathname must change too, or reload restores the wrong view.
    if (window.location.pathname === `/wikis/${kbSlug}`) {
      if (num != null) replaceSearchParam('p', String(num))
    } else {
      navigateToView('wiki', num != null ? { searchParams: { p: String(num) } } : undefined)
    }
  }, [showWikiPage, navigateToView, kbSlug, wikiDocs])

  const handleWikiNavigate = React.useCallback((path: string) => {
    const nextPath = resolveWikiHref(path, wikiActivePath, wikiPathSet)
    setWikiActivePath(nextPath)
    const doc = findWikiDocByPath(wikiDocs, nextPath)
    lastWikiDocNumberRef.current = doc?.document_number ?? null
    if (doc?.document_number != null) replaceSearchParam('p', String(doc.document_number))
  }, [wikiActivePath, wikiPathSet, setWikiActivePath, lastWikiDocNumberRef, wikiDocs])

  return { handleWikiSelect, handleWikiNavigate }
}
