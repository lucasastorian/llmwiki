'use client'

import * as React from 'react'
import { toast } from 'sonner'
import { apiFetch, getDocumentsWsUrl } from '@/lib/api'
import { useUserStore } from '@/stores'
import type { DocumentListItem } from '@/lib/types'

const isLocal = process.env.NEXT_PUBLIC_MODE === 'local'
const POLL_INTERVAL = 2000
const WS_RECONNECT_BASE = 1000
const WS_RECONNECT_MAX = 30000
const DEBOUNCE_MS = 300

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
      setDocuments(data)
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
        // Debounce refetches — OCR updates can fire many events in quick succession
        if (debounceTimer.current) clearTimeout(debounceTimer.current)
        debounceTimer.current = setTimeout(fetchDocs, DEBOUNCE_MS)
      }

      ws.onclose = (e) => {
        wsRef.current = null
        if (cancelled) return
        // 4001 = auth failure, don't reconnect
        if (e.code === 4001) {
          console.error('WebSocket auth failed:', e.reason)
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
