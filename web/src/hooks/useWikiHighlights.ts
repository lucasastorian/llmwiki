'use client'

import * as React from 'react'
import { apiFetch } from '@/lib/api'
import { useUserStore } from '@/stores'
import { createHighlightId } from '@/lib/highlights/ids'
import { isOwnWrite, markOwnWrite } from '@/lib/highlights/ownWrites'
import type { Highlight, HighlightsResponse, TextAnchor } from '@/lib/highlights/types'

const isLocal = process.env.NEXT_PUBLIC_MODE === 'local'

export interface WikiHighlightsApi {
  highlights: Highlight[]
  saveHighlight: (textAnchor: TextAnchor, comment: string | null, id?: string) => Promise<void>
  updateComment: (id: string, comment: string | null) => Promise<void>
  removeHighlight: (id: string) => Promise<void>
}

export interface DocumentHighlightsApi {
  highlights: Highlight[]
  saveHighlight: (highlight: Highlight) => Promise<void>
  updateComment: (id: string, comment: string | null) => Promise<void>
  removeHighlight: (id: string) => Promise<void>
}

/** Canonical highlight sidecar client shared by text and PDF viewers. */
export function useDocumentHighlights(
  documentId: string | null,
  remoteVersion: number | null = null,
): DocumentHighlightsApi {
  const token = useUserStore((s) => s.accessToken)
  const [highlights, setHighlights] = React.useState<Highlight[]>([])
  const lastAppliedVersionRef = React.useRef(-1)
  const fetchedDocRef = React.useRef<string | null>(null)

  // Responses from concurrent in-flight requests can arrive out of order;
  // the doc version is monotonic, so older snapshots are dropped.
  const applyServerState = React.useCallback((res: HighlightsResponse) => {
    if (!Array.isArray(res.highlights)) return
    if (res.version <= lastAppliedVersionRef.current) return
    lastAppliedVersionRef.current = res.version
    setHighlights(res.highlights)
  }, [])

  // The local backend signals the per-doc highlight cap with a 200 + no
  // highlights array; treat it as a failure instead of wiping state.
  const applyResponse = React.useCallback((res: HighlightsResponse) => {
    if (!Array.isArray(res.highlights)) throw new Error('Highlight limit reached for this page')
    markOwnWrite(res.id, res.version)
    applyServerState(res)
  }, [applyServerState])

  React.useEffect(() => {
    setHighlights([])
    lastAppliedVersionRef.current = -1
    fetchedDocRef.current = null
  }, [documentId])

  // One fetch path for both the initial load and external version bumps (the
  // agent replying via MCP), so responses can't race each other past the
  // version guard. Own writes are already applied from their POST responses.
  React.useEffect(() => {
    if (!documentId || (!isLocal && !token)) return
    const isInitialLoad = fetchedDocRef.current !== documentId
    if (!isInitialLoad) {
      if (remoteVersion == null || remoteVersion <= lastAppliedVersionRef.current) return
      if (isOwnWrite(documentId, remoteVersion)) return
    }
    fetchedDocRef.current = documentId
    let cancelled = false
    apiFetch<HighlightsResponse>(`/v1/documents/${documentId}/highlights`, token ?? '')
      .then((res) => {
        if (!cancelled) applyServerState(res)
      })
      .catch(() => {
        // Page renders fine without highlights; the next version bump retries.
      })
    return () => {
      cancelled = true
    }
  }, [applyServerState, documentId, remoteVersion, token])

  // All mutations apply optimistically and roll back on failure, so the UI
  // never waits on the network round-trip.
  const saveHighlight = React.useCallback(
    async (highlight: Highlight): Promise<void> => {
      if (!documentId) return
      setHighlights((prev) => [...prev, highlight])
      try {
        const res = await apiFetch<HighlightsResponse>(
          `/v1/documents/${documentId}/highlights`,
          token ?? '',
          { method: 'POST', body: JSON.stringify({ highlight }) },
        )
        applyResponse(res)
      } catch (err) {
        setHighlights((prev) => prev.filter((h) => h.id !== highlight.id))
        throw err
      }
    },
    [applyResponse, documentId, token],
  )

  const updateComment = React.useCallback(
    async (id: string, comment: string | null): Promise<void> => {
      if (!documentId) return
      const existing = highlights.find((h) => h.id === id)
      if (!existing) return
      const highlight: Highlight = { ...existing, comment: comment?.trim() || null }
      setHighlights((prev) => prev.map((h) => (h.id === id ? highlight : h)))
      try {
        const res = await apiFetch<HighlightsResponse>(
          `/v1/documents/${documentId}/highlights`,
          token ?? '',
          { method: 'POST', body: JSON.stringify({ highlight }) },
        )
        applyResponse(res)
      } catch (err) {
        // Restore only if the entry is still our optimistic object — a newer
        // edit may have replaced it while this request was in flight.
        setHighlights((prev) => prev.map((h) => (h === highlight ? existing : h)))
        throw err
      }
    },
    [applyResponse, documentId, highlights, token],
  )

  const removeHighlight = React.useCallback(
    async (id: string): Promise<void> => {
      if (!documentId) return
      const existing = highlights.find((h) => h.id === id)
      if (!existing) return
      setHighlights((prev) => prev.filter((h) => h.id !== id))
      try {
        const res = await apiFetch<HighlightsResponse>(
          `/v1/documents/${documentId}/highlights/${encodeURIComponent(id)}`,
          token ?? '',
          { method: 'DELETE' },
        )
        applyResponse(res)
      } catch (err) {
        setHighlights((prev) => (prev.some((h) => h.id === id) ? prev : [...prev, existing]))
        throw err
      }
    },
    [applyResponse, documentId, highlights, token],
  )

  return { highlights, saveHighlight, updateComment, removeHighlight }
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
