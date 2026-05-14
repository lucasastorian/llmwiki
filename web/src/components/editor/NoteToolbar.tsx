'use client'

import * as React from 'react'
import {
  Bold, Italic, Heading2, List, ListOrdered, LinkIcon,
  Table2, Undo2, Redo2, ChevronLeft, ChevronRight,
  Rows3, Columns3, Trash2,
} from 'lucide-react'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuTrigger, DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'
import { Popover, PopoverTrigger, PopoverContent } from '@/components/ui/popover'
import type { Editor } from '@tiptap/react'

interface NoteToolbarProps {
  editor: Editor | null
  backLabel: string
  noteTitle: string
  onTitleChange?: (title: string) => void
  onBack: () => void
  embedded?: boolean
}

export function NoteToolbar({ editor, backLabel, noteTitle, onTitleChange, onBack, embedded }: NoteToolbarProps) {
  const [linkOpen, setLinkOpen] = React.useState(false)
  const [linkUrl, setLinkUrl] = React.useState('')

  const handleLinkSubmit = () => {
    const url = linkUrl.trim()
    if (url) {
      editor?.chain().focus().setLink({ href: url }).run()
    }
    setLinkUrl('')
    setLinkOpen(false)
  }

  return (
    <div className={cn(
      'flex items-center gap-1.5 shrink-0',
      embedded ? 'px-4 py-2 border-b border-border' : 'px-5 py-4 bg-background',
    )}>
      {!embedded && (
        <>
          <button
            onClick={onBack}
            className="p-1 rounded transition-colors hover:bg-accent cursor-pointer text-foreground"
          >
            <ChevronLeft className="size-4" />
          </button>
          <button
            disabled
            className="p-1 rounded transition-colors text-muted-foreground/30 cursor-default"
          >
            <ChevronRight className="size-4" />
          </button>

          <nav className="flex items-center gap-1 text-sm min-w-0 mr-auto overflow-hidden">
            <button
              onClick={onBack}
              className="px-1.5 py-0.5 rounded transition-colors cursor-pointer truncate text-muted-foreground hover:text-foreground hover:bg-accent"
            >
              {backLabel}
            </button>
            <span className="text-muted-foreground/40">/</span>
            <span className="px-1.5 py-0.5 text-foreground font-medium truncate">
              {noteTitle || 'Untitled'}
            </span>
          </nav>
        </>
      )}

      {embedded && (
        <input
          type="text"
          value={noteTitle}
          onChange={(e) => onTitleChange?.(e.target.value)}
          placeholder="Untitled"
          className="flex-1 min-w-0 text-sm font-medium text-foreground bg-transparent border-none outline-none placeholder:text-muted-foreground/30 mr-2"
        />
      )}

      <div className="flex items-center gap-0.5">
        <ToolbarButton
          onClick={() => editor?.chain().focus().undo().run()}
          disabled={!editor?.can().undo()}
          title="Undo"
        >
          <Undo2 className="size-3.5" />
        </ToolbarButton>
        <ToolbarButton
          onClick={() => editor?.chain().focus().redo().run()}
          disabled={!editor?.can().redo()}
          title="Redo"
        >
          <Redo2 className="size-3.5" />
        </ToolbarButton>

        <div className="w-px h-4 bg-border mx-1" />

        <ToolbarButton
          active={editor?.isActive('bold')}
          onClick={() => editor?.chain().focus().toggleBold().run()}
          title="Bold"
        >
          <Bold className="size-3.5" />
        </ToolbarButton>
        <ToolbarButton
          active={editor?.isActive('italic')}
          onClick={() => editor?.chain().focus().toggleItalic().run()}
          title="Italic"
        >
          <Italic className="size-3.5" />
        </ToolbarButton>
        <ToolbarButton
          active={editor?.isActive('heading', { level: 2 })}
          onClick={() => editor?.chain().focus().toggleHeading({ level: 2 }).run()}
          title="Heading"
        >
          <Heading2 className="size-3.5" />
        </ToolbarButton>

        <div className="w-px h-4 bg-border mx-1" />

        <ToolbarButton
          active={editor?.isActive('bulletList')}
          onClick={() => editor?.chain().focus().toggleBulletList().run()}
          title="Bullet List"
        >
          <List className="size-3.5" />
        </ToolbarButton>
        <ToolbarButton
          active={editor?.isActive('orderedList')}
          onClick={() => editor?.chain().focus().toggleOrderedList().run()}
          title="Ordered List"
        >
          <ListOrdered className="size-3.5" />
        </ToolbarButton>
        {editor?.isActive('link') ? (
          <ToolbarButton
            active
            onClick={() => editor.chain().focus().unsetLink().run()}
            title="Remove link"
          >
            <LinkIcon className="size-3.5" />
          </ToolbarButton>
        ) : (
          <Popover open={linkOpen} onOpenChange={(open) => {
            setLinkOpen(open)
            if (!open) setLinkUrl('')
          }}>
            <PopoverTrigger asChild>
              <button
                title="Link"
                className={cn(
                  'p-1.5 rounded-md transition-colors cursor-pointer',
                  'text-muted-foreground hover:text-foreground hover:bg-accent'
                )}
              >
                <LinkIcon className="size-3.5" />
              </button>
            </PopoverTrigger>
            <PopoverContent className="w-72 p-2" align="start" side="bottom">
              <form
                onSubmit={(e) => { e.preventDefault(); handleLinkSubmit() }}
                className="flex items-center gap-1.5"
              >
                <input
                  type="url"
                  value={linkUrl}
                  onChange={(e) => setLinkUrl(e.target.value)}
                  placeholder="https://..."
                  autoFocus
                  className="flex-1 text-sm bg-transparent border border-border rounded-md px-2 py-1 focus:outline-none focus:ring-1 focus:ring-ring placeholder:text-muted-foreground/40"
                />
                <button
                  type="submit"
                  disabled={!linkUrl.trim()}
                  className="text-sm px-2 py-1 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-40 cursor-pointer"
                >
                  Add
                </button>
              </form>
            </PopoverContent>
          </Popover>
        )}

        <div className="w-px h-4 bg-border mx-1" />

        {editor?.isActive('table') ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                title="Table options"
                className="p-1.5 rounded-md transition-colors cursor-pointer bg-accent text-foreground"
              >
                <Table2 className="size-3.5" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => editor.chain().focus().addRowAfter().run()}>
                <Rows3 className="size-3.5 mr-2" />
                Add Row Below
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => editor.chain().focus().addColumnAfter().run()}>
                <Columns3 className="size-3.5 mr-2" />
                Add Column Right
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => editor.chain().focus().deleteRow().run()}>
                Delete Row
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => editor.chain().focus().deleteColumn().run()}>
                Delete Column
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={() => editor.chain().focus().deleteTable().run()}
                className="text-destructive focus:text-destructive"
              >
                <Trash2 className="size-3.5 mr-2" />
                Delete Table
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        ) : (
          <ToolbarButton
            onClick={() => editor?.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()}
            title="Insert Table"
          >
            <Table2 className="size-3.5" />
          </ToolbarButton>
        )}
      </div>
    </div>
  )
}

