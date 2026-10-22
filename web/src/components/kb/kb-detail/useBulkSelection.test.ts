import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { DocumentListItem } from '@/lib/types'
import { useUserStore } from '@/stores/useUserStore'
import { computeNextSelection, useBulkSelection } from './useBulkSelection'

const VISIBLE = ['a', 'b', 'c', 'd', 'e']
const fetchMock = vi.fn<typeof fetch>()

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  useUserStore.setState({ accessToken: 'token' })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('computeNextSelection', () => {
  it('toggles a single id on and off', () => {
    const added = computeNextSelection(new Set(['a']), 'c', 'a', 'toggle', VISIBLE)
    expect([...added]).toEqual(['a', 'c'])
    expect([...computeNextSelection(added, 'a', 'c', 'toggle', VISIBLE)]).toEqual(['c'])
  })

  it('adds the visible-order range between anchor and target, in either direction', () => {
    expect([...computeNextSelection(new Set(['b']), 'd', 'b', 'range', VISIBLE)].sort()).toEqual(['b', 'c', 'd'])
    expect([...computeNextSelection(new Set(['e']), 'c', 'e', 'range', VISIBLE)].sort()).toEqual(['c', 'd', 'e'])
  })

  it('keeps earlier picks when extending with a range', () => {
    expect([...computeNextSelection(new Set(['a', 'd']), 'e', 'd', 'range', VISIBLE)].sort()).toEqual(['a', 'd', 'e'])
  })

  it('selects only the target when there is no visible anchor', () => {
    expect([...computeNextSelection(new Set(), 'c', null, 'range', VISIBLE)]).toEqual(['c'])
    expect([...computeNextSelection(new Set(['x']), 'c', 'x', 'range', VISIBLE)].sort()).toEqual(['c', 'x'])
  })
})

describe('useBulkSelection', () => {
  it('ranges from the last clicked document', () => {
    const { result } = renderHook(() => useBulkSelection(vi.fn()))
    act(() => result.current.selectDocument('b', 'toggle', VISIBLE))
    act(() => result.current.selectDocument('d', 'range', VISIBLE))
    expect([...result.current.selectedIds].sort()).toEqual(['b', 'c', 'd'])
  })

  it('deletes every selected document with one bulk request and drops them locally', async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }))
    let documents = [{ id: 'a' }, { id: 'b' }, { id: 'c' }] as DocumentListItem[]
    const setDocuments = vi.fn((update: React.SetStateAction<DocumentListItem[]>) => {
      documents = typeof update === 'function' ? update(documents) : update
    })
    const { result } = renderHook(() => useBulkSelection(setDocuments))
    act(() => result.current.selectDocument('a', 'toggle', VISIBLE))
    act(() => result.current.selectDocument('b', 'toggle', VISIBLE))

    await act(() => result.current.deleteSelected())

    expect(fetchMock).toHaveBeenCalledOnce()
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toMatch(/\/v1\/documents\/bulk-delete$/)
    expect(init?.method).toBe('POST')
    expect(JSON.parse(String(init?.body))).toEqual({ ids: ['a', 'b'] })
    expect(documents.map((d) => d.id)).toEqual(['c'])
    expect(result.current.selectedIds.size).toBe(0)
  })

  it('keeps the selection and documents when the bulk request fails', async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'nope' }), { status: 500 }))
    const setDocuments = vi.fn()
    const { result } = renderHook(() => useBulkSelection(setDocuments))
    act(() => result.current.selectDocument('a', 'toggle', VISIBLE))

    await act(() => result.current.deleteSelected())

    expect(setDocuments).not.toHaveBeenCalled()
    expect([...result.current.selectedIds]).toEqual(['a'])
    expect(result.current.bulkDeleting).toBe(false)
  })

  it('drops a deleted batch from the selection when a later batch fails', async () => {
    fetchMock
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'nope' }), { status: 500 }))
    const ids = Array.from({ length: 150 }, (_, i) => `doc-${i}`)
    const { result } = renderHook(() => useBulkSelection(vi.fn()))
    act(() => ids.forEach((id) => result.current.selectDocument(id, 'toggle', ids)))

    await act(() => result.current.deleteSelected())

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect([...result.current.selectedIds]).toEqual(ids.slice(100))
  })
})
