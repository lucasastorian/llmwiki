'use client'

import * as React from 'react'
import { createClient } from '@/lib/supabase/client'
import { toast } from 'sonner'
import type { DocumentListItem } from '@/lib/types'

const DOC_LIST_COLUMNS = 'id, filename, title, file_type, file_size, status, path, tags, date, metadata, error_message, version, document_number, sort_order, archived, created_at, updated_at, knowledge_base_id, user_id, url, page_count'

export function useKBDocuments(knowledgeBaseId: string) {
  const [documents, setDocuments] = React.useState<DocumentListItem[]>([])
  const [loading, setLoading] = React.useState(true)
  const supabase = React.useMemo(() => createClient(), [])

  React.useEffect(() => {
    if (!knowledgeBaseId) {
      setDocuments([])
      setLoading(false)
      return
    }

    let cancelled = false
    setLoading(true)

    supabase
      .from('documents')
      .select(DOC_LIST_COLUMNS)
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

    return () => { cancelled = true }
  }, [knowledgeBaseId, supabase])

  React.useEffect(() => {
    if (!knowledgeBaseId) return

    const fetchDoc = async (id: string): Promise<DocumentListItem | null> => {
      const { data } = await supabase
        .from('documents')
        .select(DOC_LIST_COLUMNS)
        .eq('id', id)
        .single()
      return data as DocumentListItem | null
    }

    const channel = supabase
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

    return () => {
      supabase.removeChannel(channel)
    }
  }, [knowledgeBaseId, supabase])

  const refetchDocuments = React.useCallback(() => {
    supabase
      .from('documents')
      .select(DOC_LIST_COLUMNS)
      .eq('knowledge_base_id', knowledgeBaseId)
      .order('created_at', { ascending: false })
      .then(({ data }) => { if (data) setDocuments(data as DocumentListItem[]) })
  }, [knowledgeBaseId, supabase])

  return { documents, setDocuments, loading, refetchDocuments }
}
