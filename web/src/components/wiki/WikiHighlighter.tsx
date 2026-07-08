'use client'

import * as React from 'react'
import { Highlighter, Loader2, MessageSquarePlus, Pencil, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import {
  domPlaintextFromContainer,
  offsetAtDomPoint,
  offsetsFromRange,
  rangeFromOffsets,
  type DomPlaintext,
} from '@/lib/highlights/domPlaintext'
import { locateTextAnchor, normalizeAnchorText } from '@/lib/highlights/locator'
import { useWikiHighlights } from '@/hooks/useWikiHighlights'
import type { Highlight as HighlightModel, TextAnchor } from '@/lib/highlights/types'

const CONTEXT_CHARS = 80
const MAX_HIGHLIGHT_CHARS = 10000
const HIGHLIGHT_REGISTRY_KEY = 'wiki-highlight'
const NOTE_REGISTRY_KEY = 'wiki-highlight-note'

interface CardPosition {
  top: number
  bottom: number
  left: number
}

interface ResolvedHighlight {
  id: string
  start: number
  end: number
  comment: string | null
}

interface Props {
  scrollRef: React.RefObject<HTMLDivElement | null>
  contentRef: React.RefObject<HTMLDivElement | null>
  documentId: string
  contentKey: string
}

export function WikiHighlighter({ scrollRef, contentRef, documentId, contentKey }: Props) {
  const { highlights, saveHighlight, updateComment, removeHighlight } = useWikiHighlights(documentId)
  const [toolbar, setToolbar] = React.useState<(CardPosition & { anchor: TextAnchor }) | null>(null)
  const [composer, setComposer] = React.useState<(CardPosition & { anchor: TextAnchor }) | null>(null)
  const [active, setActive] = React.useState<(CardPosition & { id: string; comment: string | null }) | null>(null)
  const [editing, setEditing] = React.useState(false)
  const [draft, setDraft] = React.useState('')
  const [saving, setSaving] = React.useState(false)
  const [peek, setPeek] = React.useState<(CardPosition & { comment: string }) | null>(null)
  const resolvedRef = React.useRef<ResolvedHighlight[]>([])
  const dpRef = React.useRef<DomPlaintext | null>(null)
  const peekIdRef = React.useRef<string | null>(null)

  const supportsPainting = typeof CSS !== 'undefined' && 'highlights' in CSS

  // The paint-time plaintext snapshot dies whenever React swaps the rendered
  // DOM; hand out a rebuilt one when its nodes are no longer connected.
  const freshPlaintext = React.useCallback((content: HTMLElement): DomPlaintext => {
    const cached = dpRef.current
    if (
      cached &&
      cached.segments.length > 0 &&
      cached.segments[0].node.isConnected &&
      cached.segments[cached.segments.length - 1].node.isConnected
    ) {
      return cached
    }
    const dp = domPlaintextFromContainer(content)
    dpRef.current = dp
    return dp
  }, [])

  const paint = React.useCallback(() => {
    if (!supportsPainting) return
    const content = contentRef.current
    if (!content) return
    const dp = domPlaintextFromContainer(content)
    const resolved: ResolvedHighlight[] = []
    const plainRanges: Range[] = []
    const noteRanges: Range[] = []
    for (const h of highlights) {
      if (h.type === 'pdf') continue
      const offsets = resolveOffsets(h, dp)
      if (!offsets) continue
      const range = rangeFromOffsets(dp, offsets.start, offsets.end)
      if (!range) continue
      resolved.push({ id: h.id, start: offsets.start, end: offsets.end, comment: h.comment })
      if (h.comment) noteRanges.push(range)
      else plainRanges.push(range)
    }
    resolvedRef.current = resolved
    dpRef.current = dp
    CSS.highlights.set(HIGHLIGHT_REGISTRY_KEY, new window.Highlight(...plainRanges))
    CSS.highlights.set(NOTE_REGISTRY_KEY, new window.Highlight(...noteRanges))
  }, [contentRef, highlights, supportsPainting])

  // Repaint on data/page changes, and on DOM mutations (images resolving,
  // Mermaid hydrating) that replace the text nodes our Ranges point at.
  React.useEffect(() => {
    if (!supportsPainting) return
    const content = contentRef.current
    if (!content) return
    let raf = requestAnimationFrame(paint)
    const observer = new MutationObserver(() => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(paint)
    })
    observer.observe(content, { childList: true, subtree: true, characterData: true })
    return () => {
      observer.disconnect()
      cancelAnimationFrame(raf)
    }
  }, [paint, contentRef, contentKey, supportsPainting])

  React.useEffect(() => {
    if (!supportsPainting) return
    return () => {
      CSS.highlights.delete(HIGHLIGHT_REGISTRY_KEY)
      CSS.highlights.delete(NOTE_REGISTRY_KEY)
    }
  }, [supportsPainting])

  // Close any open card when navigating to another page.
  React.useEffect(() => {
    setToolbar(null)
    setComposer(null)
    setActive(null)
    setEditing(false)
    setDraft('')
    peekIdRef.current = null
    setPeek(null)
  }, [contentKey, documentId])

  const localPosition = React.useCallback(
    (rect: DOMRect): CardPosition | null => {
      const container = scrollRef.current
      if (!container) return null
      const containerRect = container.getBoundingClientRect()
      // Clamp to half the widest card (w-[26rem] = 416px) plus a small margin.
      const halfCard = 216
      const left = Math.min(
        Math.max(rect.left - containerRect.left + rect.width / 2, halfCard),
        Math.max(container.clientWidth - halfCard, halfCard),
      )
      return {
        top: rect.top - containerRect.top + container.scrollTop,
        bottom: rect.bottom - containerRect.top + container.scrollTop,
        left,
      }
    },
    [scrollRef],
  )

  // rAF-debounced: selectionchange fires on every drag tick, and reading the
  // anchor walks the page's text nodes each time.
  React.useEffect(() => {
    let raf = 0
    const handleSelectionChange = () => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => {
        const selectionAnchor = readSelectionAnchor(contentRef.current)
        if (!selectionAnchor) {
          setToolbar(null)
          return
        }
        const position = localPosition(selectionAnchor.rect)
        if (!position) return
        setToolbar({ ...position, anchor: selectionAnchor.anchor })
      })
    }
    document.addEventListener('selectionchange', handleSelectionChange)
    return () => {
      cancelAnimationFrame(raf)
      document.removeEventListener('selectionchange', handleSelectionChange)
    }
  }, [contentRef, localPosition])

  // Click on painted text opens the comment card for that highlight.
  React.useEffect(() => {
    const container = scrollRef.current
    if (!container) return
    const handleClick = (event: MouseEvent) => {
      const target = event.target as HTMLElement
      if (target.closest('[data-wiki-highlighter]')) return
      if (target.closest('a, button')) return
      const selection = window.getSelection()
      if (selection && !selection.isCollapsed) return
      const content = contentRef.current
      if (!content || !content.contains(target)) {
        setActive(null)
        setEditing(false)
        return
      }
      const hit = hitTestHighlight(freshPlaintext(content), event, resolvedRef.current)
      if (!hit) {
        setActive(null)
        setEditing(false)
        return
      }
      const position = localPosition(new DOMRect(event.clientX, event.clientY, 0, 0))
      if (!position) return
      setToolbar(null)
      setEditing(false)
      setDraft(hit.comment ?? '')
      peekIdRef.current = null
      setPeek(null)
      setActive({ ...position, id: hit.id, comment: hit.comment })
    }
    container.addEventListener('click', handleClick)
    return () => container.removeEventListener('click', handleClick)
  }, [contentRef, freshPlaintext, localPosition, scrollRef])

  // Hovering a noted highlight peeks its comment; click still opens the
  // editable card. Uses the paint-time plaintext cache, so mousemove stays cheap.
  React.useEffect(() => {
    const container = scrollRef.current
    if (!container) return
    let raf = 0
    const clearPeek = () => {
      if (!peekIdRef.current) return
      peekIdRef.current = null
      setPeek(null)
    }
    const handleMove = (event: MouseEvent) => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => {
        if (toolbar || composer || active) {
          clearPeek()
          return
        }
        const content = contentRef.current
        if (!content || !(event.target instanceof Node) || !content.contains(event.target)) {
          clearPeek()
          return
        }
        const hit = hitTestHighlight(freshPlaintext(content), event, resolvedRef.current)
        if (!hit?.comment) {
          clearPeek()
          return
        }
        if (peekIdRef.current === hit.id) return
        const position = localPosition(new DOMRect(event.clientX, event.clientY, 0, 0))
        if (!position) return
        peekIdRef.current = hit.id
        setPeek({ ...position, comment: hit.comment })
      })
    }
    container.addEventListener('mousemove', handleMove)
    container.addEventListener('mouseleave', clearPeek)
    return () => {
      cancelAnimationFrame(raf)
      container.removeEventListener('mousemove', handleMove)
      container.removeEventListener('mouseleave', clearPeek)
    }
  }, [active, composer, contentRef, freshPlaintext, localPosition, scrollRef, toolbar])

  React.useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setToolbar(null)
      setComposer(null)
      setActive(null)
      setEditing(false)
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [])

  const runSave = React.useCallback(
    async (action: () => Promise<void>, failure: string): Promise<boolean> => {
      setSaving(true)
      try {
        await action()
        return true
      } catch (err) {
        toast.error(err instanceof Error ? err.message : failure)
        return false
      } finally {
        setSaving(false)
      }
    },
    [],
  )

  const handleHighlight = React.useCallback(async () => {
    if (!toolbar) return
    const ok = await runSave(() => saveHighlight(toolbar.anchor, null), 'Failed to save highlight')
    if (!ok) return
    window.getSelection()?.removeAllRanges()
    setToolbar(null)
  }, [runSave, saveHighlight, toolbar])

  const handleOpenComposer = React.useCallback(() => {
    if (!toolbar) return
    setDraft('')
    setComposer(toolbar)
    setToolbar(null)
    window.getSelection()?.removeAllRanges()
  }, [toolbar])

  const handleComposerSave = React.useCallback(async () => {
    if (!composer) return
    const ok = await runSave(() => saveHighlight(composer.anchor, draft), 'Failed to save note')
    if (!ok) return
    setComposer(null)
    setDraft('')
  }, [composer, draft, runSave, saveHighlight])

  const handleCommentSave = React.useCallback(async () => {
    if (!active) return
    const ok = await runSave(() => updateComment(active.id, draft), 'Failed to save note')
    if (!ok) return
    setActive({ ...active, comment: draft.trim() || null })
    setEditing(false)
  }, [active, draft, runSave, updateComment])

  const handleDelete = React.useCallback(async () => {
    if (!active) return
    const ok = await runSave(() => removeHighlight(active.id), 'Failed to remove highlight')
    if (!ok) return
    setActive(null)
    setEditing(false)
  }, [active, removeHighlight, runSave])

  return (
    <>
      {peek && (
        <div
          data-wiki-highlighter
          className="pointer-events-none absolute z-20 w-max max-w-[26rem] -translate-x-1/2 whitespace-pre-wrap rounded-md border border-border bg-popover px-3 py-2 text-[13px] leading-relaxed text-popover-foreground shadow-md"
          style={{ top: peek.bottom + 10, left: peek.left }}
        >
          {peek.comment}
        </div>
      )}

      {toolbar && !composer && (
        <div
          data-wiki-highlighter
          className="absolute z-30 flex -translate-x-1/2 -translate-y-full items-center gap-0.5 rounded-md border border-border bg-popover p-0.5 shadow-md"
          style={{ top: toolbar.top - 8, left: toolbar.left }}
          onMouseDown={(event) => event.preventDefault()}
        >
          <Button
            variant="ghost"
            size="icon"
            className="size-7"
            title="Highlight"
            disabled={saving}
            onClick={handleHighlight}
          >
            {saving ? <Loader2 className="size-3.5 animate-spin" /> : <Highlighter className="size-3.5" />}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="size-7"
            title="Highlight with note"
            disabled={saving}
            onClick={handleOpenComposer}
          >
            <MessageSquarePlus className="size-3.5" />
          </Button>
        </div>
      )}

      {composer && (
        <div
          data-wiki-highlighter
          className="absolute z-30 w-[26rem] -translate-x-1/2 rounded-md border border-border bg-popover p-3 shadow-md"
          style={{ top: composer.bottom + 8, left: composer.left }}
        >
          <Textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="What's unclear here?"
            rows={5}
            maxLength={4000}
            className="max-h-72 min-h-28 resize-y text-sm"
            autoFocus
          />
          <div className="mt-2.5 flex justify-end gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setComposer(null)
                setDraft('')
              }}
            >
              Cancel
            </Button>
            <Button size="sm" disabled={saving} onClick={handleComposerSave}>
              {saving && <Loader2 className="size-3 animate-spin" />}
              Save
            </Button>
          </div>
        </div>
      )}

      {active && (
        <div
          data-wiki-highlighter
          className="absolute z-30 w-[26rem] -translate-x-1/2 rounded-md border border-border bg-popover p-3 shadow-md"
          style={{ top: active.bottom + 12, left: active.left }}
        >
          {editing ? (
            <>
              <Textarea
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="What's unclear here?"
                rows={5}
                maxLength={4000}
                className="max-h-72 min-h-28 resize-y text-sm"
                autoFocus
              />
              <div className="mt-2.5 flex justify-end gap-2">
                <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>
                  Cancel
                </Button>
                <Button size="sm" disabled={saving} onClick={handleCommentSave}>
                  {saving && <Loader2 className="size-3 animate-spin" />}
                  Save
                </Button>
              </div>
            </>
          ) : (
            <div className="flex items-start gap-2">
              <p
                className={cn(
                  'flex-1 min-w-0 text-sm leading-relaxed whitespace-pre-wrap',
                  active.comment ? 'text-foreground' : 'italic text-muted-foreground',
                )}
              >
                {active.comment ?? 'No note'}
              </p>
              <div className="flex shrink-0 gap-0.5">
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-7"
                  title={active.comment ? 'Edit note' : 'Add note'}
                  onClick={() => {
                    setDraft(active.comment ?? '')
                    setEditing(true)
                  }}
                >
                  <Pencil className="size-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-7 text-muted-foreground hover:text-destructive"
                  title="Remove highlight"
                  disabled={saving}
                  onClick={handleDelete}
                >
                  {saving ? <Loader2 className="size-3.5 animate-spin" /> : <Trash2 className="size-3.5" />}
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </>
  )
}

function resolveOffsets(h: HighlightModel, dp: DomPlaintext): { start: number; end: number } | null {
  if (h.textAnchor) {
    const ta = h.textAnchor
    const slice = dp.text.slice(ta.textStart, ta.textEnd)
    if (slice.length > 0 && normalizeAnchorText(slice) === normalizeAnchorText(ta.textContent)) {
      return { start: ta.textStart, end: ta.textEnd }
    }
  }
  const search = h.textAnchor ?? h.anchor
  if (!search) return null
  const located = locateTextAnchor(dp.text, {
    textContent: search.textContent,
    prefix: search.prefix,
    suffix: search.suffix,
  })
  if (!located) return null
  return { start: located.textStart, end: located.textEnd }
}

function readSelectionAnchor(
  content: HTMLElement | null,
): { anchor: TextAnchor; rect: DOMRect } | null {
  if (!content) return null
  const selection = window.getSelection()
  if (!selection || selection.isCollapsed || selection.rangeCount === 0) return null
  const range = selection.getRangeAt(0)
  if (!content.contains(range.startContainer) || !content.contains(range.endContainer)) return null

  const dp = domPlaintextFromContainer(content)
  const offsets = offsetsFromRange(dp, range)
  if (!offsets) return null

  let { start, end } = offsets
  while (start < end && /\s/.test(dp.text[start])) start += 1
  while (end > start && /\s/.test(dp.text[end - 1])) end -= 1
  if (end <= start || end - start > MAX_HIGHLIGHT_CHARS) return null

  return {
    anchor: {
      textStart: start,
      textEnd: end,
      textContent: dp.text.slice(start, end),
      prefix: dp.text.slice(Math.max(0, start - CONTEXT_CHARS), start) || null,
      suffix: dp.text.slice(end, end + CONTEXT_CHARS) || null,
    },
    rect: range.getBoundingClientRect(),
  }
}

function hitTestHighlight(
  dp: DomPlaintext,
  event: MouseEvent,
  resolved: ResolvedHighlight[],
): ResolvedHighlight | null {
  if (resolved.length === 0) return null
  const point = caretPointFromEvent(event)
  if (!point) return null
  const offset = offsetAtDomPoint(dp, point.node, point.offset)
  if (offset === null) return null
  // Accept offset === end: the caret for a click on the last glyph often
  // lands on the trailing insertion point.
  return resolved.find((r) => offset >= r.start && offset <= r.end) ?? null
}

function caretPointFromEvent(event: MouseEvent): { node: Node; offset: number } | null {
  if (typeof document.caretPositionFromPoint === 'function') {
    const position = document.caretPositionFromPoint(event.clientX, event.clientY)
    if (!position) return null
    return { node: position.offsetNode, offset: position.offset }
  }
  const legacy = (document as Document & { caretRangeFromPoint?: (x: number, y: number) => Range | null })
    .caretRangeFromPoint?.(event.clientX, event.clientY)
  if (!legacy) return null
  return { node: legacy.startContainer, offset: legacy.startOffset }
}
