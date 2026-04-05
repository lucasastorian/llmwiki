'use client'

import * as React from 'react'
import ReactDOM from 'react-dom'
import { Pencil, Trash2, NotepadText, Folder, Upload } from 'lucide-react'

interface ContextMenuProps {
  open: boolean
  x: number
  y: number
  onClose: () => void
}

function useContextMenuDismiss(open: boolean, onClose: () => void, menuRef: React.RefObject<HTMLDivElement | null>) {
  React.useEffect(() => {
    if (!open) return
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) onClose()
    }
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('mousedown', handleClick)
    document.addEventListener('keydown', handleEsc)
    document.addEventListener('contextmenu', handleClick)
    return () => {
      document.removeEventListener('mousedown', handleClick)
      document.removeEventListener('keydown', handleEsc)
      document.removeEventListener('contextmenu', handleClick)
    }
  }, [open, onClose, menuRef])
}

export function SourceContextMenu({
  open, x, y, onRename, onDelete, onClose,
}: ContextMenuProps & { onRename: () => void; onDelete: () => void }) {
  const menuRef = React.useRef<HTMLDivElement>(null)
  useContextMenuDismiss(open, onClose, menuRef)

  if (!open) return null

  return ReactDOM.createPortal(
    <div
      ref={menuRef}
      className="fixed z-50 min-w-[8rem] bg-popover text-popover-foreground border rounded-md p-1 shadow-md animate-in fade-in-0 zoom-in-95"
      style={{ left: x, top: y }}
    >
      <button
        onClick={onRename}
        className="flex items-center gap-2 w-full rounded-sm px-2 py-1.5 text-sm hover:bg-accent cursor-pointer"
      >
        <Pencil className="size-3.5" />
        Rename
      </button>
      <div className="h-px bg-border -mx-1 my-1" />
      <button
        onClick={onDelete}
        className="flex items-center gap-2 w-full rounded-sm px-2 py-1.5 text-sm text-destructive hover:bg-destructive/10 cursor-pointer"
      >
        <Trash2 className="size-3.5" />
        Delete
      </button>
    </div>,
    document.body,
  )
}

export function SourceAreaContextMenu({
  open, x, y, onNewNote, onNewFolder, onUpload, onClose,
}: ContextMenuProps & { onNewNote: () => void; onNewFolder: () => void; onUpload: () => void }) {
  const menuRef = React.useRef<HTMLDivElement>(null)
  useContextMenuDismiss(open, onClose, menuRef)

  if (!open) return null

  return ReactDOM.createPortal(
    <div
      ref={menuRef}
      className="fixed z-50 min-w-[8rem] bg-popover text-popover-foreground border rounded-md p-1 shadow-md animate-in fade-in-0 zoom-in-95"
      style={{ left: x, top: y }}
    >
      <button
        onClick={onNewNote}
        className="flex items-center gap-2 w-full rounded-sm px-2 py-1.5 text-sm hover:bg-accent cursor-pointer"
      >
        <NotepadText className="size-3.5" />
        New Note
      </button>
      <button
        onClick={onNewFolder}
        className="flex items-center gap-2 w-full rounded-sm px-2 py-1.5 text-sm hover:bg-accent cursor-pointer"
      >
        <Folder className="size-3.5" />
        New Folder
      </button>
      <div className="h-px bg-border -mx-1 my-1" />
      <button
        onClick={onUpload}
        className="flex items-center gap-2 w-full rounded-sm px-2 py-1.5 text-sm hover:bg-accent cursor-pointer"
      >
        <Upload className="size-3.5" />
        Upload Files
      </button>
    </div>,
    document.body,
  )
}
