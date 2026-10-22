'use client'

import * as React from 'react'
import { apiFetch, getDocumentsWsUrl } from '@/lib/api'
import { refreshAccessToken } from '@/lib/auth-token'
import { useUserStore } from '@/stores'
import type { DocumentListItem } from '@/lib/types'

const isLocal = process.env.NEXT_PUBLIC_MODE === 'local'
const POLL_INTERVAL = 2000
const WS_RECONNECT_BASE = 1000
const WS_RECONNECT_MAX = 30000
const WS_CLOSE_AUTH = 4001
const WS_CLOSE_FORBIDDEN = 4003
const DEBOUNCE_MS = 300

// Rendered fields only: `updated_at` (and local-mode index bookkeeping) moves on every row write.
const IDENTITY_FIELDS: ReadonlyArray<keyof DocumentListItem> = [
  'id', 'filename', 'title', 'path', 'file_type', 'status', 'archived',
  'tags', 'date', 'metadata', 'version', 'document_number', 'error_message', 'page_count',
]

// Key-order-insensitive: jsonb re-sorts keys, so an optimistic metadata write echoes back reordered.
function isJsonEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true
  if (typeof a !== 'object' || typeof b !== 'object' || a === null || b === null) return false
  if (Array.isArray(a) !== Array.isArray(b)) return false
  const aRecord = a as Record<string, unknown>
  const bRecord = b as Record<string, unknown>
  const aKeys = Object.keys(aRecord)
  if (aKeys.length !== Object.keys(bRecord).length) return false
  return aKeys.every((key) => key in bRecord && isJsonEqual(aRecord[key], bRecord[key]))
}

function shallowEqualForIdentity(a: DocumentListItem, b: DocumentListItem): boolean {
  return IDENTITY_FIELDS.every((field) => isJsonEqual(a[field], b[field]))
}

function mergePreservingIdentity(
  prev: DocumentListItem[],
  next: DocumentListItem[],
): DocumentListItem[] {
  if (prev.length === 0) return next
  const prevById = new Map(prev.map((d) => [d.id, d]))
  let allSame = prev.length === next.length
  const merged = next.map((nextDoc, i) => {
    const prevDoc = prevById.get(nextDoc.id)
    const result = prevDoc && shallowEqualForIdentity(prevDoc, nextDoc) ? prevDoc : nextDoc
    if (result !== prev[i]) allSame = false
    return result
  })
  return allSame ? prev : merged
}

export function useKBDocuments(knowledgeBaseId: string) {
  const [documents, setDocuments] = React.useState<DocumentListItem[]>([])
  const [loading, setLoading] = React.useState(true)
  const [loadError, setLoadError] = React.useState<string | null>(null)
  const accessToken = useUserStore((s) => s.accessToken)
  const wsRef = React.useRef<WebSocket | null>(null)
  const reconnectTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null)
  const reconnectDelay = React.useRef(WS_RECONNECT_BASE)
  const debounceTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null)

  const fetchDocs = React.useCallback(async () => {
    if (!knowledgeBaseId || !accessToken) return
    try {
      const data = await apiFetch<DocumentListItem[]>(
        `/v1/knowledge-bases/${knowledgeBaseId}/documents`,
        accessToken,
      )
      setDocuments((prev) => mergePreservingIdentity(prev, data))
      setLoadError(null)
    } catch (err) {
      console.error('Failed to load documents:', err)
      setLoadError(err instanceof Error ? err.message : 'Failed to load documents')
    }
  }, [knowledgeBaseId, accessToken])

  // Only a KB change resets `loading`; token refreshes revalidate in the background without blanking the wiki.
  React.useEffect(() => {
    if (!knowledgeBaseId) {
      setDocuments([])
      setLoading(false)
      return
    }

    setDocuments([])
    setLoadError(null)
    setLoading(true)
  }, [knowledgeBaseId])

  React.useEffect(() => {
    if (!knowledgeBaseId || !accessToken) return

    let cancelled = false
    fetchDocs().finally(() => {
      if (!cancelled) setLoading(false)
    })

    return () => {
      cancelled = true
    }
  }, [knowledgeBaseId, accessToken, fetchDocs])

  React.useEffect(() => {
    if (!knowledgeBaseId || !accessToken) return

    if (isLocal) {
      const interval = setInterval(fetchDocs, POLL_INTERVAL)
      return () => clearInterval(interval)
    }

    let cancelled = false

    function connect() {
      if (cancelled) return

      const url = getDocumentsWsUrl(knowledgeBaseId)
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        // Token as first message keeps the JWT out of URLs and logs.
        ws.send(accessToken!)
        reconnectDelay.current = WS_RECONNECT_BASE
      }

      ws.onmessage = () => {
        if (process.env.NODE_ENV === 'development') {
          console.count(`documents ws message:${knowledgeBaseId}`)
        }
        // OCR updates can fire many events in quick succession.
        if (debounceTimer.current) clearTimeout(debounceTimer.current)
        debounceTimer.current = setTimeout(fetchDocs, DEBOUNCE_MS)
      }

      ws.onclose = (e) => {
        wsRef.current = null
        if (cancelled) return
        // Usually a token that expired while the tab was open; the refreshed accessToken recreates the socket.
        if (e.code === WS_CLOSE_AUTH) {
          console.warn('WebSocket auth failed; refreshing token:', e.reason)
          refreshAccessToken(accessToken!).catch((err) => {
            console.error('Token refresh after WebSocket auth failure failed:', err)
          })
          return
        }
        if (e.code === WS_CLOSE_FORBIDDEN) {
          console.warn('WebSocket subscription forbidden; stopping reconnect:', e.reason)
          return
        }
        const delay = reconnectDelay.current
        reconnectDelay.current = Math.min(delay * 2, WS_RECONNECT_MAX)
        reconnectTimer.current = setTimeout(connect, delay)
      }

      ws.onerror = () => {
        // onclose follows and handles reconnection.
      }
    }

    connect()

    return () => {
      cancelled = true
      if (debounceTimer.current) clearTimeout(debounceTimer.current)
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
      if (wsRef.current) {
        wsRef.current.onclose = null
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [knowledgeBaseId, accessToken, fetchDocs])

  const refetchDocuments = React.useCallback(() => {
    fetchDocs()
  }, [fetchDocs])

  return { documents, setDocuments, loading, loadError, refetchDocuments }
}
