'use client'

import { Trash2, X } from 'lucide-react'

type Props = {
  count: number
  onDelete: () => void
  onClear: () => void
}

export function SelectionActionBar({ count, onDelete, onClear }: Props) {
  if (count === 0) return null

  return (
    <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-40 flex items-center gap-3 rounded-lg border border-border bg-background/95 backdrop-blur-sm shadow-lg px-4 py-2.5 animate-in slide-in-from-bottom-2 fade-in-0 duration-200">
      <span className="text-sm font-medium text-foreground tabular-nums">
        {count} selected
      </span>
      <div className="h-4 w-px bg-border" />
      <button
        onClick={onDelete}
        className="inline-flex items-center gap-1.5 rounded-md bg-destructive px-3 py-1.5 text-xs font-medium text-destructive-foreground hover:bg-destructive/90 transition-colors cursor-pointer"
      >
        <Trash2 className="size-3.5" />
        Delete
      </button>
      <button
        onClick={onClear}
        className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors cursor-pointer"
        title="Clear selection (Esc)"
      >
        <X className="size-4" />
      </button>
    </div>
  )
}
