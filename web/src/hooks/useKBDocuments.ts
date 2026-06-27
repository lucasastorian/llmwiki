'use client'

import * as React from 'react'
import { toast } from 'sonner'
import { apiFetch, getDocumentsWsUrl } from '@/lib/api'
import { refreshAccessToken } from '@/lib/auth-token'
import { useUserStore } from '@/stores'
import type { DocumentListItem } from '@/lib/types'

const isLocal = process.env.NEXT_PUBLIC_MODE === 'local'
const POLL_INTERVAL = 2000
const WS_RECONNECT_BASE = 1000
const WS_RECONNECT_MAX = 30000
const DEBOUNCE_MS = 300

// Fields whose change we want to *force* a re-render through identity churn.
// `updated_at` is intentionally excluded — it bumps on every UPDATE (incl.
// highlight-only writes) and would otherwise unmount the active viewer.
const IDENTITY_FIELDS: ReadonlyArray<keyof DocumentListItem> = [
  'id', 'filename', 'title', 'path', 'file_type', 'status', 'archived',
  'tags', 'date', 'metadata', 'version', 'document_number', 'error_message',
]

function shallowEqualForIdentity(a: DocumentListItem, b: DocumentListItem): boolean {
  for (const k of IDENTITY_FIELDS) {
    const av = a[k]
    const bv = b[k]
    if (av === bv) continue
    // Arrays and dicts: fall back to JSON compare. Cheap for our row sizes
    // and avoids pulling in a deep-equal dependency.
    if (typeof av === 'object' || typeof bv === 'object') {
      if (JSON.stringify(av) !== JSON.stringify(bv)) return false
      continue
    }
    return false
  }
  return true
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
      // Preserve object identity for rows whose user-visible content hasn't
      // actually changed. Highlight saves bump `updated_at` (via the row's
      // UPDATE trigger) without changing any field we render in this list,
      // so without this merge the WS-triggered refetch would churn references
      // downstream and cause the active doc viewer to remount.
      setDocuments((prev) => mergePreservingIdentity(prev, data))
    } catch (err) {
      console.error('Failed to load documents:', err)
    }
  }, [knowledgeBaseId, accessToken])

  // Initial load — always use the API
  React.useEffect(() => {
    if (!knowledgeBaseId) {
      setDocuments([])
      setLoading(false)
      return
    }
    setLoading(true)
    fetchDocs().finally(() => setLoading(false))
  }, [knowledgeBaseId, fetchDocs])

  // Real-time updates: WebSocket (hosted) or polling (local)
  React.useEffect(() => {
    if (!knowledgeBaseId || !accessToken) return

    if (isLocal) {
      const interval = setInterval(fetchDocs, POLL_INTERVAL)
      return () => clearInterval(interval)
    }

    // Hosted mode — connect to API WebSocket
    let cancelled = false

    function connect() {
      if (cancelled) return

      const url = getDocumentsWsUrl(knowledgeBaseId)
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        // Send token as first message — keeps JWT out of URLs and logs
        ws.send(accessToken!)
        reconnectDelay.current = WS_RECONNECT_BASE
      }

      ws.onmessage = () => {
        if (process.env.NODE_ENV === 'development') {
          console.count(`documents ws message:${knowledgeBaseId}`)
        }
        // Debounce refetches — OCR updates can fire many events in quick succession
        if (debounceTimer.current) clearTimeout(debounceTimer.current)
        debounceTimer.current = setTimeout(fetchDocs, DEBOUNCE_MS)
      }

      ws.onclose = (e) => {
        wsRef.current = null
        if (cancelled) return
        // 4001 = auth failure. The common cause is a tab reconnecting with a
        // token that expired while the page was open; ask Supabase to refresh
        // and let the accessToken dependency recreate the socket.
        if (e.code === 4001) {
          console.warn('WebSocket auth failed; refreshing token:', e.reason)
          refreshAccessToken().catch((err) => {
            console.error('Token refresh after WebSocket auth failure failed:', err)
          })
          return
        }
        // Reconnect with exponential backoff
        const delay = reconnectDelay.current
        reconnectDelay.current = Math.min(delay * 2, WS_RECONNECT_MAX)
        reconnectTimer.current = setTimeout(connect, delay)
      }

      ws.onerror = () => {
        // onclose will fire after this, which handles reconnection
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

  return { documents, setDocuments, loading, refetchDocuments }
}