/**
 * Standalone formatting buttons — can be rendered anywhere with an Editor instance.
 * Used by FilesGrid to embed formatting in its unified toolbar.
 */
export function NoteFormattingButtons({ editor }: { editor: Editor | null }) {
  const [linkOpen, setLinkOpen] = React.useState(false)
  const [linkUrl, setLinkUrl] = React.useState('')

  const handleLinkSubmit = () => {
    const url = linkUrl.trim()
    if (url) editor?.chain().focus().setLink({ href: url }).run()
    setLinkUrl('')
    setLinkOpen(false)
  }

  return (
    <div className="flex items-center gap-0.5">
      <ToolbarButton onClick={() => editor?.chain().focus().undo().run()} disabled={!editor?.can().undo()} title="Undo"><Undo2 className="size-3.5" /></ToolbarButton>
      <ToolbarButton onClick={() => editor?.chain().focus().redo().run()} disabled={!editor?.can().redo()} title="Redo"><Redo2 className="size-3.5" /></ToolbarButton>
      <div className="w-px h-4 bg-border mx-1" />
      <ToolbarButton active={editor?.isActive('bold')} onClick={() => editor?.chain().focus().toggleBold().run()} title="Bold"><Bold className="size-3.5" /></ToolbarButton>
      <ToolbarButton active={editor?.isActive('italic')} onClick={() => editor?.chain().focus().toggleItalic().run()} title="Italic"><Italic className="size-3.5" /></ToolbarButton>
      <ToolbarButton active={editor?.isActive('heading', { level: 2 })} onClick={() => editor?.chain().focus().toggleHeading({ level: 2 }).run()} title="Heading"><Heading2 className="size-3.5" /></ToolbarButton>
      <div className="w-px h-4 bg-border mx-1" />
      <ToolbarButton active={editor?.isActive('bulletList')} onClick={() => editor?.chain().focus().toggleBulletList().run()} title="Bullet List"><List className="size-3.5" /></ToolbarButton>
      <ToolbarButton active={editor?.isActive('orderedList')} onClick={() => editor?.chain().focus().toggleOrderedList().run()} title="Ordered List"><ListOrdered className="size-3.5" /></ToolbarButton>
      {editor?.isActive('link') ? (
        <ToolbarButton active onClick={() => editor.chain().focus().unsetLink().run()} title="Remove link"><LinkIcon className="size-3.5" /></ToolbarButton>
      ) : (
        <Popover open={linkOpen} onOpenChange={(open) => { setLinkOpen(open); if (!open) setLinkUrl('') }}>
          <PopoverTrigger asChild>
            <button title="Link" className="p-1.5 rounded-md transition-colors cursor-pointer text-muted-foreground hover:text-foreground hover:bg-accent"><LinkIcon className="size-3.5" /></button>
          </PopoverTrigger>
          <PopoverContent className="w-72 p-2" align="start" side="bottom">
            <form onSubmit={(e) => { e.preventDefault(); handleLinkSubmit() }} className="flex items-center gap-1.5">
              <input type="url" value={linkUrl} onChange={(e) => setLinkUrl(e.target.value)} placeholder="https://..." autoFocus className="flex-1 text-sm bg-transparent border border-border rounded-md px-2 py-1 focus:outline-none focus:ring-1 focus:ring-ring placeholder:text-muted-foreground/40" />
              <button type="submit" disabled={!linkUrl.trim()} className="text-sm px-2 py-1 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-40 cursor-pointer">Add</button>
            </form>
          </PopoverContent>
        </Popover>
      )}
      <div className="w-px h-4 bg-border mx-1" />
      {editor?.isActive('table') ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button title="Table options" className="p-1.5 rounded-md transition-colors cursor-pointer bg-accent text-foreground"><Table2 className="size-3.5" /></button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => editor.chain().focus().addRowAfter().run()}><Rows3 className="size-3.5 mr-2" />Add Row Below</DropdownMenuItem>
            <DropdownMenuItem onClick={() => editor.chain().focus().addColumnAfter().run()}><Columns3 className="size-3.5 mr-2" />Add Column Right</DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => editor.chain().focus().deleteRow().run()}>Delete Row</DropdownMenuItem>
            <DropdownMenuItem onClick={() => editor.chain().focus().deleteColumn().run()}>Delete Column</DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => editor.chain().focus().deleteTable().run()} className="text-destructive focus:text-destructive"><Trash2 className="size-3.5 mr-2" />Delete Table</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : (
        <ToolbarButton onClick={() => editor?.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()} title="Insert Table"><Table2 className="size-3.5" /></ToolbarButton>
      )}
    </div>
  )
}

function ToolbarButton({
  children,
  active,
  onClick,
  title,
  disabled,
}: {
  children: React.ReactNode
  active?: boolean
  onClick?: () => void
  title?: string
  disabled?: boolean
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      disabled={disabled}
      className={cn(
        'p-1.5 rounded-md transition-colors cursor-pointer',
        disabled
          ? 'text-muted-foreground/30 cursor-default'
          : active
            ? 'bg-accent text-foreground'
            : 'text-muted-foreground hover:text-foreground hover:bg-accent'
      )}
    >
      {children}
    </button>
  )
}
