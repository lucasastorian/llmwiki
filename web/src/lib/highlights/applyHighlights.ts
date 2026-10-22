// Unmatched highlights are skipped, not deleted: they stay in JSONB and may resolve after future edits.

import type { Node as ProseMirrorNode } from '@tiptap/pm/model'

import { canonicalPlaintextFromTipTapDoc, type CanonicalPlaintext } from './canonicalPlaintext'
import { locateTextAnchor, normalizeAnchorText, type LocateInput } from './locator'
import type { DecorationRange, Highlight } from './types'

interface Offsets {
  start: number
  end: number
}

type Resolver = (h: Highlight, canonical: CanonicalPlaintext) => Offsets | null

function verifiedOffsets(h: Highlight, canonical: CanonicalPlaintext): Offsets | null {
  const ta = h.textAnchor
  if (!ta) return null
  const slice = canonical.text.slice(ta.textStart, ta.textEnd)
  if (slice.length === 0 || normalizeAnchorText(slice) !== normalizeAnchorText(ta.textContent)) return null
  return { start: ta.textStart, end: ta.textEnd }
}

function searchedOffsets(h: Highlight, canonical: CanonicalPlaintext): Offsets | null {
  const anchor = h.textAnchor ?? h.anchor
  if (!anchor) return null
  const search: LocateInput = { textContent: anchor.textContent, prefix: anchor.prefix, suffix: anchor.suffix }
  const located = locateTextAnchor(canonical.text, search)
  return located ? { start: located.textStart, end: located.textEnd } : null
}

function toRange(h: Highlight, canonical: CanonicalPlaintext, offsets: Offsets): DecorationRange | null {
  const from = canonical.offsetToPos(offsets.start, 'right')
  const to = canonical.offsetToPos(offsets.end, 'left')
  if (from === null || to === null || from >= to) return null
  return { id: h.id, from, to, comment: h.comment }
}

// Anchors saved before the list-separator change only verify against the legacy text, which maps onto the same doc.
// Exact offsets in either text outrank any search, so an old anchor never jumps to a later look-alike passage.
export function decorationsFromHighlights(highlights: Highlight[], doc: ProseMirrorNode): DecorationRange[] {
  const current = canonicalPlaintextFromTipTapDoc(doc)
  let legacy: CanonicalPlaintext | null = null
  const legacyText = (): CanonicalPlaintext => (legacy ??= canonicalPlaintextFromTipTapDoc(doc, true))
  const attempts: Array<[Resolver, () => CanonicalPlaintext]> = [
    [verifiedOffsets, () => current],
    [verifiedOffsets, legacyText],
    [searchedOffsets, () => current],
    [searchedOffsets, legacyText],
  ]

  const ranges: DecorationRange[] = []
  for (const h of highlights) {
    if (h.type === 'pdf') continue
    for (const [resolve, text] of attempts) {
      const canonical = text()
      const offsets = resolve(h, canonical)
      const range = offsets ? toRange(h, canonical, offsets) : null
      if (range) {
        ranges.push(range)
        break
      }
    }
  }
  return ranges
}
