'use client'

import * as React from 'react'
import { toast } from 'sonner'
import { apiFetch } from '@/lib/api'
import { useUserStore } from '@/stores'
import type { DocumentListItem } from '@/lib/types'

const isLocal = process.env.NEXT_PUBLIC_MODE === 'local'
const POLL_INTERVAL = 2000

export function useKBDocuments(knowledgeBaseId: string) {
  const [documents, setDocuments] = React.useState<DocumentListItem[]>([])
  const [loading, setLoading] = React.useState(true)
  const accessToken = useUserStore((s) => s.accessToken)

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

  // Initial load
  React.useEffect(() => {
    if (!knowledgeBaseId) {
      setDocuments([])
      setLoading(false)
      return
    }

    if (isLocal) {
      // Local mode: fetch from API
      setLoading(true)
      fetchDocs().finally(() => setLoading(false))
      return
    }

    // Hosted mode: fetch from Supabase directly
    let cancelled = false
    setLoading(true)

    import('@/lib/supabase/client').then(({ createClient }) => {
      const supabase = createClient()
      supabase
        .from('documents')
        .select('*')
        .eq('knowledge_base_id', knowledgeBaseId)
        .order('created_at', { ascending: false })
        .then(({ data, error }) => {
          if (cancelled) return
          if (error) {
            console.error('Failed to load documents:', error)
            toast.error('Failed to load documents')
            setDocuments([])
          } else {
            setDocuments((data as DocumentListItem[]) ?? [])
          }
          setLoading(false)
        })
    })

    return () => { cancelled = true }
  }, [knowledgeBaseId, fetchDocs])

  // Polling (local mode) or realtime (hosted mode)
  React.useEffect(() => {
    if (!knowledgeBaseId) return

    if (isLocal) {
      // Poll every 2s
      const interval = setInterval(fetchDocs, POLL_INTERVAL)
      return () => clearInterval(interval)
    }

    // Hosted mode: Supabase realtime
    let channel: ReturnType<ReturnType<typeof import('@/lib/supabase/client').createClient>['channel']> | null = null
    let cancelled = false

    import('@/lib/supabase/client').then(({ createClient }) => {
      if (cancelled) return
      const supabase = createClient()

      const fetchDoc = async (id: string): Promise<DocumentListItem | null> => {
        const { data } = await supabase
          .from('documents')
          .select('*')
          .eq('id', id)
          .single()
        return data as DocumentListItem | null
      }

      channel = supabase
        .channel(`documents:${knowledgeBaseId}`)
        .on(
          'postgres_changes',
          { event: '*', schema: 'public', table: 'documents', filter: `knowledge_base_id=eq.${knowledgeBaseId}` },
          async (payload) => {
            if (payload.eventType === 'INSERT') {
              const id = (payload.new as { id: string }).id
              const item = await fetchDoc(id)
              if (!item) return
              setDocuments((prev) => {
                if (prev.some((d) => d.id === item.id)) return prev
                return [item, ...prev]
              })
            } else if (payload.eventType === 'UPDATE') {
              const id = (payload.new as { id: string }).id
              const item = await fetchDoc(id)
              if (!item) return
              setDocuments((prev) => prev.map((d) => d.id === item.id ? item : d))
            } else if (payload.eventType === 'DELETE') {
              const id = (payload.old as { id: string }).id
              setDocuments((prev) => prev.filter((d) => d.id !== id))
            }
          }
        )
        .subscribe()
    })

    return () => {
      cancelled = true
      if (channel) {
        import('@/lib/supabase/client').then(({ createClient }) => {
          createClient().removeChannel(channel!)
        })
      }
    }
  }, [knowledgeBaseId, fetchDocs])

  const refetchDocuments = React.useCallback(() => {
    fetchDocs()
  }, [fetchDocs])

  return { documents, setDocuments, loading, refetchDocuments }
}
