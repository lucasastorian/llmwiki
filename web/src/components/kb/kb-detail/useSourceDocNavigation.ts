import * as React from 'react'
import type { DocumentListItem } from '@/lib/types'
import { replaceSearchParam } from './helpers'
import type { KBViewState } from './useKBViewState'

type Params = {
  view: KBViewState
  documents: DocumentListItem[]
  sourceDocs: DocumentListItem[]
}

export interface SourceDocNavigation {
  handleOpenFiles: () => void
  handleOpenSourceDoc: (docId: string) => void
  handleCitationSourceClick: (filename: string, page?: number) => void
  handleFilesPathChange: (path: string) => void
  handleFilesDocOpen: (docNumber: number | null) => void
  handleFilesDocClose: () => void
}

/** Opening the files browser and source documents, keeping the files route and ?doc= in sync. */
export function useSourceDocNavigation({ view, documents, sourceDocs }: Params): SourceDocNavigation {
  const { activeView, setActiveView, setActiveSourceDocId, setFilesInitialPage, showSourceDoc, navigateToView, openFilesView } = view

  const handleOpenFiles = React.useCallback(() => {
    if (activeView === 'files') return
    if (activeView === 'doc') setActiveSourceDocId(null)
    openFilesView()
  }, [activeView, setActiveSourceDocId, openFilesView])

  const handleOpenSourceDoc = React.useCallback((docId: string) => {
    const doc = documents.find((d) => d.id === docId)
    if (!doc) return
    showSourceDoc(doc.id)
    if (doc.document_number != null) {
      navigateToView('files', { searchParams: { doc: String(doc.document_number) } })
    }
  }, [documents, showSourceDoc, navigateToView])

  const handleCitationSourceClick = React.useCallback((filename: string, page?: number) => {
    const match = findSourceDocByName(sourceDocs, filename)
    if (!match) return
    showSourceDoc(match.id)
    setFilesInitialPage(page)
    if (match.document_number != null) {
      navigateToView('files', { searchParams: { doc: String(match.document_number) } })
    }
  }, [sourceDocs, showSourceDoc, setFilesInitialPage, navigateToView])

  // pushState so each folder is a back-button stop; FilesGrid already holds the path.
  const handleFilesPathChange = React.useCallback((path: string) => {
    navigateToView('files', { filesPath: path })
  }, [navigateToView])

  const handleFilesDocOpen = React.useCallback((docNumber: number | null) => {
    if (docNumber == null) return
    const doc = documents.find((d) => d.document_number === docNumber)
    if (!doc) return
    showSourceDoc(doc.id)
    replaceSearchParam('doc', String(docNumber))
  }, [documents, showSourceDoc])

  const handleFilesDocClose = React.useCallback(() => {
    setActiveSourceDocId(null)
    setActiveView('files')
    replaceSearchParam('doc', null)
  }, [setActiveSourceDocId, setActiveView])

  return {
    handleOpenFiles,
    handleOpenSourceDoc,
    handleCitationSourceClick,
    handleFilesPathChange,
    handleFilesDocOpen,
    handleFilesDocClose,
  }
}

function findSourceDocByName(sourceDocs: DocumentListItem[], filename: string): DocumentListItem | undefined {
  const lower = filename.toLowerCase()
  return sourceDocs.find((d) => {
    const fn = d.filename.toLowerCase()
    const title = (d.title || '').toLowerCase()
    return fn === lower || title === lower || fn === lower + '.md' || fn.replace(/\.md$/, '') === lower
  })
}
