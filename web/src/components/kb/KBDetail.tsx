'use client'

import * as React from 'react'
import { useRouter } from 'next/navigation'
import dynamic from 'next/dynamic'
import { motion, AnimatePresence } from 'framer-motion'
import { Loader2 } from 'lucide-react'
import { useUserStore } from '@/stores'
import { useKBDocuments } from '@/hooks/useKBDocuments'
import { ConfirmDialog } from '@/components/dialogs/ConfirmDialog'
import { KBSidenav } from '@/components/kb/KBSidenav'
import { SelectionActionBar } from '@/components/kb/SelectionActionBar'
import { WikiContent } from '@/components/wiki/WikiContent'
import type { ViewMode } from '@/components/kb/viewMode'
import { DocumentsLoadError } from '@/components/kb/DocumentsLoadError'
import { FileDropOverlay } from '@/components/kb/kb-detail/FileDropOverlay'
import { WikiEmptyState } from '@/components/kb/kb-detail/WikiEmptyState'
import { useBulkSelection } from '@/components/kb/kb-detail/useBulkSelection'
import { useDocumentMutations } from '@/components/kb/kb-detail/useDocumentMutations'
import { useFileDropZone } from '@/components/kb/kb-detail/useFileDropZone'
import { useGraphNavigation } from '@/components/kb/kb-detail/useGraphNavigation'
import { useKBUploads } from '@/components/kb/kb-detail/useKBUploads'
import { useKBViewState } from '@/components/kb/kb-detail/useKBViewState'
import { useSourceDocNavigation } from '@/components/kb/kb-detail/useSourceDocNavigation'
import { useUploadOpenRequest } from '@/components/kb/kb-detail/useUploadOpenRequest'
import { useWikiNavigation } from '@/components/kb/kb-detail/useWikiNavigation'
import { useWikiPage } from '@/components/kb/kb-detail/useWikiPage'
import { useWikiTree } from '@/components/kb/kb-detail/useWikiTree'

const FilesGrid = dynamic(() => import('@/components/kb/FilesGrid').then((mod) => mod.FilesGrid), {
  ssr: false,
  loading: () => <DetailPaneLoading />,
})

const GraphViewer = dynamic(() => import('@/components/kb/GraphViewer').then((mod) => mod.GraphViewer), {
  ssr: false,
  loading: () => <DetailPaneLoading />,
})

function DetailPaneLoading() {
  return (
    <div className="flex h-full items-center justify-center">
      <Loader2 className="size-5 animate-spin text-muted-foreground" />
    </div>
  )
}

type Props = {
  kbId: string
  kbSlug: string
  kbName: string
  viewMode: ViewMode
  routeFilesPath: string
}

