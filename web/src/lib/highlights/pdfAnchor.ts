// PDF highlight anchor helpers.
//
// Storage is in PDF user-space points (1/72"), zoom/rotation-independent.
// Viewport rects are derived at render time from the page's current viewport
// transform.

import type { PdfRect } from './types'

interface PdfJsViewport {
  convertToPdfPoint: (x: number, y: number) => [number, number]
  convertToViewportRectangle: (rect: [number, number, number, number]) => [number, number, number, number]
}

const PREFIX_CHARS = 20
const SUFFIX_CHARS = 20

function normalizeWhitespace(value: string): string {
  return value.replace(/\s+/g, ' ').trim()
}

/**
 * Convert one viewport-pixel rect (e.g. from Range.getClientRects) into a PDF
 * user-space rect via the page's viewport transform. Caller is responsible
 * for translating viewport coords into the page-local container's coords
 * before calling (subtract the page element's bounding rect).
 */
function viewportRectToPdf(rect: { x: number; y: number; width: number; height: number }, viewport: PdfJsViewport): PdfRect {
  const [px1, py1] = viewport.convertToPdfPoint(rect.x, rect.y)
  const [px2, py2] = viewport.convertToPdfPoint(rect.x + rect.width, rect.y + rect.height)
  const x = Math.min(px1, px2)
  const y = Math.min(py1, py2)
  const width = Math.abs(px2 - px1)
  const height = Math.abs(py2 - py1)
  return { x, y, width, height }
}

interface ComputeAnchorArgs {
  range: Range
  viewport: PdfJsViewport
  pageContainer: HTMLElement
  pageText: string
}

/**
 * Compute a PDF-space anchor from a live DOM selection in the text layer.
 * Returns null if the selection is empty or has no client rects.
 */
export function computePdfAnchor({ range, viewport, pageContainer, pageText }: ComputeAnchorArgs): {
  textStart: number | null
  textEnd: number | null
  textContent: string
  prefix: string | null
  suffix: string | null
  rects: PdfRect[]
} | null {
  const textContent = normalizeWhitespace(range.toString())
  if (!textContent) return null

  const clientRects = Array.from(range.getClientRects())
  if (clientRects.length === 0) return null

  const containerRect = pageContainer.getBoundingClientRect()
  const rects: PdfRect[] = []
  for (const r of clientRects) {
    if (r.width === 0 || r.height === 0) continue
    rects.push(
      viewportRectToPdf(
        {
          x: r.left - containerRect.left,
          y: r.top - containerRect.top,
          width: r.width,
          height: r.height,
        },
        viewport,
      ),
    )
  }
  if (rects.length === 0) return null

  // Prefix/suffix from the page's full text layer string — best-effort, used
  // only as a stability check, not for primary anchoring.
  const normalizedPageText = pageText.replace(/\s+/g, ' ')
  const target = textContent
  const idx = normalizedPageText.indexOf(target)
  let textStart: number | null = null
  let textEnd: number | null = null
  let prefix: string | null = null
  let suffix: string | null = null
  if (idx >= 0) {
    textStart = idx
    textEnd = idx + target.length
    prefix = normalizedPageText.slice(Math.max(0, idx - PREFIX_CHARS), idx).trim() || null
    suffix = normalizedPageText.slice(idx + target.length, idx + target.length + SUFFIX_CHARS).trim() || null
  }

  return { textStart, textEnd, textContent, prefix, suffix, rects }
}

export interface ViewportRect {
  left: number
  top: number
  width: number
  height: number
}

/**
 * Convert stored PDF rects → viewport-pixel rects for rendering. The
 * returned coords are page-container-relative (absolute-position friendly).
 */
export function pdfRectsToViewport(rects: PdfRect[], viewport: PdfJsViewport): ViewportRect[] {
  const out: ViewportRect[] = []
  for (const r of rects) {
    const [x1, y1, x2, y2] = viewport.convertToViewportRectangle([r.x, r.y, r.x + r.width, r.y + r.height])
    const left = Math.min(x1, x2)
    const top = Math.min(y1, y2)
    out.push({ left, top, width: Math.abs(x2 - x1), height: Math.abs(y2 - y1) })
  }
  return out
}
