import { create } from 'zustand'
import { apiFetch } from '@/lib/api'
import { useUserStore } from './useUserStore'
import type { KnowledgeBase } from '@/lib/types'

type KBState = {
  knowledgeBases: KnowledgeBase[]
  loading: boolean
  error: string | null
  fetchKBs: () => Promise<KnowledgeBase[]>
  createKB: (name: string, description?: string) => Promise<KnowledgeBase>
  deleteKB: (id: string) => Promise<void>
  renameKB: (id: string, name: string) => Promise<void>
}

function getToken(): string {
  const token = useUserStore.getState().accessToken
  if (!token) throw new Error('Not authenticated')
  return token
}

export const useKBStore = create<KBState>((set, get) => ({
  knowledgeBases: [],
  loading: true,
  error: null,

  fetchKBs: async () => {
    set({ loading: true, error: null })
    try {
      const token = getToken()
      const data = await apiFetch<KnowledgeBase[]>('/v1/knowledge-bases', token)
      set({ knowledgeBases: data, loading: false })
      return data
    } catch (err) {
      set({ error: (err as Error).message, loading: false })
      return []
    }
  },

  createKB: async (name: string, description?: string) => {
    const token = getToken()
    const kb = await apiFetch<KnowledgeBase>('/v1/knowledge-bases', token, {
      method: 'POST',
      body: JSON.stringify({ name, description: description || undefined }),
    })
    // Dedupe: in local mode the backend returns the existing singleton
    const existing = get().knowledgeBases
    if (existing.some((k) => k.id === kb.id)) {
      set({ knowledgeBases: existing.map((k) => k.id === kb.id ? kb : k) })
    } else {
      set({ knowledgeBases: [kb, ...existing] })
    }
    return kb
  },

  deleteKB: async (id: string) => {
    const token = getToken()
    await apiFetch(`/v1/knowledge-bases/${id}`, token, { method: 'DELETE' })
    set({ knowledgeBases: get().knowledgeBases.filter((kb) => kb.id !== id) })
  },

  renameKB: async (id: string, name: string) => {
    const token = getToken()
    const updated = await apiFetch<KnowledgeBase>(`/v1/knowledge-bases/${id}`, token, {
      method: 'PATCH',
      body: JSON.stringify({ name }),
    })
    set({
      knowledgeBases: get().knowledgeBases.map((kb) => (kb.id === id ? updated : kb)),
    })
  },
}))