export function KBDetail({ kbId, kbSlug, kbName, viewMode, routeFilesPath }: Props) {
  const router = useRouter()
  const token = useUserStore((s) => s.accessToken)
  const userId = useUserStore((s) => s.user?.id)
  const { documents, setDocuments, loading, loadError, refetchDocuments } = useKBDocuments(kbId)

  const wikiDocs = React.useMemo(
    () => documents.filter((d) => (d.path === '/wiki/' || d.path.startsWith('/wiki/')) && !d.archived && d.file_type === 'md'),
    [documents],
  )
  const sourceDocs = React.useMemo(
    () => documents.filter((d) => !d.path.startsWith('/wiki/') && !d.archived),
    [documents],
  )

  const view = useKBViewState(kbSlug, viewMode, documents)
  const { filesViewActive, graphViewActive, wikiActivePath } = view
  const { wikiTree, indexLoaded, hasNavigableWiki } = useWikiTree(wikiDocs, token)
  const { handleWikiSelect, handleWikiNavigate } = useWikiNavigation({ kbSlug, view, wikiDocs, wikiTree, indexLoaded, loading })
  const { pageContent, pageTitle, pageLoading, pageLoadedPath, activeWikiDocId } = useWikiPage(wikiActivePath, wikiDocs, token)
  const selection = useBulkSelection(setDocuments)
  const { clearSelection } = selection
  React.useEffect(() => clearSelection(), [clearSelection, filesViewActive, view.activeSourceDocId])
  const { handleGraphToggle, handleGraphNodeClick, handlePageGraphClick } = useGraphNavigation({ view, documents, activeWikiDocId })
  const sourceNav = useSourceDocNavigation({ view, documents, sourceDocs })
  const mutations = useDocumentMutations({ kbId, userId, setDocuments, filesViewActive, openFilesView: view.openFilesView })
  const { handleUploadClick, uploadFiles } = useKBUploads({
    kbId, kbSlug, userId, documents, setDocuments, sourceDocCount: sourceDocs.length, openFilesView: view.openFilesView,
  })
  useUploadOpenRequest(kbId, documents, view)
  const { isFileDragOver, dropZoneProps } = useFileDropZone(filesViewActive, uploadFiles)

  const rootRef = React.useRef<HTMLDivElement>(null)
  const restoreFocusToRoot = React.useCallback((event: Event) => {
    event.preventDefault()
    rootRef.current?.focus()
  }, [])

  const isWikiPaneActive = !filesViewActive && !graphViewActive
  const showMainLoading =
    loading ||
    (isWikiPaneActive && hasNavigableWiki && !wikiActivePath) ||
    (isWikiPaneActive && !!wikiActivePath && pageLoadedPath !== wikiActivePath)

  return (
    <div
      ref={rootRef}
      tabIndex={-1}
      className="flex flex-col h-full relative outline-none"
      {...dropZoneProps}
    >
      <FileDropOverlay isVisible={isFileDragOver} />

      <div className="flex-1 overflow-hidden flex">
        <div className="shrink-0">
          <KBSidenav
            kbId={kbId}
            kbName={kbName}
            wikiTree={wikiTree}
            wikiActivePath={filesViewActive || graphViewActive ? null : wikiActivePath}
            onWikiNavigate={handleWikiSelect}
            sourceDocs={sourceDocs}
            hasWiki={hasNavigableWiki}
            loading={loading}
            onUpload={() => handleUploadClick()}
            filesViewActive={filesViewActive}
            onOpenFiles={sourceNav.handleOpenFiles}
            graphViewActive={graphViewActive}
            onGraphToggle={handleGraphToggle}
            onOpenSourceDoc={sourceNav.handleOpenSourceDoc}
            recentActive={false}
            onRecentSelect={() => router.push(`/wikis/${kbSlug}`)}
          />
        </div>
        <div className="flex-1 min-w-0">
          <AnimatePresence mode="wait">
            {loadError && documents.length === 0 ? (
              <DocumentsLoadError key="load-error" onRetry={refetchDocuments} />
            ) : showMainLoading ? (
              <motion.div
                key="loading"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.1 }}
                className="flex items-center justify-center h-full"
              >
                <Loader2 className="size-5 animate-spin text-muted-foreground" />
              </motion.div>
            ) : graphViewActive ? (
              <motion.div
                key="graph"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.15, ease: [0.25, 0.1, 0.25, 1] }}
                className="h-full"
              >
                <GraphViewer
                  kbId={kbId}
                  focusNodeId={view.graphFocusNodeId}
                  onNavigateToDoc={handleGraphNodeClick}
                />
              </motion.div>
            ) : filesViewActive ? (
              <motion.div
                key="files"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.15, ease: [0.25, 0.1, 0.25, 1] }}
                className="h-full"
              >
                <FilesGrid
                  key={kbId}
                  documents={documents}
                  onDeleteDocument={mutations.handleDeleteDocument}
                  onRenameDocument={mutations.handleRenameDocument}
                  onUpload={handleUploadClick}
                  onCreateNote={mutations.handleCreateNote}
                  onCreateFolder={mutations.handleCreateFolder}
                  onMoveDocument={mutations.handleMoveDocument}
                  onUploadFiles={uploadFiles}
                  initialDocId={view.activeSourceDocId}
                  initialPage={view.filesInitialPage}
                  initialPath={routeFilesPath}
                  onPathChange={sourceNav.handleFilesPathChange}
                  onDocOpen={sourceNav.handleFilesDocOpen}
                  onDocClose={sourceNav.handleFilesDocClose}
                  selectedIds={selection.selectedIds}
                  onSelectDocument={selection.selectDocument}
                  onShownFolderChange={selection.clearSelection}
                />
              </motion.div>
            ) : pageLoading ? (
              <motion.div
                key="wiki-loading"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.1 }}
                className="flex items-center justify-center h-full"
              >
                <Loader2 className="size-5 animate-spin text-muted-foreground" />
              </motion.div>
            ) : hasNavigableWiki && wikiActivePath ? (
              <motion.div
                key={`wiki-${wikiActivePath}`}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15, ease: [0.25, 0.1, 0.25, 1] }}
                className="h-full"
              >
                <WikiContent
                  content={pageContent}
                  title={pageTitle}
                  path={wikiActivePath ?? undefined}
                  documentId={activeWikiDocId}
                  onNavigate={handleWikiNavigate}
                  onSourceClick={sourceNav.handleCitationSourceClick}
                  onGraphClick={handlePageGraphClick}
                  documents={documents}
                />
              </motion.div>
            ) : (
              <motion.div
                key="empty"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.2, ease: [0.25, 0.1, 0.25, 1] }}
                className="flex flex-col items-center justify-center h-full gap-4 px-6"
              >
                <WikiEmptyState onUpload={() => handleUploadClick()} />
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

      <SelectionActionBar
        count={selection.selectedIds.size}
        onDelete={() => selection.setConfirmingBulkDelete(true)}
        onClear={selection.clearSelection}
      />

      <ConfirmDialog
        open={selection.confirmingBulkDelete}
        onOpenChange={selection.setConfirmingBulkDelete}
        title={`Delete ${selection.selectedIds.size} document${selection.selectedIds.size > 1 ? 's' : ''}?`}
        description="The selected documents will be removed from this wiki. This cannot be undone."
        confirmLabel="Delete"
        busyLabel="Deleting…"
        busy={selection.bulkDeleting}
        onConfirm={selection.deleteSelected}
        destructive
        onCloseAutoFocus={restoreFocusToRoot}
      />
    </div>
  )
}
