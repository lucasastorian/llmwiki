// Wiki-side highlight types. Mirrors api/services/types.py:Highlight + TextAnchor.
// JSONB shape on `documents.highlights`:
//
//   [
//     {
//       id: "uuid",
//       type: "text" | "pdf",
//       anchor:     { xpath, endXPath?, startOffset, endOffset, textContent, prefix?, suffix? } | null,
//       textAnchor: { textStart, textEnd, textContent, prefix?, suffix? }                    | null,
//       pdfAnchor:  { page, textContent, prefix?, suffix?, rects }                           | null,
//       comment: string | null,
//       color: "yellow",
//       createdAt: ISO,
//     },
//     ...
//   ]
//
// These are all the same user-facing feature. The separate anchor fields are
// resolver metadata for different surfaces: live-page DOM, parsed markdown,
// and PDF canvas/text-layer rendering.

export interface DomAnchor {
  xpath: string
  endXPath?: string | null
  startOffset: number
  endOffset: number
  textContent: string
  prefix?: string | null
  suffix?: string | null
}

export interface TextAnchor {
  textStart: number
  textEnd: number
  textContent: string
  prefix?: string | null
  suffix?: string | null
}

export interface PdfRect {
  x: number
  y: number
  width: number
  height: number
}

export interface PdfAnchor {
  page: number
  /** Page-local offsets into PDF.js's normalized extracted page text. */
  textStart?: number | null
  textEnd?: number | null
  textContent: string
  prefix?: string | null
  suffix?: string | null
  rects: PdfRect[]
}

export interface HighlightReply {
  id: string
  author: 'user' | 'agent'
  text: string
  createdAt: string
}

export interface Highlight {
  id: string
  type: 'text' | 'pdf'
  anchor?: DomAnchor | null
  textAnchor?: TextAnchor | null
  pdfAnchor?: PdfAnchor | null
  comment: string | null
  replies?: HighlightReply[] | null
  color: string
  createdAt: string
}

export interface HighlightsResponse {
  id: string
  version: number
  highlights: Highlight[]
}

export interface DecorationRange {
  id: string
  from: number
  to: number
  comment?: string | null
}
