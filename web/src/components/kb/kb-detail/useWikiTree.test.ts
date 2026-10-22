import { cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiFetch } from '@/lib/api'
import type { DocumentListItem } from '@/lib/types'
import { useWikiTree } from './useWikiTree'

vi.mock('@/lib/api', () => ({ apiFetch: vi.fn() }))

const apiFetchMock = vi.mocked(apiFetch)

function wikiDoc(filename: string, overrides: Partial<DocumentListItem> = {}): DocumentListItem {
  return {
    id: `id-${filename}`,
    knowledge_base_id: 'kb-1',
    user_id: 'user-1',
    filename,
    title: filename,
    path: '/wiki/',
    file_type: 'md',
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

const indexContent = JSON.stringify({ tree: [{ title: 'Page', path: 'page.md' }] })

beforeEach(() => {
  apiFetchMock.mockReset()
  apiFetchMock.mockResolvedValue({ content: indexContent })
})
afterEach(() => cleanup())

describe('useWikiTree', () => {
  it('builds the tree from index.json, enriched with doc numbers', async () => {
    const docs = [wikiDoc('index.json'), wikiDoc('page.md', { document_number: 4 })]
    const { result } = renderHook(() => useWikiTree(docs, 'token'))
    await waitFor(() => expect(result.current.indexLoaded).toBe(true))
    expect(result.current.wikiTree).toEqual([{ title: 'Page', path: 'page.md', docNumber: 4, children: undefined }])
    expect(result.current.hasNavigableWiki).toBe(true)
  })

  it('does not refetch index.json when only a page version changes', async () => {
    const docs = [wikiDoc('index.json'), wikiDoc('page.md', { document_number: 4 })]
    const { result, rerender } = renderHook(({ docs }) => useWikiTree(docs, 'token'), { initialProps: { docs } })
    await waitFor(() => expect(result.current.indexLoaded).toBe(true))

    rerender({ docs: docs.map((d) => (d.filename === 'page.md' ? { ...d, version: 2 } : d)) })

    expect(apiFetchMock).toHaveBeenCalledTimes(1)
    expect(result.current.indexLoaded).toBe(true)
  })

  it('refetches index.json when a page is renamed', async () => {
    const docs = [wikiDoc('index.json'), wikiDoc('page.md', { document_number: 4 })]
    const { result, rerender } = renderHook(({ docs }) => useWikiTree(docs, 'token'), { initialProps: { docs } })
    await waitFor(() => expect(result.current.indexLoaded).toBe(true))

    rerender({ docs: docs.map((d) => (d.filename === 'page.md' ? { ...d, title: 'Renamed' } : d)) })

    await waitFor(() => expect(apiFetchMock).toHaveBeenCalledTimes(2))
  })

  it('drops index.json entries whose page no longer exists', async () => {
    apiFetchMock.mockResolvedValue({
      content: JSON.stringify({ tree: [{ title: 'Page', path: 'page.md' }, { title: 'Deleted', path: 'deleted.md' }] }),
    })
    const docs = [wikiDoc('index.json'), wikiDoc('page.md', { document_number: 4 })]
    const { result } = renderHook(() => useWikiTree(docs, 'token'))
    await waitFor(() => expect(result.current.indexLoaded).toBe(true))
    expect(result.current.wikiTree.map((n) => n.path)).toEqual(['page.md'])
  })

  it('falls back to a doc-derived tree when index.json is unparseable', async () => {
    apiFetchMock.mockResolvedValue({ content: 'not json' })
    const docs = [wikiDoc('index.json'), wikiDoc('page.md', { title: 'Page', document_number: 4 })]
    const { result } = renderHook(() => useWikiTree(docs, 'token'))
    await waitFor(() => expect(result.current.indexLoaded).toBe(true))
    expect(result.current.wikiTree).toEqual([{ title: 'Page', path: 'page.md', docNumber: 4 }])
  })
})
