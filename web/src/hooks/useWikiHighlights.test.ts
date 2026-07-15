import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiFetch } from '@/lib/api'
import { useUserStore } from '@/stores'
import { useWikiHighlights } from './useWikiHighlights'
import type { Highlight, HighlightsResponse, TextAnchor } from '@/lib/highlights/types'

vi.mock('@/lib/api', () => ({ apiFetch: vi.fn() }))

const apiFetchMock = vi.mocked(apiFetch)

interface Deferred {
  promise: Promise<unknown>
  resolve: (value: unknown) => void
  reject: (reason: unknown) => void
}

function deferred(): Deferred {
  let resolve!: (value: unknown) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function anchor(text: string): TextAnchor {
  return { textStart: 0, textEnd: text.length, textContent: text }
}

function highlight(id: string, comment: string | null): Highlight {
  return {
    id,
    type: 'text',
    anchor: null,
    textAnchor: anchor('quoted text'),
    comment,
    color: 'yellow',
    createdAt: '2026-07-09T00:00:00.000Z',
  }
}

function response(id: string, version: number, highlights: Highlight[]): HighlightsResponse {
  return { id, version, highlights }
}

async function mountHook(docId: string, initial: HighlightsResponse) {
  apiFetchMock.mockResolvedValueOnce(initial)
  const rendered = renderHook(() => useWikiHighlights(docId))
  await waitFor(() => expect(rendered.result.current.highlights).toEqual(initial.highlights))
  return rendered
}

beforeEach(() => {
  apiFetchMock.mockReset()
  useUserStore.setState({ accessToken: 'test-token' })
})

describe('useWikiHighlights', () => {
  it('paints a new highlight optimistically before the server responds', async () => {
    const { result } = await mountHook('doc-add', response('doc-add', 1, []))

    const save = deferred()
    apiFetchMock.mockReturnValueOnce(save.promise as Promise<never>)
    let savePromise!: Promise<void>
    act(() => {
      savePromise = result.current.saveHighlight(anchor('hello'), 'a note')
    })

    expect(result.current.highlights).toHaveLength(1)
    expect(result.current.highlights[0].comment).toBe('a note')

    const saved = result.current.highlights[0]
    await act(async () => {
      save.resolve(response('doc-add', 2, [saved]))
      await savePromise
    })
    expect(result.current.highlights).toEqual([saved])
  })

  it('rolls back an optimistic save when the request fails', async () => {
    const { result } = await mountHook('doc-fail', response('doc-fail', 1, []))

    const save = deferred()
    apiFetchMock.mockReturnValueOnce(save.promise as Promise<never>)
    let savePromise!: Promise<void>
    act(() => {
      savePromise = result.current.saveHighlight(anchor('hello'), null)
    })
    expect(result.current.highlights).toHaveLength(1)

    await act(async () => {
      save.reject(new Error('network down'))
      await expect(savePromise).rejects.toThrow('network down')
    })
    expect(result.current.highlights).toHaveLength(0)
  })

  it('drops out-of-order responses via the version guard', async () => {
    const h = highlight('h1', 'A')
    const { result } = await mountHook('doc-order', response('doc-order', 1, [h]))

    const first = deferred()
    const second = deferred()
    apiFetchMock.mockReturnValueOnce(first.promise as Promise<never>)
    apiFetchMock.mockReturnValueOnce(second.promise as Promise<never>)

    let firstPromise!: Promise<void>
    let secondPromise!: Promise<void>
    act(() => {
      firstPromise = result.current.updateComment('h1', 'B')
    })
    act(() => {
      secondPromise = result.current.updateComment('h1', 'C')
    })

    // The newer write's response lands first; the older one must not clobber it.
    await act(async () => {
      second.resolve(response('doc-order', 3, [highlight('h1', 'C')]))
      await secondPromise
    })
    await act(async () => {
      first.resolve(response('doc-order', 2, [highlight('h1', 'B')]))
      await firstPromise
    })
    expect(result.current.highlights[0].comment).toBe('C')
  })

  it('does not restore stale state when a failed edit was superseded', async () => {
    const h = highlight('h1', 'A')
    const { result } = await mountHook('doc-restore', response('doc-restore', 1, [h]))

    const first = deferred()
    const second = deferred()
    apiFetchMock.mockReturnValueOnce(first.promise as Promise<never>)
    apiFetchMock.mockReturnValueOnce(second.promise as Promise<never>)

    let firstPromise!: Promise<void>
    let secondPromise!: Promise<void>
    act(() => {
      firstPromise = result.current.updateComment('h1', 'B')
    })
    act(() => {
      secondPromise = result.current.updateComment('h1', 'C')
    })

    await act(async () => {
      second.resolve(response('doc-restore', 2, [highlight('h1', 'C')]))
      await secondPromise
    })
    // The A→B write fails after B→C already succeeded; rollback must not revive A.
    await act(async () => {
      first.reject(new Error('timeout'))
      await expect(firstPromise).rejects.toThrow('timeout')
    })
    expect(result.current.highlights[0].comment).toBe('C')
  })

  it('issues a single fetch on mount even when remoteVersion is provided', async () => {
    apiFetchMock.mockResolvedValueOnce(response('doc-single', 3, []))
    const { result } = renderHook(() => useWikiHighlights('doc-single', 3))
    await waitFor(() => expect(result.current.highlights).toEqual([]))
    expect(apiFetchMock).toHaveBeenCalledTimes(1)
  })

  it('drops a stale initial response that loses the race against a write', async () => {
    const initial = deferred()
    apiFetchMock.mockReturnValueOnce(initial.promise as Promise<never>)
    const { result } = renderHook(() => useWikiHighlights('doc-race'))

    const save = deferred()
    apiFetchMock.mockReturnValueOnce(save.promise as Promise<never>)
    let savePromise!: Promise<void>
    act(() => {
      savePromise = result.current.saveHighlight(anchor('hello'), 'note')
    })
    const saved = result.current.highlights[0]
    await act(async () => {
      save.resolve(response('doc-race', 2, [saved]))
      await savePromise
    })

    // The pre-save initial snapshot arrives last; it must not wipe the write.
    await act(async () => {
      initial.resolve(response('doc-race', 1, []))
    })
    expect(result.current.highlights).toEqual([saved])
  })

  it('restores a removed highlight when the delete fails', async () => {
    const h = highlight('h1', 'keep me')
    const { result } = await mountHook('doc-del', response('doc-del', 1, [h]))

    const del = deferred()
    apiFetchMock.mockReturnValueOnce(del.promise as Promise<never>)
    let deletePromise!: Promise<void>
    act(() => {
      deletePromise = result.current.removeHighlight('h1')
    })
    expect(result.current.highlights).toHaveLength(0)

    await act(async () => {
      del.reject(new Error('offline'))
      await expect(deletePromise).rejects.toThrow('offline')
    })
    expect(result.current.highlights).toEqual([h])
  })
})
