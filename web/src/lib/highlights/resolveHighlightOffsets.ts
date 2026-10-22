import { locateTextAnchor, normalizeAnchorText } from './locator'
import type { DomPlaintext } from './domPlaintext'
import type { Highlight } from './types'

// Saved offsets win while they verify; drifted markdown falls back to context search.
export function resolveHighlightOffsets(
  h: Highlight,
  dp: DomPlaintext,
): { start: number; end: number } | null {
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
