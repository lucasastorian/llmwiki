import * as React from 'react'

const INTERNAL_DRAG_TYPE = 'application/x-llmwiki-item'

export interface FileDropZone {
  isFileDragOver: boolean
  dropZoneProps: {
    onDragEnter: (e: React.DragEvent) => void
    onDragLeave: (e: React.DragEvent) => void
    onDragOver: (e: React.DragEvent) => void
    onDrop: (e: React.DragEvent) => void
  }
}

/** Whole-pane OS file drop target; inert while disabled and ignores in-app item drags. */
export function useFileDropZone(isDisabled: boolean, onDropFiles: (files: File[]) => void): FileDropZone {
  const [isFileDragOver, setIsFileDragOver] = React.useState(false)
  const dragCounterRef = React.useRef(0)

  const onDragEnter = (e: React.DragEvent): void => {
    if (isDisabled || isInternalDrag(e)) return
    e.preventDefault()
    dragCounterRef.current++
    if (dragCounterRef.current === 1) setIsFileDragOver(true)
  }

  const onDragLeave = (e: React.DragEvent): void => {
    if (isDisabled) return
    e.preventDefault()
    dragCounterRef.current--
    if (dragCounterRef.current === 0) setIsFileDragOver(false)
  }

  const onDragOver = (e: React.DragEvent): void => {
    if (isDisabled || isInternalDrag(e)) return
    e.preventDefault()
    e.dataTransfer.dropEffect = 'copy'
  }

  const onDrop = (e: React.DragEvent): void => {
    if (isDisabled || isInternalDrag(e)) return
    e.preventDefault()
    dragCounterRef.current = 0
    setIsFileDragOver(false)
    const files = Array.from(e.dataTransfer.files)
    if (files.length > 0) onDropFiles(files)
  }

  return { isFileDragOver, dropZoneProps: { onDragEnter, onDragLeave, onDragOver, onDrop } }
}

function isInternalDrag(e: React.DragEvent): boolean {
  return e.dataTransfer.types.includes(INTERNAL_DRAG_TYPE)
}
