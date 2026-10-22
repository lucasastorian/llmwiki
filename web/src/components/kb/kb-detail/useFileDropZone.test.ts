import type * as React from 'react'
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useFileDropZone } from './useFileDropZone'

function dragEvent(types: string[] = ['Files'], files: File[] = []): React.DragEvent {
  return {
    preventDefault: vi.fn(),
    dataTransfer: { types, files, dropEffect: 'none' },
  } as unknown as React.DragEvent
}

afterEach(() => cleanup())

describe('useFileDropZone', () => {
  it('stays highlighted across nested enter/leave pairs until the outermost leave', () => {
    const { result } = renderHook(() => useFileDropZone(false, vi.fn()))
    act(() => result.current.dropZoneProps.onDragEnter(dragEvent()))
    act(() => result.current.dropZoneProps.onDragEnter(dragEvent()))
    act(() => result.current.dropZoneProps.onDragLeave(dragEvent()))
    expect(result.current.isFileDragOver).toBe(true)

    act(() => result.current.dropZoneProps.onDragLeave(dragEvent()))
    expect(result.current.isFileDragOver).toBe(false)
  })

  it('hands dropped files to the callback and resets the highlight', () => {
    const onDropFiles = vi.fn()
    const file = new File(['x'], 'a.pdf')
    const { result } = renderHook(() => useFileDropZone(false, onDropFiles))
    act(() => result.current.dropZoneProps.onDragEnter(dragEvent()))
    act(() => result.current.dropZoneProps.onDrop(dragEvent(['Files'], [file])))

    expect(onDropFiles).toHaveBeenCalledWith([file])
    expect(result.current.isFileDragOver).toBe(false)
  })

  it('ignores in-app item drags', () => {
    const onDropFiles = vi.fn()
    const { result } = renderHook(() => useFileDropZone(false, onDropFiles))
    const internal = dragEvent(['application/x-llmwiki-item'], [new File(['x'], 'a.pdf')])
    act(() => result.current.dropZoneProps.onDragEnter(internal))
    act(() => result.current.dropZoneProps.onDrop(internal))

    expect(result.current.isFileDragOver).toBe(false)
    expect(onDropFiles).not.toHaveBeenCalled()
  })

  it('does nothing while disabled', () => {
    const onDropFiles = vi.fn()
    const { result } = renderHook(() => useFileDropZone(true, onDropFiles))
    const event = dragEvent(['Files'], [new File(['x'], 'a.pdf')])
    act(() => result.current.dropZoneProps.onDragEnter(event))
    act(() => result.current.dropZoneProps.onDrop(event))

    expect(event.preventDefault).not.toHaveBeenCalled()
    expect(onDropFiles).not.toHaveBeenCalled()
  })
})
