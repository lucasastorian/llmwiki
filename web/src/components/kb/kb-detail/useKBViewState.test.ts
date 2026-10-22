import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { DocumentListItem } from '@/lib/types'
import { useKBViewState } from './useKBViewState'

let currentSearch = ''

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(currentSearch),
}))

function wikiDoc(filename: string, documentNumber: number): DocumentListItem {
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
    document_number: documentNumber,
    sort_order: null,
    archived: false,
    created_at: '2026-08-10T00:00:00.000Z',
    updated_at: '2026-08-10T00:00:00.000Z',
  }
}

function setUrl(search: string): void {
  currentSearch = search
  window.history.replaceState(null, '', `/wikis/kb${search}`)
}

beforeEach(() => setUrl(''))
afterEach(() => cleanup())

describe('useKBViewState', () => {
  it('opens the wiki page named by ?p= once documents load', () => {
    setUrl('?p=1')
    const { result, rerender } = renderHook(
      ({ docs }) => useKBViewState('kb', 'wiki', docs),
      { initialProps: { docs: [] as DocumentListItem[] } },
    )
    expect(result.current.wikiActivePath).toBeNull()

    rerender({ docs: [wikiDoc('a.md', 1), wikiDoc('b.md', 2)] })
    expect(result.current.wikiActivePath).toBe('a.md')
  })

  it('does not snap back to the ?p= page when documents churn after the user navigated', () => {
    setUrl('?p=1')
    const docs = [wikiDoc('a.md', 1), wikiDoc('b.md', 2)]
    const { result, rerender } = renderHook(
      ({ docs }) => useKBViewState('kb', 'wiki', docs),
      { initialProps: { docs } },
    )
    expect(result.current.wikiActivePath).toBe('a.md')

    act(() => result.current.setWikiActivePath('b.md'))
    rerender({ docs: docs.map((d) => ({ ...d, version: d.version + 1 })) })

    expect(result.current.wikiActivePath).toBe('b.md')
  })

  it('ignores a ?p= value that useSearchParams still reports after the URL moved on', () => {
    setUrl('?p=1')
    const docs = [wikiDoc('a.md', 1), wikiDoc('b.md', 2)]
    const { result, rerender } = renderHook(
      ({ docs }) => useKBViewState('kb', 'wiki', docs),
      { initialProps: { docs: [] as DocumentListItem[] } },
    )

    window.history.replaceState(null, '', '/wikis/kb?p=2')
    rerender({ docs })

    expect(result.current.wikiActivePath).toBeNull()
  })

  it('opens the mount-time ?doc= source document once documents load', () => {
    setUrl('?doc=2')
    const { result, rerender } = renderHook(
      ({ docs }) => useKBViewState('kb', 'files', docs),
      { initialProps: { docs: [] as DocumentListItem[] } },
    )
    expect(result.current.activeSourceDocId).toBeNull()

    rerender({ docs: [wikiDoc('a.md', 1), wikiDoc('b.md', 2)] })
    expect(result.current.activeSourceDocId).toBe('id-b.md')
    expect(result.current.activeView).toBe('doc')
  })

  it('follows the open page when it is renamed', () => {
    setUrl('?p=1')
    const { result, rerender } = renderHook(
      ({ docs }) => useKBViewState('kb', 'wiki', docs),
      { initialProps: { docs: [wikiDoc('a.md', 1)] } },
    )
    expect(result.current.wikiActivePath).toBe('a.md')

    rerender({ docs: [{ ...wikiDoc('a.md', 1), filename: 'renamed.md' }] })

    expect(result.current.wikiActivePath).toBe('renamed.md')
  })

  it('lets a ?p= change win over unrelated document churn in the same render', () => {
    setUrl('?p=1')
    const docs = [wikiDoc('a.md', 1), wikiDoc('b.md', 2)]
    const { result, rerender } = renderHook(
      ({ docs }) => useKBViewState('kb', 'wiki', docs),
      { initialProps: { docs } },
    )
    expect(result.current.wikiActivePath).toBe('a.md')

    setUrl('?p=2')
    rerender({ docs: docs.map((d) => ({ ...d, version: d.version + 1 })) })

    expect(result.current.wikiActivePath).toBe('b.md')
  })
})
