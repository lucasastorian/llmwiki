'use client'

import * as React from 'react'
import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'
import Typography from '@tiptap/extension-typography'
import Link from '@tiptap/extension-link'
import Image from '@tiptap/extension-image'
import { Table, TableRow, TableHeader, TableCell } from '@tiptap/extension-table'
import { Markdown } from 'tiptap-markdown'
import { format, parse, isValid } from 'date-fns'
import { X, CalendarIcon, Plus, ChevronUp } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { useUserStore } from '@/stores'
import { cn, sanitizeTitle } from '@/lib/utils'
import { NoteToolbar } from './NoteToolbar'
import {
  sanitizeUrl, defaultValue, migrateProperties,
  PropertyValueEditor, TagsRow, PropertyRow, AddPropertyButton,
} from './PropertyEditors'
import { Popover, PopoverTrigger, PopoverContent } from '@/components/ui/popover'
import { Calendar } from '@/components/ui/calendar'
import type { Editor } from '@tiptap/react'
import type { PropertyType, TypedProperty, PropertyMap } from '@/lib/types'

const AUTOSAVE_DELAY = 1500

function getMarkdown(editor: Editor): string {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (editor.storage as any).markdown.getMarkdown()
}

const FRONTMATTER_RE = /^\s*---[ \t]*\n([\s\S]*?\n)---[ \t]*\n/

function stripFrontmatter(content: string): { body: string; meta: Record<string, string> } {
  const match = content.match(FRONTMATTER_RE)
  if (!match) return { body: content, meta: {} }

  const body = content.slice(match[0].length)
  const meta: Record<string, string> = {}
  for (const line of match[1].split('\n')) {
    const idx = line.indexOf(':')
    if (idx > 0) {
      const key = line.slice(0, idx).trim()
      const val = line.slice(idx + 1).trim()
      if (key && val && !key.startsWith(' ') && !key.startsWith('-')) {
        meta[key] = val
      }
    }
  }
  return { body, meta }
}


interface NoteEditorProps {
  documentId: string
  initialContent?: string
  initialTitle?: string
  initialTags?: string[]
  initialDate?: string | null
  initialProperties?: Record<string, unknown>
  onTitleChange?: (title: string) => void
  backLabel?: string
  onBack?: () => void
  embedded?: boolean
  /** Hide the built-in toolbar (when the parent provides its own) */
  hideToolbar?: boolean
  /** Called when the tiptap editor is ready — lets the parent render formatting buttons externally */
  onEditorReady?: (editor: import('@tiptap/react').Editor) => void
}

function getAccessToken(): string | null {
  return useUserStore.getState().accessToken
}

