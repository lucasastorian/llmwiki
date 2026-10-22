import * as React from 'react'
import { toast } from 'sonner'
import { bulkDeleteDocuments } from '@/lib/api'
import type { DocumentListItem } from '@/lib/types'
import { getAccessTokenOrToast } from './helpers'

const SERVER_BULK_DELETE_MAX_IDS = 100

type SetDocuments = React.Dispatch<React.SetStateAction<DocumentListItem[]>>

export type SelectionGesture = 'toggle' | 'range'

export interface BulkSelection {
  selectedIds: Set<string>
  selectDocument: (docId: string, gesture: SelectionGesture, visibleIds: readonly string[]) => void
  clearSelection: () => void
  confirmingBulkDelete: boolean
  setConfirmingBulkDelete: React.Dispatch<React.SetStateAction<boolean>>
  bulkDeleting: boolean
  deleteSelected: () => Promise<void>
}

/** Multi-document selection with Escape-to-clear and a confirmed bulk delete. */
export function useBulkSelection(setDocuments: SetDocuments): BulkSelection {
  const [selectedIds, setSelectedIds] = React.useState<Set<string>>(new Set())
  const lastSelectedIdRef = React.useRef<string | null>(null)
  const [confirmingBulkDelete, setConfirmingBulkDelete] = React.useState(false)
  const [bulkDeleting, setBulkDeleting] = React.useState(false)

  const selectDocument = React.useCallback((docId: string, gesture: SelectionGesture, visibleIds: readonly string[]) => {
    const anchorId = lastSelectedIdRef.current
    lastSelectedIdRef.current = docId
    setSelectedIds((prev) => computeNextSelection(prev, docId, anchorId, gesture, visibleIds))
  }, [])

  const clearSelection = React.useCallback(() => {
    setSelectedIds(new Set())
    lastSelectedIdRef.current = null
  }, [])

  React.useEffect(() => {
    if (selectedIds.size === 0) return
    const handleKeyDown = (e: KeyboardEvent): void => { if (e.key === 'Escape') clearSelection() }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [selectedIds.size, clearSelection])

  const deleteSelected = async (): Promise<void> => {
    const token = getAccessTokenOrToast()
    if (!token) return
    const ids = Array.from(selectedIds)
    setBulkDeleting(true)
    try {
      for (let i = 0; i < ids.length; i += SERVER_BULK_DELETE_MAX_IDS) {
        const batch = ids.slice(i, i + SERVER_BULK_DELETE_MAX_IDS)
        await bulkDeleteDocuments(batch, token)
        const deleted = new Set(batch)
        setDocuments((prev) => prev.filter((d) => !deleted.has(d.id)))
        setSelectedIds((prev) => new Set([...prev].filter((id) => !deleted.has(id))))
      }
      clearSelection()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete documents')
    } finally {
      setBulkDeleting(false)
      setConfirmingBulkDelete(false)
    }
  }

  return { selectedIds, selectDocument, clearSelection, confirmingBulkDelete, setConfirmingBulkDelete, bulkDeleting, deleteSelected }
}

/** Selection after a modifier-click: toggle one id, or add the anchor-to-target span of `visibleIds`. */
export function computeNextSelection(
  prev: ReadonlySet<string>,
  docId: string,
  anchorId: string | null,
  gesture: SelectionGesture,
  visibleIds: readonly string[],
): Set<string> {
  const next = new Set(prev)
  if (gesture === 'toggle') {
    if (next.has(docId)) next.delete(docId)
    else next.add(docId)
    return next
  }
  for (const id of idsBetween(visibleIds, anchorId, docId)) next.add(id)
  return next
}

function idsBetween(visibleIds: readonly string[], anchorId: string | null, docId: string): readonly string[] {
  const from = anchorId ? visibleIds.indexOf(anchorId) : -1
  const to = visibleIds.indexOf(docId)
  if (from === -1 || to === -1) return [docId]
  return visibleIds.slice(Math.min(from, to), Math.max(from, to) + 1)
}
