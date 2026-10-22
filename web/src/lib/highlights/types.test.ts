import { describe, expect, it } from 'vitest'

import fixture from '../../../../tests/fixtures/parity/highlight_types.json'
import type { DomAnchor, Highlight, HighlightReply, PdfAnchor, PdfRect, TextAnchor } from './types'

/** Exhaustive by construction: tsc rejects a missing or extra key. */
type FieldSet<T> = Record<keyof T, true>

const highlightFields: FieldSet<Highlight> = {
  id: true, type: true, anchor: true, textAnchor: true, pdfAnchor: true,
  comment: true, replies: true, color: true, createdAt: true,
}
const domAnchorFields: FieldSet<DomAnchor> = {
  xpath: true, endXPath: true, startOffset: true, endOffset: true, textContent: true, prefix: true, suffix: true,
}
const textAnchorFields: FieldSet<TextAnchor> = {
  textStart: true, textEnd: true, textContent: true, prefix: true, suffix: true,
}
const pdfAnchorFields: FieldSet<PdfAnchor> = {
  page: true, textStart: true, textEnd: true, textContent: true, prefix: true, suffix: true, rects: true,
}
const pdfRectFields: FieldSet<PdfRect> = { x: true, y: true, width: true, height: true }
const replyFields: FieldSet<HighlightReply> = { id: true, author: true, text: true, createdAt: true }

const TS_FIELDS: Record<keyof typeof fixture.models, object> = {
  Highlight: highlightFields,
  HighlightAnchor: domAnchorFields,
  TextAnchor: textAnchorFields,
  PdfAnchor: pdfAnchorFields,
  PdfRect: pdfRectFields,
  HighlightReply: replyFields,
}

const highlightTypes: Record<Highlight['type'], true> = { text: true, pdf: true }
const replyAuthors: Record<HighlightReply['author'], true> = { user: true, agent: true }

describe('highlight types parity with api/services/types.py', () => {
  it.each(Object.entries(fixture.models))('%s fields', (name, model) => {
    const fields = Object.keys(TS_FIELDS[name as keyof typeof fixture.models])
    expect(fields.sort()).toEqual([...model.fields].sort())
  })

  it('literal values', () => {
    expect(Object.keys(highlightTypes).sort()).toEqual([...fixture.literals['Highlight.type']].sort())
    expect(Object.keys(replyAuthors).sort()).toEqual([...fixture.literals['HighlightReply.author']].sort())
  })
})
