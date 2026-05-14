// TypeScript port of api/html_parser/parser.py:_locate_highlight.
// Used by the wiki viewer when:
//   1. A V1 highlight has no `textAnchor` (DOM-only) — search by textContent
//   2. A V2 highlight's textAnchor verifies stale (markdown changed since save)
//
// The algorithm matches the server: normalize whitespace via a normalize+
// index-map, search the normalized haystack, score multi-occurrences via
// prefix/suffix context, refuse short ambiguous matches without context.

const MIN_AUTO_LOCATE_LEN = 4
const MAX_OCCURRENCES = 500

// U+200B zero-width space, U+FEFF zero-width no-break space (BOM).
const ZERO_WIDTH_RE = /[​﻿]/g
// U+00A0 non-breaking space → regular space.
const NBSP_RE = / /g
const WS_RE = /\s+/g

export function normalizeAnchorText(s: string): string {
  if (!s) return ''
  return s
    .replace(ZERO_WIDTH_RE, '')
    .replace(NBSP_RE, ' ')
    .replace(WS_RE, ' ')
    .trim()
}

interface NormalizedHaystack {
  text: string
  /** indexMap[i] = original-text position of normalized[i]; the last entry is
   *  the original-text length (so end-exclusive offsets have a mapping). */
  indexMap: number[]
}

function isWhitespace(ch: string): boolean {
  return (
    ch === ' ' ||
    ch === '\t' ||
    ch === '\n' ||
    ch === '\r' ||
    ch === ' ' /* nbsp */
  )
}

function isZeroWidth(ch: string): boolean {
  // Match the chars stripped by normalizeAnchorText so the haystack and the
  // needle agree on character composition.
  return ch === '​' || ch === '﻿'
}

function normalizeWithIndexMap(plaintext: string): NormalizedHaystack {
  const out: string[] = []
  const indexMap: number[] = []
  let prevWasWs = true
  for (let i = 0; i < plaintext.length; i++) {
    const ch = plaintext[i]
    if (isZeroWidth(ch)) {
      // Drop entirely — matches normalizeAnchorText behavior on the needle.
      continue
    }
    if (isWhitespace(ch)) {
      if (!prevWasWs && out.length) {
        out.push(' ')
        indexMap.push(i)
      }
      prevWasWs = true
      continue
    }
    out.push(ch)
    indexMap.push(i)
    prevWasWs = false
  }
  // Trailing entry so end-exclusive offsets have a mapping.
  indexMap.push(plaintext.length)
  let normalized = out.join('')
  if (normalized.endsWith(' ')) {
    normalized = normalized.slice(0, -1)
    indexMap.splice(indexMap.length - 2, 1)
  }
  return { text: normalized, indexMap }
}

function allOccurrences(haystack: string, needle: string, cap: number): number[] {
  if (!needle) return []
  const out: number[] = []
  let start = 0
  while (out.length < cap) {
    const idx = haystack.indexOf(needle, start)
    if (idx === -1) break
    out.push(idx)
    start = idx + 1
  }
  return out
}

function scoreContext(
  normalizedHaystack: string,
  idx: number,
  length: number,
  prefix: string | null | undefined,
  suffix: string | null | undefined,
): number {
  let score = 0
  if (prefix) {
    const np = normalizeAnchorText(prefix)
    if (np) {
      const window = Math.max(np.length, 32)
      const before = normalizedHaystack.slice(Math.max(0, idx - window), idx)
      if (before.endsWith(np)) score += 4
      else if (before.includes(np)) score += 1
    }
  }
  if (suffix) {
    const ns = normalizeAnchorText(suffix)
    if (ns) {
      const window = Math.max(ns.length, 32)
      const after = normalizedHaystack.slice(idx + length, idx + length + window)
      if (after.startsWith(ns)) score += 4
      else if (after.includes(ns)) score += 1
    }
  }
  return score
}

export interface LocateInput {
  textContent: string
  prefix?: string | null
  suffix?: string | null
}

export interface LocateResult {
  textStart: number
  textEnd: number
  textContent: string
}

export function locateTextAnchor(
  plaintext: string,
  input: LocateInput,
): LocateResult | null {
  const needle = normalizeAnchorText(input.textContent)
  if (!needle) return null

  const { text: haystack, indexMap } = normalizeWithIndexMap(plaintext)
  const occurrences = allOccurrences(haystack, needle, MAX_OCCURRENCES)
  if (occurrences.length === 0) return null

  let chosen: number
  if (occurrences.length === 1) {
    chosen = occurrences[0]
  } else {
    let bestScore = -1
    let bestIdx = occurrences[0]
    for (const occ of occurrences) {
      const s = scoreContext(haystack, occ, needle.length, input.prefix, input.suffix)
      if (s > bestScore) {
        bestScore = s
        bestIdx = occ
      }
    }
    if (needle.length < MIN_AUTO_LOCATE_LEN && bestScore === 0) {
      return null
    }
    chosen = bestIdx
  }

  const textStart = chosen < indexMap.length ? indexMap[chosen] : chosen
  const endNormIdx = chosen + needle.length
  const textEnd = endNormIdx < indexMap.length ? indexMap[endNormIdx] : plaintext.length

  return {
    textStart,
    textEnd,
    textContent: plaintext.slice(textStart, textEnd),
  }
}
