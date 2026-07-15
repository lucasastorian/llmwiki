import type { DocumentListItem, WikiNode } from '@/lib/types'

export type LessonStatus = 'complete' | 'in_progress' | 'not_started'

// Scaffold pages that frame a course but aren't completable lessons: the hub
// page and the changelog. Excluded from progress counts, locking, and the pager.
const STRUCTURAL_PAGES = new Set(['overview.md', 'log.md', 'index.json'])

export function isLesson(path: string): boolean {
  return !STRUCTURAL_PAGES.has(path)
}

export function lessonStatus(doc: DocumentListItem | null | undefined): LessonStatus {
  const s = (doc?.metadata as { course?: { status?: string } } | null)?.course?.status
  return s === 'complete' ? 'complete' : s === 'in_progress' ? 'in_progress' : 'not_started'
}

// Course mode: stamp each lesson node with its status (from the lesson doc's metadata.course)
// and a derived `locked` flag — a lesson is locked until the previous lesson in tree order is complete.
export function enrichTreeWithProgress(tree: WikiNode[], docs: DocumentListItem[]): WikiNode[] {
  const statusByPath = new Map<string, LessonStatus>()
  for (const doc of docs) {
    const relative = (doc.path + doc.filename).replace(/^\/wiki\/?/, '')
    statusByPath.set(relative, lessonStatus(doc))
  }

  const apply = (nodes: WikiNode[]): WikiNode[] =>
    nodes.map((node) => {
      const next: WikiNode = { ...node, children: node.children ? apply(node.children) : undefined }
      if (next.path) {
        next.status = statusByPath.get(next.path) ?? 'not_started'
        if (!isLesson(next.path)) next.locked = false
      }
      return next
    })

  const enriched = apply(tree)

  // Lock in display order: a lesson is locked until EVERY earlier lesson is complete.
  let prevComplete = true // the first lesson is never locked
  for (const lesson of flattenLessons(enriched)) {
    lesson.locked = lesson.status !== 'complete' && !prevComplete
    prevComplete = prevComplete && lesson.status === 'complete'
  }

  return enriched
}

// First non-complete lesson, in tree order — the "current" / resume target.
export function findCurrentLesson(nodes: WikiNode[]): WikiNode | null {
  for (const node of nodes) {
    if (node.path && isLesson(node.path) && node.status !== 'complete') return node
    if (node.children) {
      const found = findCurrentLesson(node.children)
      if (found) return found
    }
  }
  return null
}

// Path-bearing nodes (lessons) in tree order.
export function flattenLessons(nodes: WikiNode[]): WikiNode[] {
  const out: WikiNode[] = []
  const walk = (ns: WikiNode[]) => {
    for (const n of ns) {
      if (n.path && isLesson(n.path)) out.push(n)
      if (n.children) walk(n.children)
    }
  }
  walk(nodes)
  return out
}

// All path-bearing nodes in tree order, structural pages included — the
// reading order used by the wiki pager.
export function flattenPages(nodes: WikiNode[]): WikiNode[] {
  const out: WikiNode[] = []
  const walk = (ns: WikiNode[]) => {
    for (const n of ns) {
      if (n.path) out.push(n)
      if (n.children) walk(n.children)
    }
  }
  walk(nodes)
  return out
}
