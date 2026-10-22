// Parity with the server's `_to_plaintext()` (api/html_parser/plaintext_builder.py) is enforced by tests/fixtures/parity/canonical_plaintext.json.

import type { Node as ProseMirrorNode } from '@tiptap/pm/model'

export interface CanonicalPlaintext {
  text: string
  charToPos: Array<number | null>
  offsetToPos: (offset: number, bias: 'right' | 'left') => number | null
}

type Separator = '' | ' ' | '\n' | '\n\n'

const BLOCK_SEPARATOR: Separator = '\n\n'
const LIST_SEPARATOR: Separator = '\n'
const CELL_SEPARATOR: Separator = ' '
const SEPARATOR_RANK: Record<Separator, number> = { '': 0, ' ': 1, '\n': 2, '\n\n': 3 }
const TRAILING_WHITESPACE = /[ \t\n\r\f]/

/** Separators and hard breaks are emitted lazily, only once more text follows, so empty blocks leave no trace. */
interface Builder {
  parts: string[]
  charToPos: Array<number | null>
  offset: number
  separator: Separator
  hasPendingHardBreak: boolean
  lineHasText: boolean
  /** Pre-UTF-16 walker behaviour: a list item's blocks were joined with nothing, so stored anchors read "parentchild". */
  isLegacy: boolean
}

function newBuilder(isLegacy: boolean): Builder {
  return { parts: [], charToPos: [], offset: 0, separator: '', hasPendingHardBreak: false, lineHasText: false, isLegacy }
}

function push(b: Builder, text: string, basePos: number | null): void {
  b.parts.push(text)
  for (let i = 0; i < text.length; i++) {
    b.charToPos.push(basePos === null ? null : basePos + i)
  }
  b.offset += text.length
}

function flushPending(b: Builder): void {
  if (b.separator) {
    if (b.offset > 0) push(b, b.separator, null)
  } else if (b.hasPendingHardBreak) {
    push(b, '\n', null)
  }
  b.separator = ''
  b.hasPendingHardBreak = false
}

function appendText(b: Builder, text: string, basePos: number): void {
  if (!text) return
  flushPending(b)
  push(b, text, basePos)
  b.lineHasText = true
}

function requestBlockBreak(b: Builder, separator: Separator): void {
  if (SEPARATOR_RANK[separator] > SEPARATOR_RANK[b.separator]) b.separator = separator
  b.hasPendingHardBreak = false
  b.lineHasText = false
}

function requestHardBreak(b: Builder): void {
  if (!b.lineHasText) return
  b.hasPendingHardBreak = true
  b.lineHasText = false
}

function walkChildren(b: Builder, parent: ProseMirrorNode, parentStartPos: number, separator: Separator): void {
  // +1 skips the parent's opening token.
  let cursor = parentStartPos + 1
  parent.forEach((child) => {
    walkAt(b, child, cursor, separator)
    cursor += child.nodeSize
  })
}

function walkListItems(b: Builder, list: ProseMirrorNode, listPos: number): void {
  let cursor = listPos + 1
  list.forEach((item, _offset, index) => {
    if (index > 0) requestBlockBreak(b, LIST_SEPARATOR)
    walkChildren(b, item, cursor, b.isLegacy ? '' : LIST_SEPARATOR)
    cursor += item.nodeSize
  })
}

function walkAt(b: Builder, node: ProseMirrorNode, pos: number, separator: Separator): void {
  const name = node.type.name

  if (node.isText) {
    appendText(b, node.text ?? '', pos)
    return
  }
  if (name === 'hardBreak') {
    requestHardBreak(b)
    return
  }
  if (name === 'bulletList' || name === 'orderedList') {
    requestBlockBreak(b, separator)
    walkListItems(b, node, pos)
    return
  }
  if (name === 'tableRow') {
    requestBlockBreak(b, LIST_SEPARATOR)
    walkChildren(b, node, pos, CELL_SEPARATOR)
    return
  }
  if (node.isBlock) {
    requestBlockBreak(b, separator)
  }
  walkChildren(b, node, pos, separator)
}

export function canonicalPlaintextFromTipTapDoc(doc: ProseMirrorNode, isLegacy = false): CanonicalPlaintext {
  const b = newBuilder(isLegacy)
  // doc has no opening token; first child is at position 0.
  let cursor = 0
  doc.forEach((child) => {
    walkAt(b, child, cursor, BLOCK_SEPARATOR)
    cursor += child.nodeSize
  })

  let text = b.parts.join('')
  let map = b.charToPos
  while (text.length > 0 && TRAILING_WHITESPACE.test(text[text.length - 1])) {
    text = text.slice(0, -1)
    map = map.slice(0, -1)
  }

  const offsetToPos = (offset: number, bias: 'right' | 'left'): number | null => {
    const len = map.length
    if (offset < 0) offset = 0
    if (offset > len) offset = len
    if (bias === 'right') {
      for (let i = offset; i < len; i++) {
        if (map[i] !== null) return map[i] as number
      }
      return null
    }
    for (let i = offset - 1; i >= 0; i--) {
      if (map[i] !== null) return (map[i] as number) + 1
    }
    return null
  }

  return { text, charToPos: map, offsetToPos }
}
