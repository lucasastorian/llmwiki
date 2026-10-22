'use client'

import * as React from 'react'
import { createHighlightId } from '@/lib/highlights/ids'
import type { Highlight, TextAnchor } from '@/lib/highlights/types'
import { useDocumentHighlights } from './useDocumentHighlights'

export interface WikiHighlightsApi {
  highlights: Highlight[]
  saveHighlight: (textAnchor: TextAnchor, comment: string | null, id?: string) => Promise<void>
  updateComment: (id: string, comment: string | null) => Promise<void>
  removeHighlight: (id: string) => Promise<void>
}

export function useWikiHighlights(documentId: string | null, remoteVersion: number | null = null): WikiHighlightsApi {
  const api = useDocumentHighlights(documentId, remoteVersion)

  const saveHighlight = React.useCallback(
    (textAnchor: TextAnchor, comment: string | null, id?: string): Promise<void> => api.saveHighlight({
      id: id ?? createHighlightId(),
      type: 'text',
      anchor: null,
      textAnchor,
      pdfAnchor: null,
      comment: comment?.trim() || null,
      color: 'yellow',
      createdAt: new Date().toISOString(),
    }),
    [api.saveHighlight],
  )

  return {
    highlights: api.highlights,
    saveHighlight,
    updateComment: api.updateComment,
    removeHighlight: api.removeHighlight,
  }
}
