import { Editor } from '@tiptap/core'
import { describe, expect, it } from 'vitest'

import { createMarkdownExtensions } from '@/lib/tiptap/extensions'
import fixture from '../../../../tests/fixtures/parity/canonical_plaintext.json'
import { canonicalPlaintextFromTipTapDoc, type CanonicalPlaintext } from './canonicalPlaintext'

interface Rendered {
  canonical: CanonicalPlaintext
  textAt: (pos: number) => string
}

function render(markdown: string): Rendered {
  const editor = new Editor({ extensions: createMarkdownExtensions(), content: markdown })
  const doc = editor.state.doc
  const canonical = canonicalPlaintextFromTipTapDoc(doc)
  editor.destroy()
  return { canonical, textAt: (pos) => doc.textBetween(pos, pos + 1) }
}

interface CanonicalCase {
  name: string
  html: string
  markdown: string
  plaintext: string
  tsPlaintext?: string
  knownDiscrepancy?: string
}

const cases: CanonicalCase[] = fixture.cases

describe('canonical plaintext parity with the server parser', () => {
  it.each(cases)('$name', (c) => {
    expect(render(c.markdown).canonical.text).toBe(c.tsPlaintext ?? c.plaintext)
  })

  it.each(cases)('$name maps every text char to its doc position', (c) => {
    const { canonical, textAt } = render(c.markdown)
    canonical.charToPos.forEach((pos, i) => {
      if (pos !== null) expect(textAt(pos)).toBe(canonical.text[i])
    })
  })

  it('documents every TS-only expectation as a discrepancy', () => {
    for (const c of cases.filter((c) => c.tsPlaintext !== undefined)) {
      expect(c.knownDiscrepancy).toBeTruthy()
      expect(c.tsPlaintext).not.toBe(c.plaintext)
    }
  })
})
