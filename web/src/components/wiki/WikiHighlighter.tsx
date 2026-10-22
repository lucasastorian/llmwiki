'use client'

import * as React from 'react'
import { Copy, Highlighter, MessageSquarePlus, Trash2, X } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Kbd } from '@/components/ui/kbd'
import { Textarea } from '@/components/ui/textarea'
import {
  domPlaintextFromContainer,
  offsetAtDomPoint,
  offsetsFromRange,
  rangeFromOffsets,
  type DomPlaintext,
} from '@/lib/highlights/domPlaintext'
import { resolveHighlightOffsets } from '@/lib/highlights/resolveHighlightOffsets'
import { ReplyThread } from './ReplyThread'
import type { WikiHighlightsApi } from '@/hooks/useWikiHighlights'
import type { HighlightReply, TextAnchor } from '@/lib/highlights/types'

const CONTEXT_CHARS = 80
const MAX_HIGHLIGHT_CHARS = 10000
const HIGHLIGHT_REGISTRY_KEY = 'wiki-highlight'
const NOTE_REGISTRY_KEY = 'wiki-highlight-note'

interface CardPosition {
  top: number
  bottom: number
  left: number
}

type PendingSelection = CardPosition & { anchor: TextAnchor }

type ActiveCard = CardPosition & {
  comment: string | null
  replies: HighlightReply[]
} & (
    | { mode: 'create'; anchor: TextAnchor }
    | { mode: 'edit'; id: string }
  )

interface ResolvedHighlight {
  id: string
  start: number
  end: number
  comment: string | null
  replies: HighlightReply[]
}

function ComposerHint() {
  return (
    <span className="text-[11px] text-muted-foreground/60">
      <Kbd>↵</Kbd> save · <Kbd>⇧↵</Kbd> line · <Kbd>esc</Kbd> dismiss
    </span>
  )
}

interface Props {
  scrollRef: React.RefObject<HTMLDivElement | null>
  contentRef: React.RefObject<HTMLDivElement | null>
  documentId: string
  contentKey: string
  api: WikiHighlightsApi
}

