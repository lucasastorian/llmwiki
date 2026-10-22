import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { gunzipSync } from 'node:zlib'

import { Editor } from '@tiptap/core'
import { describe, expect, it } from 'vitest'

import { createMarkdownExtensions } from '@/lib/tiptap/extensions'
import { canonicalPlaintextFromTipTapDoc } from './canonicalPlaintext'

interface PageGolden {
  markdown: string
  plaintext: string
  markdown_sha256: string
}

const GOLDENS_PATH = resolve(__dirname, '../../../../tests/fixtures/real_pages/goldens.json.gz')
const DIVERGENCE_CONTEXT = 120

const goldens = JSON.parse(gunzipSync(readFileSync(GOLDENS_PATH)).toString('utf-8')) as Record<string, PageGolden>
const pages: Array<[string, PageGolden]> = Object.entries(goldens)

function renderPlaintext(markdown: string): string {
  const editor = new Editor({ extensions: createMarkdownExtensions(), content: markdown })
  const text = canonicalPlaintextFromTipTapDoc(editor.state.doc).text
  editor.destroy()
  return text
}

function firstDivergence(expected: string, actual: string): string {
  let index = 0
  while (index < expected.length && index < actual.length && expected[index] === actual[index]) index++
  const start = Math.max(0, index - DIVERGENCE_CONTEXT)
  const end = index + DIVERGENCE_CONTEXT
  return [
    `diverges at UTF-16 offset ${index} (server ${expected.length}, TipTap ${actual.length})`,
    `server: ${JSON.stringify(expected.slice(start, end))}`,
    `tiptap: ${JSON.stringify(actual.slice(start, end))}`,
  ].join('\n')
}

describe('real-page plaintext parity between the server parser and TipTap', () => {
  it('loads the frozen goldens', () => {
    expect(pages.length).toBeGreaterThan(0)
  })

  it.each(pages)('%s', (_id, golden) => {
    const actual = renderPlaintext(golden.markdown)
    if (actual !== golden.plaintext) console.error(firstDivergence(golden.plaintext, actual))
    expect(actual === golden.plaintext, firstDivergence(golden.plaintext, actual)).toBe(true)
  })
})
