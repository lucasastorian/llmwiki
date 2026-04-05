'use client'

import * as React from 'react'
import { format, parse, isValid } from 'date-fns'
import {
  X, CalendarIcon, Tag, Plus, Hash, Type, CheckSquare, Square,
  List, LinkIcon, ExternalLink, ChevronDown, ChevronUp,
} from 'lucide-react'
import { Popover, PopoverTrigger, PopoverContent } from '@/components/ui/popover'
import { Calendar } from '@/components/ui/calendar'
import {
  DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'
import type { PropertyType, TypedProperty, PropertyMap } from '@/lib/types'

const ALLOWED_SCHEMES = new Set(['http:', 'https:', 'mailto:'])

export function sanitizeUrl(url: string): string | undefined {
  try {
    const parsed = new URL(url, 'https://placeholder.invalid')
    if (ALLOWED_SCHEMES.has(parsed.protocol)) return url
  } catch { /* invalid URL */ }
  return undefined
}

export function defaultValue(type: PropertyType): TypedProperty {
  switch (type) {
    case 'text': return { type, value: '' }
    case 'number': return { type, value: null }
    case 'date': return { type, value: null }
    case 'checkbox': return { type, value: false }
    case 'select': return { type, value: null, options: [] }
    case 'url': return { type, value: '' }
  }
}

export function migrateProperties(raw: Record<string, unknown>): PropertyMap {
  const result: PropertyMap = {}
  for (const [k, v] of Object.entries(raw)) {
    if (typeof v === 'string') {
      result[k] = { type: 'text', value: v }
    } else if (v && typeof v === 'object' && 'type' in v) {
      result[k] = v as TypedProperty
    }
  }
  return result
}

const PROPERTY_TYPE_ICON: Record<PropertyType, React.ElementType> = {
  text: Type,
  number: Hash,
  date: CalendarIcon,
  checkbox: CheckSquare,
  select: List,
  url: LinkIcon,
}

function PropertyIcon({ type }: { type: PropertyType }) {
  const Icon = PROPERTY_TYPE_ICON[type]
  return <Icon className="size-3.5 text-muted-foreground" />
}

function DatePropertyEditor({
  value,
  onChange,
}: {
  value: string | null
  onChange: (value: string | null) => void
}) {
  const [open, setOpen] = React.useState(false)

  const dateObj = React.useMemo(() => {
    if (!value) return undefined
    const parsed = parse(value, 'yyyy-MM-dd', new Date())
    return isValid(parsed) ? parsed : undefined
  }, [value])

  return (
    <div className="flex items-center flex-1 gap-1">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            className={cn(
              'text-sm h-7 transition-colors cursor-pointer px-1.5',
              value ? 'text-foreground' : 'text-muted-foreground/40'
            )}
          >
            {dateObj ? format(dateObj, 'PPP') : 'Pick a date'}
          </button>
        </PopoverTrigger>
        <PopoverContent className="w-auto p-0" align="start">
          <Calendar
            mode="single"
            selected={dateObj}
            onSelect={(d) => {
              onChange(d ? format(d, 'yyyy-MM-dd') : null)
              setOpen(false)
            }}
            defaultMonth={dateObj ?? new Date()}
          />
        </PopoverContent>
      </Popover>
      {value && (
        <button
          onClick={() => onChange(null)}
          className="text-muted-foreground/40 hover:text-muted-foreground cursor-pointer"
        >
          <X className="size-3" />
        </button>
      )}
    </div>
  )
}

function SelectPropertyEditor({
  value,
  options,
  onChange,
  onOptionsChange,
}: {
  value: string | null
  options: string[]
  onChange: (value: string | null) => void
  onOptionsChange: (options: string[]) => void
}) {
  const [open, setOpen] = React.useState(false)
  const [input, setInput] = React.useState('')

  const filtered = options.filter((o) =>
    !input || o.toLowerCase().includes(input.toLowerCase())
  )

  const handleAdd = () => {
    const trimmed = input.trim()
    if (!trimmed || options.includes(trimmed)) return
    onOptionsChange([...options, trimmed])
    onChange(trimmed)
    setInput('')
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          className={cn(
            'text-sm h-7 transition-colors cursor-pointer px-1.5 text-left flex-1 truncate',
            value ? 'text-foreground' : 'text-muted-foreground/40'
          )}
        >
          {value || 'Select...'}
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-48 p-1" align="start">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              if (filtered.length > 0 && !options.includes(input.trim())) {
                onChange(filtered[0])
                setOpen(false)
                setInput('')
              } else if (input.trim()) {
                handleAdd()
                setOpen(false)
              }
            }
          }}
          placeholder="Search or add..."
          className="w-full text-sm bg-transparent border-none outline-none px-2 py-1.5 placeholder:text-muted-foreground/40"
          autoFocus
        />
        <div className="max-h-40 overflow-y-auto">
          {value && (
            <button
              onClick={() => { onChange(null); setOpen(false); setInput('') }}
              className="w-full text-left text-sm px-2 py-1.5 rounded-sm hover:bg-accent text-muted-foreground/60 cursor-pointer"
            >
              Clear
            </button>
          )}
          {filtered.map((opt) => (
            <button
              key={opt}
              onClick={() => { onChange(opt); setOpen(false); setInput('') }}
              className={cn(
                'w-full text-left text-sm px-2 py-1.5 rounded-sm hover:bg-accent cursor-pointer flex items-center justify-between',
                opt === value && 'bg-accent'
              )}
            >
              {opt}
              {opt === value && <span className="text-xs text-muted-foreground">&#10003;</span>}
            </button>
          ))}
          {input.trim() && !options.includes(input.trim()) && (
            <button
              onClick={() => { handleAdd(); setOpen(false) }}
              className="w-full text-left text-sm px-2 py-1.5 rounded-sm hover:bg-accent text-muted-foreground cursor-pointer"
            >
              <Plus className="size-3 inline mr-1.5" />
              Create &ldquo;{input.trim()}&rdquo;
            </button>
          )}
        </div>
      </PopoverContent>
    </Popover>
  )
}