export function WikiHighlighter({ scrollRef, contentRef, documentId, contentKey, api }: Props) {
  const { highlights, saveHighlight, updateComment, removeHighlight } = api
  const [pending, setPending] = React.useState<PendingSelection | null>(null)
  const [active, setActive] = React.useState<ActiveCard | null>(null)
  const [draft, setDraft] = React.useState('')
  const [peek, setPeek] = React.useState<(CardPosition & { comment: string | null; replies: HighlightReply[] }) | null>(null)
  const resolvedRef = React.useRef<ResolvedHighlight[]>([])
  const dpRef = React.useRef<DomPlaintext | null>(null)
  const peekIdRef = React.useRef<string | null>(null)
  const lastAnchorRef = React.useRef<TextAnchor | null>(null)

  const supportsPainting = typeof CSS !== 'undefined' && 'highlights' in CSS

  // The cached snapshot goes stale whenever React swaps the rendered DOM.
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
      const offsets = resolveHighlightOffsets(h, dp)
      if (!offsets) continue
      const range = rangeFromOffsets(dp, offsets.start, offsets.end)
      if (!range) continue
      const replies = h.replies ?? []
      resolved.push({ id: h.id, start: offsets.start, end: offsets.end, comment: h.comment, replies })
      if (h.comment || replies.length > 0) noteRanges.push(range)
      else plainRanges.push(range)
    }
    resolvedRef.current = resolved
    dpRef.current = dp
    CSS.highlights.set(HIGHLIGHT_REGISTRY_KEY, new window.Highlight(...plainRanges))
    CSS.highlights.set(NOTE_REGISTRY_KEY, new window.Highlight(...noteRanges))
  }, [contentRef, highlights, supportsPainting])

  // DOM mutations (images resolving, Mermaid hydrating) replace the text nodes our Ranges point at.
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

  React.useEffect(() => {
    setPending(null)
    setActive(null)
    setDraft('')
    peekIdRef.current = null
    lastAnchorRef.current = null
    setPeek(null)
  }, [contentKey, documentId])

  const localPosition = React.useCallback(
    (rect: DOMRect): CardPosition | null => {
      const container = scrollRef.current
      if (!container) return null
      const containerRect = container.getBoundingClientRect()
      // Half the widest card (w-[26rem] = 416px) plus a margin.
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

  // useWikiHighlights paints optimistically and rolls back on failure.
  const persist = React.useCallback((action: () => Promise<void>, failure: string): void => {
    action().catch((err: unknown) => {
      toast.error(err instanceof Error ? err.message : failure)
    })
  }, [])

  // The selection stays native so Cmd/Ctrl+C works without persisting a highlight.
  React.useEffect(() => {
    const container = scrollRef.current
    if (!container) return
    const handlePointerUp = (event: PointerEvent) => {
      const target = event.target as HTMLElement
      if (target.closest('[data-wiki-highlighter]')) return
      // The selection settles after pointerup, including double/triple click.
      requestAnimationFrame(() => {
        const selectionAnchor = readSelectionAnchor(contentRef.current)
        if (!selectionAnchor) return
        const { anchor } = selectionAnchor
        const last = lastAnchorRef.current
        if (last && last.textStart === anchor.textStart && last.textEnd === anchor.textEnd) return
        const position = localPosition(selectionAnchor.rect)
        if (!position) return
        lastAnchorRef.current = anchor
        setActive(null)
        setPending({ ...position, anchor })
      })
    }
    container.addEventListener('pointerup', handlePointerUp)
    return () => container.removeEventListener('pointerup', handlePointerUp)
  }, [contentRef, localPosition, scrollRef])

  React.useEffect(() => {
    const container = scrollRef.current
    if (!container) return
    const handleClick = (event: MouseEvent) => {
      const target = event.target as HTMLElement
      if (target.closest('[data-wiki-highlighter]')) return
      if (target.closest('a, button')) return
      const selection = window.getSelection()
      if (selection && !selection.isCollapsed) return
      lastAnchorRef.current = null
      const content = contentRef.current
      if (!content || !content.contains(target)) {
        setPending(null)
        setActive(null)
        return
      }
      const hit = hitTestHighlight(freshPlaintext(content), event, resolvedRef.current)
      if (!hit) {
        setPending(null)
        setActive(null)
        return
      }
      const position = localPosition(new DOMRect(event.clientX, event.clientY, 0, 0))
      if (!position) return
      setPending(null)
      setDraft(hit.comment ?? '')
      peekIdRef.current = null
      setPeek(null)
      setActive({ ...position, mode: 'edit', id: hit.id, comment: hit.comment, replies: hit.replies })
    }
    container.addEventListener('click', handleClick)
    return () => container.removeEventListener('click', handleClick)
  }, [contentRef, freshPlaintext, localPosition, scrollRef])

  // Uses the paint-time plaintext cache so mousemove stays cheap.
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
        if (pending || active) {
          clearPeek()
          return
        }
        const content = contentRef.current
        if (!content || !(event.target instanceof Node) || !content.contains(event.target)) {
          clearPeek()
          return
        }
        const hit = hitTestHighlight(freshPlaintext(content), event, resolvedRef.current)
        if (!hit || (!hit.comment && hit.replies.length === 0)) {
          clearPeek()
          return
        }
        if (peekIdRef.current === hit.id) return
        const position = localPosition(new DOMRect(event.clientX, event.clientY, 0, 0))
        if (!position) return
        peekIdRef.current = hit.id
        setPeek({ ...position, comment: hit.comment, replies: hit.replies })
      })
    }
    container.addEventListener('mousemove', handleMove)
    container.addEventListener('mouseleave', clearPeek)
    return () => {
      cancelAnimationFrame(raf)
      container.removeEventListener('mousemove', handleMove)
      container.removeEventListener('mouseleave', clearPeek)
    }
  }, [active, contentRef, pending, freshPlaintext, localPosition, scrollRef])

  const clearPending = React.useCallback(() => {
    window.getSelection()?.removeAllRanges()
    lastAnchorRef.current = null
    setPending(null)
  }, [])

  const handlePendingHighlight = React.useCallback(() => {
    if (!pending) return
    const { anchor } = pending
    clearPending()
    persist(() => saveHighlight(anchor, null), 'Failed to save highlight')
  }, [clearPending, pending, persist, saveHighlight])

  const handlePendingNote = React.useCallback(() => {
    if (!pending) return
    const { anchor, top, bottom, left } = pending
    clearPending()
    setDraft('')
    setActive({ top, bottom, left, mode: 'create', anchor, comment: null, replies: [] })
  }, [clearPending, pending])

  const handlePendingCopy = React.useCallback(async () => {
    if (!pending) return
    try {
      await copyText(pending.anchor.textContent)
      clearPending()
      toast.success('Copied')
    } catch {
      toast.error('Could not copy selection')
    }
  }, [clearPending, pending])

  React.useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        // Escape must not destroy unrelated user selections.
        if (pending) clearPending()
        if (active) setActive(null)
        return
      }

      const target = event.target
      if (target instanceof Element && target.closest('input, textarea, [contenteditable]')) return
      if (!pending || event.metaKey || event.ctrlKey || event.altKey) return
      if (event.key.toLowerCase() === 'h') {
        event.preventDefault()
        handlePendingHighlight()
      } else if (event.key.toLowerCase() === 'n') {
        event.preventDefault()
        handlePendingNote()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [active, clearPending, handlePendingHighlight, handlePendingNote, pending])

  const handleCommentSave = React.useCallback(() => {
    if (!active) return
    setActive(null)
    if (active.mode === 'create') {
      persist(() => saveHighlight(active.anchor, draft), 'Failed to save note')
    } else {
      persist(() => updateComment(active.id, draft), 'Failed to save note')
    }
  }, [active, draft, persist, saveHighlight, updateComment])

  const saveOnEnter = React.useCallback(
    (save: () => void) => (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key !== 'Enter' || event.shiftKey) return
      event.preventDefault()
      save()
    },
    [],
  )

  const handleDelete = React.useCallback(() => {
    if (!active || active.mode !== 'edit') return
    setActive(null)
    persist(() => removeHighlight(active.id), 'Failed to remove highlight')
  }, [active, persist, removeHighlight])

  const handleCommentCancel = React.useCallback(() => {
    setActive(null)
    setDraft('')
  }, [])

  return (
    <>
      {peek && (
        <div
          data-wiki-highlighter
          className="pointer-events-none absolute z-20 w-max max-w-[26rem] -translate-x-1/2"
          style={{ top: peek.bottom + 10, left: peek.left }}
        >
          <div className="animate-in fade-in-0 duration-100 rounded-md border border-border bg-popover px-3 py-2 shadow-md">
            {peek.comment && (
              <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-popover-foreground">
                {peek.comment}
              </p>
            )}
            <ReplyThread replies={peek.replies} />
          </div>
        </div>
      )}

      {pending && (
        <div
          data-wiki-highlighter
          className="absolute z-30 -translate-x-1/2 -translate-y-full"
          style={{ top: pending.top - 8, left: pending.left }}
          onMouseDown={(event) => event.preventDefault()}
        >
          <div className="animate-in fade-in-0 zoom-in-95 duration-100 flex items-center gap-0.5 rounded-md border border-border bg-popover p-0.5 shadow-md">
            <Button
              variant="ghost"
              size="icon"
              className="size-7"
              title="Highlight (H)"
              aria-label="Highlight selected text"
              aria-keyshortcuts="H"
              onClick={handlePendingHighlight}
            >
              <Highlighter className="size-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="size-7"
              title="Add note (N)"
              aria-label="Add note to selected text"
              aria-keyshortcuts="N"
              onClick={handlePendingNote}
            >
              <MessageSquarePlus className="size-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="size-7"
              title="Copy (Cmd/Ctrl+C)"
              aria-label="Copy selected text"
              aria-keyshortcuts="Meta+C Control+C"
              onClick={() => void handlePendingCopy()}
            >
              <Copy className="size-3.5" />
            </Button>
          </div>
        </div>
      )}

      {active && (
        <div
          data-wiki-highlighter
          className="absolute z-30 w-[26rem] -translate-x-1/2"
          style={{ top: active.bottom + 12, left: active.left }}
        >
          <div className="animate-in fade-in-0 zoom-in-95 slide-in-from-top-1 duration-150 rounded-md border border-border bg-popover p-3 shadow-md">
            {active.replies.length > 0 && (
              <div className="mb-2.5 max-h-40 overflow-y-auto">
                <ReplyThread replies={active.replies} />
              </div>
            )}
            <Textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={saveOnEnter(handleCommentSave)}
              onFocus={(event) => {
                const el = event.currentTarget
                el.setSelectionRange(el.value.length, el.value.length)
              }}
              placeholder="What's unclear here?"
              rows={5}
              maxLength={4000}
              className="max-h-72 min-h-28 resize-y text-sm"
              autoFocus
            />
            <div className="mt-2 flex items-center justify-between">
              {active.mode === 'edit' ? (
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-7 text-muted-foreground hover:text-destructive"
                  title="Remove highlight"
                  aria-label="Remove highlight"
                  onClick={handleDelete}
                >
                  <Trash2 className="size-3.5" />
                </Button>
              ) : (
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-7 text-muted-foreground"
                  title="Cancel note"
                  aria-label="Cancel note"
                  onClick={handleCommentCancel}
                >
                  <X className="size-3.5" />
                </Button>
              )}
              <ComposerHint />
            </div>
          </div>
        </div>
      )}
    </>
  )
}

async function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return
    } catch {
      // Fall back to the browser's selection-based copy path.
    }
  }
  if (!document.execCommand('copy')) throw new Error('Clipboard unavailable')
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
  // offset === end: a click on the last glyph often lands on the trailing caret position.
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
