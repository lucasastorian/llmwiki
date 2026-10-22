import * as React from 'react'
import { useUploadStore } from '@/stores'
import type { DocumentListItem } from '@/lib/types'
import type { KBViewState } from './useKBViewState'

/** Opens the source document the upload panel asked for once it exists in this KB. */
export function useUploadOpenRequest(kbId: string, documents: DocumentListItem[], view: KBViewState): void {
  const openRequest = useUploadStore((s) => s.openRequest)
  const consumeOpenRequest = useUploadStore((s) => s.consumeOpenRequest)
  const { showSourceDoc, navigateToView } = view

  React.useEffect(() => {
    if (!openRequest || openRequest.kbId !== kbId) return
    const doc = documents.find((d) => d.document_number === openRequest.documentNumber)
    if (!doc) return
    showSourceDoc(doc.id)
    navigateToView('files', { searchParams: { doc: String(openRequest.documentNumber) } })
    consumeOpenRequest()
  }, [openRequest, kbId, documents, showSourceDoc, navigateToView, consumeOpenRequest])
}