export function PropertyValueEditor({
  property,
  onChange,
  onOptionsChange,
}: {
  property: TypedProperty
  onChange: (value: TypedProperty['value']) => void
  onOptionsChange?: (options: string[]) => void
}) {
  switch (property.type) {
    case 'text':
      return (
        <input
          type="text"
          value={(property.value as string) ?? ''}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Empty"
          className="text-sm text-foreground bg-transparent border-none outline-none flex-1 h-7 px-1.5 placeholder:text-muted-foreground/30"
        />
      )
    case 'number':
      return (
        <input
          type="number"
          value={property.value != null ? String(property.value) : ''}
          onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
          placeholder="Empty"
          className="text-sm text-foreground bg-transparent border-none outline-none flex-1 h-7 px-1.5 placeholder:text-muted-foreground/30 [&::-webkit-inner-spin-button]:appearance-none"
        />
      )
    case 'date':
      return <DatePropertyEditor value={property.value as string | null} onChange={onChange} />
    case 'checkbox':
      return (
        <button
          onClick={() => onChange(!property.value)}
          className="flex items-center h-7 px-1.5 cursor-pointer"
        >
          {property.value
            ? <CheckSquare className="size-4 text-foreground" />
            : <Square className="size-4 text-muted-foreground/40" />}
        </button>
      )
    case 'select':
      return (
        <SelectPropertyEditor
          value={property.value as string | null}
          options={property.options ?? []}
          onChange={onChange}
          onOptionsChange={onOptionsChange!}
        />
      )
    case 'url':
      return (
        <div className="flex items-center flex-1 gap-1">
          <input
            type="text"
            value={(property.value as string) ?? ''}
            onChange={(e) => onChange(e.target.value)}
            placeholder="https://..."
            className="text-sm text-foreground bg-transparent border-none outline-none flex-1 h-7 px-1.5 placeholder:text-muted-foreground/30"
          />
          {property.value && sanitizeUrl(property.value as string) && (
            <a
              href={sanitizeUrl(property.value as string)!}
              target="_blank"
              rel="noopener noreferrer"
              className="text-muted-foreground hover:text-foreground p-0.5"
              onClick={(e) => e.stopPropagation()}
            >
              <ExternalLink className="size-3.5" />
            </a>
          )}
        </div>
      )
  }
}

