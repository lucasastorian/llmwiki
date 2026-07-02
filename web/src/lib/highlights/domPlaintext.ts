// Plaintext view of a rendered wiki page: text nodes in document order with
// cumulative offsets, so highlights round-trip between character offsets and
// live DOM Ranges. KaTeX subtrees are skipped — KaTeX emits every formula
// twice (MathML + HTML spans), which would double-count text and destabilize
// offsets across renders.

interface TextSegment {
  node: Text
  start: number
}

export interface DomPlaintext {
  text: string
  segments: TextSegment[]
}

const SKIP_SELECTOR = '.katex'

export function domPlaintextFromContainer(root: HTMLElement): DomPlaintext {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) => {
      const parent = node.parentElement
      if (!parent || parent.closest(SKIP_SELECTOR)) return NodeFilter.FILTER_REJECT
      return NodeFilter.FILTER_ACCEPT
    },
  })
  const segments: TextSegment[] = []
  const parts: string[] = []
  let offset = 0
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = node as Text
    segments.push({ node: text, start: offset })
    parts.push(text.data)
    offset += text.data.length
  }
  return { text: parts.join(''), segments }
}

export function rangeFromOffsets(dp: DomPlaintext, start: number, end: number): Range | null {
  const startPoint = pointAtOffset(dp, start)
  const endPoint = pointAtOffset(dp, end)
  if (!startPoint || !endPoint) return null
  const range = document.createRange()
  range.setStart(startPoint.node, startPoint.offset)
  range.setEnd(endPoint.node, endPoint.offset)
  if (range.collapsed) return null
  return range
}

export function offsetsFromRange(dp: DomPlaintext, range: Range): { start: number; end: number } | null {
  const start = offsetOfPoint(dp, range.startContainer, range.startOffset)
  const end = offsetOfPoint(dp, range.endContainer, range.endOffset)
  if (start === null || end === null || end <= start) return null
  return { start, end }
}

export function offsetAtDomPoint(dp: DomPlaintext, container: Node, offsetInNode: number): number | null {
  return offsetOfPoint(dp, container, offsetInNode)
}

function pointAtOffset(dp: DomPlaintext, offset: number): { node: Text; offset: number } | null {
  if (dp.segments.length === 0) return null
  const clamped = Math.max(0, Math.min(offset, dp.text.length))
  for (let i = dp.segments.length - 1; i >= 0; i--) {
    const segment = dp.segments[i]
    if (clamped >= segment.start) {
      return { node: segment.node, offset: Math.min(clamped - segment.start, segment.node.data.length) }
    }
  }
  return { node: dp.segments[0].node, offset: 0 }
}

function offsetOfPoint(dp: DomPlaintext, container: Node, offsetInNode: number): number | null {
  if (container.nodeType === Node.TEXT_NODE) {
    const segment = dp.segments.find((s) => s.node === container)
    // A text node not in the walk (e.g. inside KaTeX) falls through to the
    // probe path, mapping to the next tracked segment.
    if (segment) return segment.start + Math.min(offsetInNode, segment.node.data.length)
  }
  const probe = document.createRange()
  try {
    probe.setStart(container, offsetInNode)
  } catch {
    return null
  }
  probe.collapse(true)
  for (const segment of dp.segments) {
    // A detached node (stale snapshot mid-re-render) makes comparePoint throw
    // WrongDocumentError.
    if (!segment.node.isConnected) continue
    if (probe.comparePoint(segment.node, 0) >= 0) return segment.start
  }
  return dp.text.length
}
