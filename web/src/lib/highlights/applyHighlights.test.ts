import { Editor } from '@tiptap/core'
import { describe, expect, it } from 'vitest'

import { createMarkdownExtensions } from '@/lib/tiptap/extensions'
import { decorationsFromHighlights } from './applyHighlights'
import { canonicalPlaintextFromTipTapDoc } from './canonicalPlaintext'
import type { Highlight, TextAnchor } from './types'

// Parser output for <ul><li><p>Para A</p><p>Para B</p></li></ul><p>😀😀 Intro with *stars* and the target words here.</p><pre>def f():\n    return 1</pre>
const MARKDOWN = '- Para A\n\n  Para B\n\n😀😀 Intro with \\*stars\\* and the target words here.\n\n```\ndef f():\n    return 1\n```'

function highlight(id: string, textAnchor: TextAnchor): Highlight {
  return { id, type: 'text', anchor: null, textAnchor, comment: null, color: 'yellow', createdAt: '2026-01-01T00:00:00Z' }
}

function renderedSlices(highlights: Highlight[], markdown = MARKDOWN): { canonicalText: string; slices: string[] } {
  const editor = new Editor({ extensions: createMarkdownExtensions(), content: markdown })
  const doc = editor.state.doc
  const slices = decorationsFromHighlights(highlights, doc).map((r) => doc.textBetween(r.from, r.to))
  editor.destroy()
  return { canonicalText: canonicalPlaintextFromTipTapDoc(doc).text, slices }
}

describe('stored text anchors across parser plaintext changes', () => {
  it('re-locates anchors whose offsets were computed against the pre-UTF-16, pre-list-fix plaintext', () => {
    // Offsets as the old parser stored them: code points, "\n\n" inside list items, dedented code.
    const stale = [
      highlight('h1', { textStart: 42, textEnd: 58, textContent: 'the target words', prefix: '*stars* and ', suffix: ' here.' }),
      highlight('h2', { textStart: 75, textEnd: 83, textContent: 'return 1', prefix: 'def f():\n', suffix: null }),
    ]
    const { canonicalText, slices } = renderedSlices(stale)

    expect(canonicalText.slice(42, 58)).not.toBe('the target words')
    expect(slices).toEqual(['the target words', 'return 1'])
  })

  it('falls back to the pre-separator list walk for anchors spanning nested list items', () => {
    // The old walker joined a list item's blocks with nothing, so "parent" + nested "child" read "parentchild".
    const legacy = [highlight('h1', { textStart: 0, textEnd: 11, textContent: 'parentchild', suffix: '\nother' })]
    const { canonicalText, slices } = renderedSlices(legacy, '- parent\n  - child\n- other')

    expect(canonicalText).toBe('parent\nchild\nother')
    expect(slices).toEqual(['parentchild'])
  })

  it('prefers legacy offsets that verify over a later current-text match of the same quote', () => {
    const editor = new Editor({ extensions: createMarkdownExtensions(), content: '- parent\n  - child\n\nLater parentchild here.' })
    const doc = editor.state.doc
    const legacy = [highlight('h1', { textStart: 0, textEnd: 11, textContent: 'parentchild' })]
    const [range] = decorationsFromHighlights(legacy, doc)
    const listEnd = doc.child(0).nodeSize
    editor.destroy()

    expect(range.to).toBeLessThanOrEqual(listEnd)
  })

  it('uses current offsets directly', () => {
    const current = [highlight('h1', { textStart: 43, textEnd: 59, textContent: 'the target words' })]
    const { canonicalText, slices } = renderedSlices(current)

    expect(canonicalText.slice(43, 59)).toBe('the target words')
    expect(slices).toEqual(['the target words'])
  })
})