export function TagsRow({
  tags,
  tagInput,
  onTagInputChange,
  onTagKeyDown,
  onAddTag,
  onRemoveTag,
}: {
  tags: string[]
  tagInput: string
  onTagInputChange: (v: string) => void
  onTagKeyDown: (e: React.KeyboardEvent) => void
  onAddTag: () => void
  onRemoveTag: (tag: string) => void
}) {
  const [expanded, setExpanded] = React.useState(false)

  return (
    <div className="flex items-start min-h-8">
      <div className="flex items-center gap-2 w-24 shrink-0 h-8">
        <Tag className="size-3.5 text-muted-foreground" />
        <span className="text-sm text-muted-foreground">tags</span>
      </div>
      <div className="flex-1 min-w-0 relative">
        <div
          className={cn(
            'flex items-center gap-1.5 px-1.5',
            expanded ? 'flex-wrap min-h-8 py-1' : 'overflow-x-auto no-scrollbar h-8',
          )}
        >
          {tags.map((tag) => (
            <span
              key={tag}
              className="inline-flex items-center gap-1 text-sm bg-muted text-muted-foreground rounded-md px-2 py-0.5 shrink-0"
            >
              {tag}
              <button
                onClick={() => onRemoveTag(tag)}
                className="hover:text-foreground cursor-pointer"
              >
                <X className="size-3" />
              </button>
            </span>
          ))}
          <input
            type="text"
            value={tagInput}
            onChange={(e) => onTagInputChange(e.target.value)}
            onKeyDown={onTagKeyDown}
            onBlur={onAddTag}
            placeholder={tags.length === 0 ? 'Add tags...' : '+'}
            className="text-sm bg-transparent border-none outline-none text-muted-foreground placeholder:text-muted-foreground/30 w-16 shrink-0"
          />
        </div>
        {tags.length > 3 && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="absolute right-0 top-1.5 p-1 text-muted-foreground hover:text-foreground cursor-pointer"
          >
            {expanded ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
          </button>
        )}
      </div>
    </div>
  )
}

export function PropertyRow({
  propKey,
  property,
  onValueChange,
  onKeyRename,
  onRemove,
  onOptionsChange,
}: {
  propKey: string
  property: TypedProperty
  onValueChange: (value: TypedProperty['value']) => void
  onKeyRename: (oldKey: string, newKey: string) => void
  onRemove: () => void
  onOptionsChange?: (options: string[]) => void
}) {
  return (
    <div className="flex items-center min-h-8 group/prop">
      <div className="flex items-center gap-2 w-24 shrink-0">
        <PropertyIcon type={property.type} />
        <input
          type="text"
          defaultValue={propKey}
          onBlur={(e) => onKeyRename(propKey, e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }}
          className="text-sm text-muted-foreground bg-transparent border-none outline-none w-full truncate"
        />
      </div>
      <PropertyValueEditor
        property={property}
        onChange={onValueChange}
        onOptionsChange={onOptionsChange}
      />
      <button
        onClick={onRemove}
        className="opacity-0 group-hover/prop:opacity-100 text-muted-foreground/40 hover:text-muted-foreground cursor-pointer p-0.5"
      >
        <X className="size-3" />
      </button>
    </div>
  )
}

export function AddPropertyButton({ onAdd }: { onAdd: (type: PropertyType) => void }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button className="flex items-center gap-2 h-7 text-sm text-muted-foreground/40 hover:text-muted-foreground transition-colors cursor-pointer">
          <Plus className="size-3.5" />
          <span>Add property</span>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuItem onClick={() => onAdd('text')}>
          <Type className="size-4" />Text
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => onAdd('number')}>
          <Hash className="size-4" />Number
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => onAdd('date')}>
          <CalendarIcon className="size-4" />Date
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => onAdd('checkbox')}>
          <CheckSquare className="size-4" />Checkbox
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => onAdd('select')}>
          <List className="size-4" />Select
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => onAdd('url')}>
          <LinkIcon className="size-4" />URL
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
