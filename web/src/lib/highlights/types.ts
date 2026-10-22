// The `documents.highlights` JSONB shape; field parity with the server is enforced by tests/fixtures/parity/highlight_types.json.

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
