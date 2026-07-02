'use client'

import * as React from 'react'
import { apiFetch } from '@/lib/api'
import { useUserStore } from '@/stores'
import { createHighlightId } from '@/lib/highlights/ids'
import type { Highlight, HighlightsResponse, TextAnchor } from '@/lib/highlights/types'

const isLocal = process.env.NEXT_PUBLIC_MODE === 'local'

export interface WikiHighlightsApi {
  highlights: Highlight[]
  saveHighlight: (textAnchor: TextAnchor, comment: string | null) => Promise<void>
  updateComment: (id: string, comment: string | null) => Promise<void>
  removeHighlight: (id: string) => Promise<void>
}

export function useWikiHighlights(documentId: string | null): WikiHighlightsApi {
  const token = useUserStore((s) => s.accessToken)
  const [highlights, setHighlights] = React.useState<Highlight[]>([])

  // The local backend signals the per-doc highlight cap with a 200 + no
  // highlights array; treat it as a failure instead of wiping state.
  const applyResponse = React.useCallback((res: HighlightsResponse) => {
    if (!Array.isArray(res.highlights)) throw new Error('Highlight limit reached for this page')
    setHighlights(res.highlights)
  }, [])

  React.useEffect(() => {
    setHighlights([])
    if (!documentId || (!isLocal && !token)) return
    let cancelled = false
    apiFetch<HighlightsResponse>(`/v1/documents/${documentId}/highlights`, token ?? '')
      .then((res) => {
        if (!cancelled) setHighlights(res.highlights ?? [])
      })
      .catch(() => {
        // Page renders fine without highlights; the next mutation surfaces errors.
      })
    return () => {
      cancelled = true
    }
  }, [documentId, token])

  const saveHighlight = React.useCallback(
    async (textAnchor: TextAnchor, comment: string | null): Promise<void> => {
      if (!documentId) return
      const highlight: Highlight = {
        id: createHighlightId(),
        type: 'text',
        anchor: null,
        textAnchor,
        comment: comment?.trim() || null,
        color: 'yellow',
        createdAt: new Date().toISOString(),
      }
      const res = await apiFetch<HighlightsResponse>(
        `/v1/documents/${documentId}/highlights`,
        token ?? '',
        { method: 'POST', body: JSON.stringify({ highlight }) },
      )
      applyResponse(res)
    },
    [applyResponse, documentId, token],
  )

  const updateComment = React.useCallback(
    async (id: string, comment: string | null): Promise<void> => {
      if (!documentId) return
      const existing = highlights.find((h) => h.id === id)
      if (!existing) return
      const highlight: Highlight = { ...existing, comment: comment?.trim() || null }
      const res = await apiFetch<HighlightsResponse>(
        `/v1/documents/${documentId}/highlights`,
        token ?? '',
        { method: 'POST', body: JSON.stringify({ highlight }) },
      )
      applyResponse(res)
    },
    [applyResponse, documentId, highlights, token],
  )

  const removeHighlight = React.useCallback(
    async (id: string): Promise<void> => {
      if (!documentId) return
      const res = await apiFetch<HighlightsResponse>(
        `/v1/documents/${documentId}/highlights/${encodeURIComponent(id)}`,
        token ?? '',
        { method: 'DELETE' },
      )
      applyResponse(res)
    },
    [applyResponse, documentId, token],
  )

  return { highlights, saveHighlight, updateComment, removeHighlight }
}
