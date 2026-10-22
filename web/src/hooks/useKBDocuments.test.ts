import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiFetch } from '@/lib/api'
import { useUserStore } from '@/stores'
import type { DocumentListItem } from '@/lib/types'
import { useKBDocuments } from './useKBDocuments'

vi.mock('@/lib/api', () => ({
  apiFetch: vi.fn(),
  getDocumentsWsUrl: vi.fn(() => 'ws://example.test/documents'),
}))

vi.mock('@/lib/auth-token', () => ({
  refreshAccessToken: vi.fn(),
}))

const apiFetchMock = vi.mocked(apiFetch)

class FakeWebSocket {
  static latest: FakeWebSocket | null = null
  onopen: (() => void) | null = null
  onmessage: (() => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null
  onerror: (() => void) | null = null

  send = vi.fn()
  close = vi.fn()

  constructor() {
    FakeWebSocket.latest = this
  }
}

interface Deferred<T> {
  promise: Promise<T>
  resolve: (value: T) => void
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

async function deliverWsEventAndRefetch(response: DocumentListItem[]): Promise<void> {
  const callsBefore = apiFetchMock.mock.calls.length
  apiFetchMock.mockResolvedValueOnce(response)
  act(() => {
    FakeWebSocket.latest!.onmessage!()
  })
  await waitFor(() => expect(apiFetchMock).toHaveBeenCalledTimes(callsBefore + 1))
  await act(async () => {})
}

function documentItem(id: string, overrides: Partial<DocumentListItem> = {}): DocumentListItem {
  return {
    id,
    knowledge_base_id: 'kb-1',
    user_id: 'user-1',
    filename: `${id}.md`,
    title: id,
    path: `/wiki/${id}.md`,
    file_type: 'wiki',
    file_size: 100,
    status: 'completed',
    page_count: null,
    tags: [],
    date: null,
    metadata: null,
    error_message: null,
    url: null,
    version: 1,
    document_number: null,
    sort_order: null,
    archived: false,
    created_at: '2026-08-10T00:00:00.000Z',
    updated_at: '2026-08-10T00:00:00.000Z',
    ...overrides,
  }
}

beforeEach(() => {
  apiFetchMock.mockReset()
  vi.stubGlobal('WebSocket', FakeWebSocket)
  useUserStore.setState({ accessToken: 'token-1' })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('useKBDocuments', () => {
  it('keeps the current wiki visible while a refreshed token revalidates documents', async () => {
    const originalDocument = documentItem('overview')
    apiFetchMock.mockResolvedValueOnce([originalDocument])

    const { result } = renderHook(() => useKBDocuments('kb-1'))

    await waitFor(() => expect(result.current.loading).toBe(false))
    const originalDocuments = result.current.documents
    expect(originalDocuments).toEqual([originalDocument])

    const refresh = deferred<DocumentListItem[]>()
    apiFetchMock.mockReturnValueOnce(refresh.promise)

    act(() => {
      useUserStore.setState({ accessToken: 'token-2' })
    })

    expect(result.current.loading).toBe(false)
    expect(result.current.documents).toBe(originalDocuments)

    await act(async () => {
      refresh.resolve([
        documentItem('overview', { updated_at: '2026-08-10T01:00:00.000Z' }),
      ])
      await refresh.promise
    })

    expect(result.current.loading).toBe(false)
    expect(result.current.documents).toBe(originalDocuments)
    expect(apiFetchMock).toHaveBeenLastCalledWith(
      '/v1/knowledge-bases/kb-1/documents',
      'token-2',
    )
  })

  it('still blocks and clears stale documents when switching to another wiki', async () => {
    apiFetchMock.mockResolvedValueOnce([documentItem('overview')])
    const nextWiki = deferred<DocumentListItem[]>()

    const { result, rerender } = renderHook(
      ({ knowledgeBaseId }) => useKBDocuments(knowledgeBaseId),
      { initialProps: { knowledgeBaseId: 'kb-1' } },
    )

    await waitFor(() => expect(result.current.loading).toBe(false))
    apiFetchMock.mockReturnValueOnce(nextWiki.promise)

    rerender({ knowledgeBaseId: 'kb-2' })

    expect(result.current.loading).toBe(true)
    expect(result.current.documents).toEqual([])

    await act(async () => {
      nextWiki.resolve([
        documentItem('start', { knowledge_base_id: 'kb-2' }),
      ])
      await nextWiki.promise
    })

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.documents[0].knowledge_base_id).toBe('kb-2')
  })

  it('reports a failed load instead of looking like an empty wiki, and recovers on retry', async () => {
    apiFetchMock.mockRejectedValueOnce(new Error('503 Service Unavailable'))
    const { result } = renderHook(() => useKBDocuments('kb-1'))
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.loadError).toBe('503 Service Unavailable')
    expect(result.current.documents).toEqual([])

    apiFetchMock.mockResolvedValueOnce([documentItem('overview')])
    await act(async () => {
      result.current.refetchDocuments()
    })

    await waitFor(() => expect(result.current.loadError).toBeNull())
    expect(result.current.documents).toHaveLength(1)
  })

  it('keeps document identity when a websocket refetch echoes optimistic metadata with jsonb key order', async () => {
    apiFetchMock.mockResolvedValueOnce([
      documentItem('lesson', { metadata: { source_url: 'https://example.test' } }),
    ])
    const { result } = renderHook(() => useKBDocuments('kb-1'))
    await waitFor(() => expect(result.current.loading).toBe(false))

    const course = { status: 'complete', completed_at: '2026-08-10T02:00:00.000Z' }
    act(() => {
      result.current.setDocuments((prev) => prev.map((d) => ({
        ...d, metadata: { ...d.metadata, course },
      })))
    })
    const optimisticDocuments = result.current.documents

    await deliverWsEventAndRefetch([
      documentItem('lesson', {
        metadata: { course, source_url: 'https://example.test' },
        updated_at: '2026-08-10T02:00:01.000Z',
      }),
    ])

    expect(result.current.documents).toBe(optimisticDocuments)
  })

  it('replaces only the changed document when a websocket event changes its page count', async () => {
    apiFetchMock.mockResolvedValueOnce([
      documentItem('paper', { file_type: 'pdf', page_count: null }),
      documentItem('overview'),
    ])
    const { result } = renderHook(() => useKBDocuments('kb-1'))
    await waitFor(() => expect(result.current.loading).toBe(false))
    const [paper, overview] = result.current.documents

    await deliverWsEventAndRefetch([
      documentItem('paper', { file_type: 'pdf', page_count: 12 }),
      documentItem('overview'),
    ])

    expect(result.current.documents[0]).not.toBe(paper)
    expect(result.current.documents[0].page_count).toBe(12)
    expect(result.current.documents[1]).toBe(overview)
  })
})
