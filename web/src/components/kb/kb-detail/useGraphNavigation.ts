import * as React from 'react'
import type { DocumentListItem } from '@/lib/types'
import { wikiRelativePath } from '@/lib/wikiTree'
import type { KBViewState } from './useKBViewState'

type Params = {
  view: KBViewState
  documents: DocumentListItem[]
  activeWikiDocId: string | null
}

export interface GraphNavigation {
  handleGraphToggle: () => void
  handleGraphNodeClick: (docId: string, sourceKind: string) => void
  handlePageGraphClick: () => void
}

/** Entering and leaving the graph view, and opening documents from graph nodes. */
export function useGraphNavigation({ view, documents, activeWikiDocId }: Params): GraphNavigation {
  const { graphViewActive, setActiveView, setGraphFocusNodeId, lastWikiDocNumberRef, showWikiPage, showSourceDoc, navigateToView } = view

  const handleGraphToggle = React.useCallback(() => {
    if (graphViewActive) {
      const sp = lastWikiDocNumberRef.current != null
        ? { p: String(lastWikiDocNumberRef.current) }
        : undefined
      navigateToView('wiki', { searchParams: sp })
      return
    }
    setActiveView('graph')
    setGraphFocusNodeId(null)
    navigateToView('graph')
  }, [graphViewActive, lastWikiDocNumberRef, setActiveView, setGraphFocusNodeId, navigateToView])

  const handleGraphNodeClick = React.useCallback((docId: string, sourceKind: string) => {
    const doc = documents.find((d) => d.id === docId)
    if (!doc) return
    const docNumberParam = doc.document_number != null ? String(doc.document_number) : null
    if (sourceKind === 'wiki') {
      showWikiPage(wikiRelativePath(doc), doc.document_number)
      navigateToView('wiki', { searchParams: docNumberParam != null ? { p: docNumberParam } : undefined })
      return
    }
    showSourceDoc(doc.id)
    navigateToView('files', { searchParams: docNumberParam != null ? { doc: docNumberParam } : undefined })
  }, [documents, showWikiPage, showSourceDoc, navigateToView])

  const handlePageGraphClick = React.useCallback(() => {
    if (!activeWikiDocId) return
    setActiveView('graph')
    setGraphFocusNodeId(activeWikiDocId)
    navigateToView('graph')
  }, [activeWikiDocId, setActiveView, setGraphFocusNodeId, navigateToView])

  return { handleGraphToggle, handleGraphNodeClick, handlePageGraphClick }
}
