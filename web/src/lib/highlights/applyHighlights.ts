// Glue between the canonical plaintext walker, the locator, and the
// decoration plugin. Given the highlight array from the API plus a
// CanonicalPlaintext of the current TipTap doc, returns the DecorationRanges
// to dispatch.
//
// Resolution priority for each highlight:
//   1. textAnchor (V2): map (textStart, textEnd) directly via posMap, but
//      verify the slice still equals textAnchor.textContent — fall back to
//      runtime locate if stale.
//   2. textAnchor missing or stale: locate via textContent + prefix/suffix
//      against the canonical plaintext.
//   3. V1 highlight (no textAnchor, only DOM `anchor`): same locate using
//      `anchor.textContent` + prefix/suffix.
//   4. Nothing matches → skip silently (the highlight stays in JSONB; future
//      content updates may resurrect it).

import type { CanonicalPlaintext } from './canonicalPlaintext'
import { locateTextAnchor, normalizeAnchorText } from './locator'
import type { DecorationRange, Highlight } from './types'

function resolveOne(h: Highlight, canonical: CanonicalPlaintext): DecorationRange | null {
  let textStart: number | null = null
  let textEnd: number | null = null

  if (h.textAnchor) {
    const ta = h.textAnchor
    const slice = canonical.text.slice(ta.textStart, ta.textEnd)
    if (
      slice.length > 0 &&
      normalizeAnchorText(slice) === normalizeAnchorText(ta.textContent)
    ) {
      textStart = ta.textStart
      textEnd = ta.textEnd
    }
  }

  if (textStart === null || textEnd === null) {
    const search = h.textAnchor
      ? { textContent: h.textAnchor.textContent, prefix: h.textAnchor.prefix, suffix: h.textAnchor.suffix }
      : h.anchor
        ? { textContent: h.anchor.textContent, prefix: h.anchor.prefix, suffix: h.anchor.suffix }
        : null
    if (!search) return null
    const located = locateTextAnchor(canonical.text, search)
    if (!located) return null
    textStart = located.textStart
    textEnd = located.textEnd
  }

  const from = canonical.offsetToPos(textStart, 'right')
  const to = canonical.offsetToPos(textEnd, 'left')
  if (from === null || to === null || from >= to) return null

  return { id: h.id, from, to }
}

export function decorationsFromHighlights(
  highlights: Highlight[],
  canonical: CanonicalPlaintext,
): DecorationRange[] {
  const ranges: DecorationRange[] = []
  for (const h of highlights) {
    if (h.type === 'pdf') continue // V3
    const r = resolveOne(h, canonical)
    if (r) ranges.push(r)
  }
  return ranges
}
