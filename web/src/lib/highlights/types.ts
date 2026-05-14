// Wiki-side highlight types. Mirrors api/services/types.py:Highlight + TextAnchor.
// JSONB shape on `documents.highlights`:
//
//   [
//     {
//       id: "uuid",
//       type: "text" | "pdf",
//       anchor:     { xpath, endXPath?, startOffset, endOffset, textContent, prefix?, suffix? } | null,
//       textAnchor: { textStart, textEnd, textContent, prefix?, suffix? }                    | null,
//       comment: string | null,
//       color: "yellow",
//       createdAt: ISO,
//     },
//     ...
//   ]
//
// `anchor` is the DOM-relative anchor used by the Chrome extension to re-apply
// highlights on the live page. `textAnchor` is the plaintext-relative anchor
// computed by the API at save time, used by this viewer to render highlights
// as ProseMirror decorations on the parsed markdown content.

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

export interface Highlight {
  id: string
  type: 'text' | 'pdf'
  anchor?: DomAnchor | null
  textAnchor?: TextAnchor | null
  comment: string | null
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
}
