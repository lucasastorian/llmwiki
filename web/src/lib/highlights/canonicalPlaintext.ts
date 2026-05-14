// Walks a ProseMirror document and produces canonical plaintext that matches
// the server-side `_to_plaintext()` in api/html_parser/parser.py exactly.
//
// Why custom (not `editor.state.doc.textBetween(...)`):
//   - lists in TipTap are paragraph-block items; textBetween would inject
//     `\n\n` between items, but parser uses `\n`
//   - tables in TipTap have textblock cells; textBetween would separate cells
//     by `\n\n`, but parser uses ` ` (space)
//   - images are leaves with no text content; textBetween treats them as a
//     leaf separator, but parser emits empty string
//
// Output:
//   text:        canonical plaintext string
//   charToPos:   per-char map. `null` for synthetic separators (block breaks,
//                cell spaces) which have no real ProseMirror position.
//   offsetToPos: resolves a plaintext offset to a PM position, biased
//                'right' for `from` and 'left' for `to`. Skips synthetic
//                separators by seeking to the nearest real position.

import type { Node as ProseMirrorNode } from '@tiptap/pm/model'

export interface CanonicalPlaintext {
  text: string
  charToPos: Array<number | null>
  offsetToPos: (offset: number, bias: 'right' | 'left') => number | null
}

interface Builder {
  parts: string[]
  charToPos: Array<number | null>
  /** True after a block break has just been emitted, so subsequent block
   *  emissions don't double-up `\n\n`. Reset to false on real text. */
  blockBreakPending: boolean
  /** When > 0, `ensureBlockBreak()` is a no-op. Used by the listItem walker
   *  to flatten multi-paragraph items into a single-line run. Counter (not
   *  boolean) so nested suppressions compose. */
  suppressBlockBreaks: number
  offset: number
}

function newBuilder(): Builder {
  return {
    parts: [],
    charToPos: [],
    blockBreakPending: true,
    suppressBlockBreaks: 0,
    offset: 0,
  }
}

function appendText(b: Builder, text: string, basePos: number): void {
  if (!text) return
  b.parts.push(text)
  for (let i = 0; i < text.length; i++) {
    b.charToPos.push(basePos + i)
  }
  b.offset += text.length
  b.blockBreakPending = false
}

function appendSynthetic(b: Builder, text: string): void {
  if (!text) return
  b.parts.push(text)
  for (let i = 0; i < text.length; i++) {
    b.charToPos.push(null)
  }
  b.offset += text.length
}

function ensureBlockBreak(b: Builder): void {
  if (b.suppressBlockBreaks > 0) return
  if (b.offset === 0 || b.blockBreakPending) return
  appendSynthetic(b, '\n\n')
  b.blockBreakPending = true
}

const BLOCK_TYPES = new Set(['paragraph', 'heading', 'codeBlock', 'blockquote'])

function walkChildren(b: Builder, parent: ProseMirrorNode, parentStartPos: number): void {
  // For non-doc parents, child positions start at parentStartPos + 1 (skip
  // the parent's opening token). The doc itself has no opening token and is
  // handled by the public entrypoint.
  let cursor = parentStartPos + 1
  parent.forEach((child) => {
    walkAt(b, child, cursor)
    cursor += child.nodeSize
  })
}

function walkAt(b: Builder, node: ProseMirrorNode, pos: number): void {
  const name = node.type.name

  if (node.isText) {
    appendText(b, node.text ?? '', pos)
    return
  }

  if (name === 'image') return
  if (name === 'hardBreak') {
    appendText(b, '\n', pos)
    return
  }
  if (name === 'horizontalRule') {
    ensureBlockBreak(b)
    return
  }

  if (BLOCK_TYPES.has(name)) {
    ensureBlockBreak(b)
    const startOffset = b.offset
    walkChildren(b, node, pos)
    if (b.offset > startOffset) {
      b.blockBreakPending = false
    }
    return
  }

  if (name === 'bulletList' || name === 'orderedList') {
    ensureBlockBreak(b)
    let firstItem = true
    let cursor = pos + 1
    node.forEach((item) => {
      if (!firstItem) appendSynthetic(b, '\n')
      // Route through walkAt so the listItem branch's per-child
      // textblock-flattening logic applies to multi-paragraph items.
      walkAt(b, item, cursor)
      cursor += item.nodeSize
      firstItem = false
    })
    b.blockBreakPending = false
    return
  }

  if (name === 'listItem') {
    // A list item may contain multiple textblocks (paragraphs). Walk each
    // child with block-breaks suppressed and join multiple textblocks with a
    // single `\n` — matches the parser's li flatten behavior.
    b.suppressBlockBreaks++
    let firstChild = true
    let cursor = pos + 1
    let lastOffset = b.offset
    node.forEach((child) => {
      // If a previous textblock emitted real content and the next child is
      // also a textblock, separate them with a single `\n`.
      if (
        !firstChild
        && b.offset > lastOffset
        && (child.isTextblock || child.type.name === 'paragraph')
      ) {
        appendSynthetic(b, '\n')
      }
      walkAt(b, child, cursor)
      cursor += child.nodeSize
      lastOffset = b.offset
      firstChild = false
    })
    b.suppressBlockBreaks--
    return
  }

  if (name === 'table') {
    ensureBlockBreak(b)
    let rowCursor = pos + 1
    let firstRow = true
    node.forEach((row) => {
      if (!firstRow) appendSynthetic(b, '\n')
      let cellCursor = rowCursor + 1
      let firstCell = true
      row.forEach((cell) => {
        if (!firstCell) appendSynthetic(b, ' ')
        // Cells are textblocks; flatten contents without injecting block breaks.
        b.suppressBlockBreaks++
        walkChildren(b, cell, cellCursor)
        b.suppressBlockBreaks--
        cellCursor += cell.nodeSize
        firstCell = false
      })
      rowCursor += row.nodeSize
      firstRow = false
    })
    b.blockBreakPending = false
    return
  }

  // Default: descend through unknown wrapper nodes.
  walkChildren(b, node, pos)
}

export function canonicalPlaintextFromTipTapDoc(doc: ProseMirrorNode): CanonicalPlaintext {
  const b = newBuilder()
  // doc has no opening token; first child is at position 0.
  let cursor = 0
  doc.forEach((child) => {
    walkAt(b, child, cursor)
    cursor += child.nodeSize
  })

  // Trim trailing whitespace from the final string + matching map entries.
  let text = b.parts.join('')
  let map = b.charToPos
  while (text.length > 0 && /\s/.test(text[text.length - 1])) {
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