export function NoteEditor({
  documentId,
  initialContent,
  initialTitle,
  initialTags,
  initialDate,
  initialProperties,
  onTitleChange,
  backLabel,
  onBack,
  embedded,
  hideToolbar,
  onEditorReady,
}: NoteEditorProps) {
  const [title, setTitle] = React.useState(initialTitle ?? '')
  const [date, setDate] = React.useState<string>(initialDate ?? '')
  const [tags, setTags] = React.useState<string[]>(initialTags ?? [])
  const [tagInput, setTagInput] = React.useState('')
  const [properties, setProperties] = React.useState<PropertyMap>(() =>
    initialProperties ? migrateProperties(initialProperties) : {}
  )
  const [loaded, setLoaded] = React.useState(false)
  const [calendarOpen, setCalendarOpen] = React.useState(false)
  const [saveStatus, setSaveStatus] = React.useState<'saved' | 'saving' | 'idle'>('idle')
  const [wordCount, setWordCount] = React.useState(0)
  const [metaExpanded, setMetaExpanded] = React.useState(false)
  const saveTimerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null)
  const latestContentRef = React.useRef<string>('')
  const frontmatterRef = React.useRef<string>('')
  const latestTitleRef = React.useRef<string>(initialTitle ?? '')
  const latestDateRef = React.useRef<string>(initialDate ?? '')
  const latestTagsRef = React.useRef<string[]>(initialTags ?? [])
  const latestPropertiesRef = React.useRef<PropertyMap>(
    initialProperties ? migrateProperties(initialProperties) : {}
  )
  const dirtyRef = React.useRef(false)
  const metaDirtyRef = React.useRef(false)

  const editor = useEditor({
    immediatelyRender: false,
    extensions: [
      StarterKit.configure({
        heading: { levels: [1, 2, 3] },
        link: false,
      }),
      Placeholder.configure({ placeholder: 'Start writing...' }),
      Typography,
      Link.configure({ autolink: true, openOnClick: false }),
      Image.configure({ inline: false, allowBase64: true }),
      Table.configure({ resizable: false }),
      TableRow,
      TableHeader,
      TableCell,
      Markdown.configure({
        html: false,
        transformCopiedText: true,
        transformPastedText: true,
      }),
    ],
    editorProps: {
      attributes: {
        class: 'prose prose-sm dark:prose-invert max-w-none focus:outline-none min-h-[calc(100vh-200px)] cursor-text',
      },
      handleClick: (_view, _pos, event) => {
        const anchor = (event.target as HTMLElement).closest('a')
        if (!anchor) return false
        const href = anchor.getAttribute('href')
        if (!href) return false
        const safeHref = sanitizeUrl(href)
        if (safeHref) window.open(safeHref, '_blank', 'noopener')
        return true
      },
    },
    onUpdate: ({ editor }) => {
      latestContentRef.current = getMarkdown(editor)
      dirtyRef.current = true
      setSaveStatus('idle')
      scheduleSave()

      const text = editor.state.doc.textContent
      setWordCount(text.trim() ? text.trim().split(/\s+/).length : 0)
    },
  })

  // Expose editor to parent for external toolbar rendering
  React.useEffect(() => {
    if (editor && onEditorReady) onEditorReady(editor)
  }, [editor, onEditorReady])

  const dateValue = React.useMemo(() => {
    if (!date) return undefined
    const parsed = parse(date, 'yyyy-MM-dd', new Date())
    return isValid(parsed) ? parsed : undefined
  }, [date])

  React.useEffect(() => {
    let cancelled = false

    const load = async () => {
      setLoaded(false)
      const token = await getAccessToken()
      if (!token || cancelled) return

      try {
        const { content } = await apiFetch<{ id: string; content: string; version: number }>(
          `/v1/documents/${documentId}/content`,
          token,
        )

        if (cancelled) return
        const raw = content ?? ''
        const { body, meta } = stripFrontmatter(raw)
        const fmMatch = raw.match(FRONTMATTER_RE)
        frontmatterRef.current = fmMatch ? fmMatch[0] : ''
        latestContentRef.current = body
        editor?.commands.setContent(body)

        if (meta.date && !date) {
          setDate(meta.date)
        }
      } catch (err) {
        console.error('[NoteEditor] Failed to load content:', err)
        if (initialContent != null && !cancelled) {
          latestContentRef.current = initialContent
          editor?.commands.setContent(initialContent)
        }
      }

      if (!cancelled) {
        setLoaded(true)
        if (editor) {
          const text = editor.state.doc.textContent
          setWordCount(text.trim() ? text.trim().split(/\s+/).length : 0)
        }
      }
    }

    load()
    return () => { cancelled = true }
  }, [documentId, editor, initialContent])

  const save = React.useCallback(async () => {
    if (!dirtyRef.current) return
    dirtyRef.current = false
    const shouldPatchMeta = metaDirtyRef.current
    metaDirtyRef.current = false
    setSaveStatus('saving')

    const token = await getAccessToken()
    if (!token) {
      dirtyRef.current = true
      setSaveStatus('idle')
      return
    }

    try {
      const promises: Promise<unknown>[] = [
        apiFetch(`/v1/documents/${documentId}/content`, token, {
          method: 'PUT',
          body: JSON.stringify({ content: frontmatterRef.current + latestContentRef.current }),
        }),
      ]

      if (shouldPatchMeta) {
        const hasProps = Object.keys(latestPropertiesRef.current).length > 0
        promises.push(
          apiFetch(`/v1/documents/${documentId}`, token, {
            method: 'PATCH',
            body: JSON.stringify({
              title: latestTitleRef.current || null,
              tags: latestTagsRef.current.length > 0 ? latestTagsRef.current : null,
              date: latestDateRef.current || null,
              metadata: hasProps ? { properties: latestPropertiesRef.current } : null,
            }),
          }),
        )
      }

      await Promise.all(promises)
      setSaveStatus('saved')
    } catch (err) {
      console.error('[NoteEditor] save failed:', err)
      dirtyRef.current = true
      setSaveStatus('idle')
    }
  }, [documentId])

  const scheduleSave = React.useCallback(() => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    saveTimerRef.current = setTimeout(save, AUTOSAVE_DELAY)
  }, [save])

  React.useEffect(() => {
    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
      if (dirtyRef.current) {
        const frontmatter = frontmatterRef.current
        const contentToSave = latestContentRef.current
        const titleToSave = latestTitleRef.current
        const tagsToSave = latestTagsRef.current
        const dateToSave = latestDateRef.current
        const propsToSave = latestPropertiesRef.current
        const shouldPatchMeta = metaDirtyRef.current
        const docId = documentId

        ;(async () => {
          const token = await getAccessToken()
          if (!token) return

          try {
            const promises: Promise<unknown>[] = [
              apiFetch(`/v1/documents/${docId}/content`, token, {
                method: 'PUT',
                body: JSON.stringify({ content: frontmatter + contentToSave }),
              }),
            ]

            if (shouldPatchMeta) {
              const hasProps = Object.keys(propsToSave).length > 0
              promises.push(
                apiFetch(`/v1/documents/${docId}`, token, {
                  method: 'PATCH',
                  body: JSON.stringify({
                    title: titleToSave || null,
                    tags: tagsToSave.length > 0 ? tagsToSave : null,
                    date: dateToSave || null,
                    metadata: hasProps ? { properties: propsToSave } : null,
                  }),
                }),
              )
            }

            await Promise.all(promises)
          } catch (err) {
            console.error('[NoteEditor] flush on unmount failed:', err)
          }
        })()
      }
    }
  }, [documentId])

  React.useEffect(() => {
    const handleOnline = () => {
      if (dirtyRef.current) save()
    }
    window.addEventListener('online', handleOnline)
    return () => window.removeEventListener('online', handleOnline)
  }, [save])

  const handleTitleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = sanitizeTitle(e.target.value)
    setTitle(val)
    latestTitleRef.current = val
    dirtyRef.current = true
    metaDirtyRef.current = true
    setSaveStatus('idle')
    scheduleSave()
    onTitleChange?.(val)
  }

  const handleDateSelect = (selected: Date | undefined) => {
    const val = selected ? format(selected, 'yyyy-MM-dd') : ''
    setDate(val)
    latestDateRef.current = val
    dirtyRef.current = true
    metaDirtyRef.current = true
    setSaveStatus('idle')
    scheduleSave()
    setCalendarOpen(false)
  }

  const handleClearDate = (e: React.MouseEvent) => {
    e.stopPropagation()
    setDate('')
    latestDateRef.current = ''
    dirtyRef.current = true
    metaDirtyRef.current = true
    scheduleSave()
  }

  const handleAddTag = () => {
    const tag = tagInput.trim()
    if (!tag || tags.includes(tag)) { setTagInput(''); return }
    const next = [...tags, tag]
    setTags(next)
    latestTagsRef.current = next
    setTagInput('')
    dirtyRef.current = true
    metaDirtyRef.current = true
    scheduleSave()
  }

  const handleRemoveTag = (tag: string) => {
    const next = tags.filter((t) => t !== tag)
    setTags(next)
    latestTagsRef.current = next
    dirtyRef.current = true
    metaDirtyRef.current = true
    scheduleSave()
  }

  const handleTagKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') { e.preventDefault(); handleAddTag() }
    if (e.key === 'Backspace' && !tagInput && tags.length > 0) {
      handleRemoveTag(tags[tags.length - 1])
    }
  }

  const handlePropertyChange = (key: string, value: TypedProperty['value']) => {
    const prev = properties[key]
    if (!prev) return
    const next = { ...properties, [key]: { ...prev, value } }
    setProperties(next)
    latestPropertiesRef.current = next
    dirtyRef.current = true
    metaDirtyRef.current = true
    setSaveStatus('idle')
    scheduleSave()
  }

  const handlePropertyKeyRename = (oldKey: string, newKey: string) => {
    if (!newKey.trim() || (newKey !== oldKey && newKey in properties)) return
    const next: PropertyMap = {}
    for (const [k, v] of Object.entries(properties)) {
      next[k === oldKey ? newKey.trim() : k] = v
    }
    setProperties(next)
    latestPropertiesRef.current = next
    dirtyRef.current = true
    metaDirtyRef.current = true
    scheduleSave()
  }

  const handleAddProperty = (type: PropertyType) => {
    let name = 'property'
    let i = 1
    while (name in properties) { name = `property ${i++}` }
    const next = { ...properties, [name]: defaultValue(type) }
    setProperties(next)
    latestPropertiesRef.current = next
    dirtyRef.current = true
    metaDirtyRef.current = true
    scheduleSave()
  }

  const handleRemoveProperty = (key: string) => {
    const next = { ...properties }
    delete next[key]
    setProperties(next)
    latestPropertiesRef.current = next
    dirtyRef.current = true
    metaDirtyRef.current = true
    scheduleSave()
  }

  const handleSelectOptionsChange = (key: string, options: string[]) => {
    const prev = properties[key]
    if (!prev || prev.type !== 'select') return
    const next = { ...properties, [key]: { ...prev, options } }
    setProperties(next)
    latestPropertiesRef.current = next
    dirtyRef.current = true
    metaDirtyRef.current = true
    scheduleSave()
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {!hideToolbar && (
        <NoteToolbar
          editor={editor}
          backLabel={backLabel ?? 'Back'}
          noteTitle={title}
          onTitleChange={embedded ? (val: string) => {
            const sanitized = sanitizeTitle(val)
            setTitle(sanitized)
            latestTitleRef.current = sanitized
            dirtyRef.current = true
            metaDirtyRef.current = true
            setSaveStatus('idle')
            scheduleSave()
            onTitleChange?.(sanitized)
          } : undefined}
          onBack={onBack ?? (() => {})}
          embedded={embedded}
        />
      )}

      <div className={cn(
        'flex-1 overflow-y-auto',
        embedded ? '' : 'bg-background px-6',
      )}>
        <div className={cn(
          embedded
            ? 'max-w-3xl mx-auto px-8 py-10'
            : 'max-w-4xl mx-auto px-20 py-12 bg-card rounded-2xl border border-border/40 shadow-sm mb-6 min-h-[calc(100%-1.5rem)]',
        )}>
          {!embedded && (
            <input
              type="text"
              value={title}
              onChange={handleTitleChange}
              placeholder="Untitled"
              className="w-full text-2xl font-bold text-foreground bg-transparent border-none outline-none placeholder:text-muted-foreground/30 mb-4"
            />
          )}

          {!metaExpanded && (tags.length > 0 || date) && (
            <button
              onClick={() => setMetaExpanded(true)}
              className="flex items-center gap-2 mb-4 text-xs text-muted-foreground/50 hover:text-muted-foreground transition-colors cursor-pointer"
            >
              {date && <span className="bg-muted px-1.5 py-0.5 rounded text-[11px]">{date}</span>}
              {tags.length > 0 && (
                <span className="bg-muted px-1.5 py-0.5 rounded text-[11px]">{tags.length} tag{tags.length !== 1 ? 's' : ''}</span>
              )}
            </button>
          )}
          {!metaExpanded && !tags.length && !date && (
            <button
              onClick={() => setMetaExpanded(true)}
              className="flex items-center gap-1.5 mb-4 text-xs text-muted-foreground/30 hover:text-muted-foreground transition-colors cursor-pointer"
            >
              <Plus className="size-3" />
              Add metadata
            </button>
          )}
          {metaExpanded && <div className="mb-6 space-y-0.5">
            <div className="flex items-center h-8">
              <div className="flex items-center gap-2 w-24 shrink-0">
                <CalendarIcon className="size-3.5 text-muted-foreground" />
                <span className="text-sm text-muted-foreground">date</span>
              </div>
              <Popover open={calendarOpen} onOpenChange={setCalendarOpen}>
                <PopoverTrigger asChild>
                  <button
                    className={cn(
                      'text-sm h-7 transition-colors cursor-pointer px-1.5',
                      date ? 'text-foreground' : 'text-muted-foreground/40'
                    )}
                  >
                    {dateValue ? format(dateValue, 'PPP') : 'Pick a date'}
                  </button>
                </PopoverTrigger>
                <PopoverContent className="w-auto p-0" align="start">
                  <Calendar
                    mode="single"
                    selected={dateValue}
                    onSelect={handleDateSelect}
                    defaultMonth={dateValue ?? new Date()}
                  />
                </PopoverContent>
              </Popover>
              {date && (
                <button
                  onClick={handleClearDate}
                  className="ml-1 text-muted-foreground/40 hover:text-muted-foreground cursor-pointer"
                >
                  <X className="size-3" />
                </button>
              )}
            </div>

            <TagsRow
              tags={tags}
              tagInput={tagInput}
              onTagInputChange={setTagInput}
              onTagKeyDown={handleTagKeyDown}
              onAddTag={handleAddTag}
              onRemoveTag={handleRemoveTag}
            />

            {Object.entries(properties).map(([key, prop]) => (
              <PropertyRow
                key={key}
                propKey={key}
                property={prop}
                onValueChange={(value) => handlePropertyChange(key, value)}
                onKeyRename={handlePropertyKeyRename}
                onRemove={() => handleRemoveProperty(key)}
                onOptionsChange={prop.type === 'select' ? (opts) => handleSelectOptionsChange(key, opts) : undefined}
              />
            ))}

            <AddPropertyButton onAdd={handleAddProperty} />

            <button
              onClick={() => setMetaExpanded(false)}
              className="flex items-center gap-1.5 h-7 text-sm text-muted-foreground/30 hover:text-muted-foreground transition-colors cursor-pointer"
            >
              <ChevronUp className="size-3.5" />
              <span>Collapse</span>
            </button>
          </div>}

          {loaded && editor ? (
            <EditorContent editor={editor} />
          ) : (
            <div className="flex min-h-[240px] items-center justify-center">
              <span className="text-sm text-muted-foreground">Loading note...</span>
            </div>
          )}
        </div>
      </div>

      <div className={cn(
        'shrink-0 flex items-center justify-end py-1.5',
        embedded ? 'px-4 border-t border-border' : 'px-5 bg-background',
      )}>
        <span className="text-[10px] text-muted-foreground mr-3">
          {saveStatus === 'saving' ? 'Saving...' : saveStatus === 'saved' ? 'Saved' : ''}
        </span>
        <span className="text-[10px] text-muted-foreground tabular-nums">
          {wordCount} {wordCount === 1 ? 'word' : 'words'}
        </span>
      </div>
    </div>
  )
}
