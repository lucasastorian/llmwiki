import type { DocumentListItem, WikiNode } from '@/lib/types'

export type LessonStatus = 'complete' | 'in_progress' | 'not_started'

type PageEntry = { title: string; path: string; docNumber: number | null }
type TopLevelPage = PageEntry & { slug: string }
type GroupedPages = { topLevel: TopLevelPage[]; childPages: Map<string, PageEntry[]> }

const PAGE_EXTENSION = /\.(md|txt|json)$/
const PINNED_FIRST = ['overview', 'plan']
const PINNED_LAST = 'log'

// Course scaffolding, not completable lessons.
const STRUCTURAL_PAGES = new Set(['overview.md', 'log.md', 'index.json'])

export function wikiRelativePath(doc: Pick<DocumentListItem, 'path' | 'filename'>): string {
  return (doc.path + doc.filename).replace(/^\/wiki\/?/, '')
}

/** Nav tree derived from the wiki docs themselves, for when index.json is absent or unusable. */
export function buildTreeFromDocs(docs: DocumentListItem[]): WikiNode[] {
  const { topLevel, childPages } = groupPagesByFolder(docs)
  const usedFolders = new Set<string>()
  const tree: WikiNode[] = topLevel.map((parent) => attachChildren(parent, childPages, usedFolders))
  for (const [folder, children] of childPages) {
    if (usedFolders.has(folder)) continue
    tree.push({ title: folderTitle(folder), children: children.map(toLeafNode) })
  }
  return tree.sort(compareTopLevelNodes)
}

export function enrichTreeWithDocNumbers(tree: WikiNode[], docs: DocumentListItem[]): WikiNode[] {
  const pathToDocNumber = new Map<string, number | null>()
  for (const doc of docs) pathToDocNumber.set(wikiRelativePath(doc), doc.document_number)
  return enrichNodes(tree, pathToDocNumber)
}

// index.json is synced lazily by the agent and can list deleted pages.
export function pruneMissingPages(nodes: WikiNode[], existing: Set<string>): WikiNode[] {
  const pruned: WikiNode[] = []
  for (const node of nodes) {
    const children = node.children ? pruneMissingPages(node.children, existing) : undefined
    if (node.path && !existing.has(node.path)) {
      if (children?.length) pruned.push({ ...node, path: undefined, docNumber: null, children })
      continue
    }
    pruned.push({ ...node, children })
  }
  return pruned
}

export function findFirstPath(nodes: WikiNode[]): { path: string; docNumber: number | null } | null {
  for (const node of nodes) {
    if (node.path) return { path: node.path, docNumber: node.docNumber ?? null }
    if (node.children) {
      const found = findFirstPath(node.children)
      if (found) return found
    }
  }
  return null
}

export function isLesson(path: string): boolean {
  return !STRUCTURAL_PAGES.has(path)
}

export function lessonStatus(doc: DocumentListItem | null | undefined): LessonStatus {
  const s = (doc?.metadata as { course?: { status?: string } } | null)?.course?.status
  return s === 'complete' ? 'complete' : s === 'in_progress' ? 'in_progress' : 'not_started'
}

export function enrichTreeWithProgress(tree: WikiNode[], docs: DocumentListItem[]): WikiNode[] {
  const statusByPath = new Map<string, LessonStatus>()
  for (const doc of docs) {
    statusByPath.set(wikiRelativePath(doc), lessonStatus(doc))
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

  // Locked until every earlier lesson in display order is complete.
  let prevComplete = true
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

// Like flattenLessons but keeps structural pages.
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

// Maps a markdown link href to a wiki-relative page path ('concepts/attention.md').
export function resolveWikiHref(href: string, activePath: string | null, knownPaths: Set<string>): string {
  const target = decodeHref(href.split('#')[0])
  if (target === '/wiki' || target.startsWith('/wiki/')) return target.replace(/^\/wiki\/?/, '')
  if (target.startsWith('/')) return target.slice(1)
  if (knownPaths.has(target) || !activePath) return target

  const segments = activePath.split('/').slice(0, -1)
  for (const part of target.split('/')) {
    if (part === '..') segments.pop()
    else if (part && part !== '.') segments.push(part)
  }
  return segments.join('/')
}

function groupPagesByFolder(docs: DocumentListItem[]): GroupedPages {
  const sorted = [...docs].sort((a, b) => (a.sort_order ?? 999) - (b.sort_order ?? 999))
  const topLevel: TopLevelPage[] = []
  const childPages = new Map<string, PageEntry[]>()

  for (const doc of sorted) {
    const relative = wikiRelativePath(doc)
    const parts = relative.split('/')
    const title = doc.title || parts[parts.length - 1].replace(PAGE_EXTENSION, '').replace(/[-_]/g, ' ')
    const entry: PageEntry = { title, path: relative, docNumber: doc.document_number }
    if (parts.length === 1) {
      topLevel.push({ ...entry, slug: parts[0].replace(PAGE_EXTENSION, '') })
      continue
    }
    const folder = parts[0]
    if (!childPages.has(folder)) childPages.set(folder, [])
    childPages.get(folder)!.push(entry)
  }
  return { topLevel, childPages }
}

function attachChildren(parent: TopLevelPage, childPages: Map<string, PageEntry[]>, usedFolders: Set<string>): WikiNode {
  const node: WikiNode = { title: parent.title, path: parent.path, docNumber: parent.docNumber }
  const children = childPages.get(parent.slug)
  if (!children || children.length === 0) return node
  usedFolders.add(parent.slug)
  return { ...node, children: children.map(toLeafNode) }
}

function toLeafNode(page: PageEntry): WikiNode {
  return { title: page.title, path: page.path, docNumber: page.docNumber }
}

function folderTitle(folder: string): string {
  return folder.replace(/[-_]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function topLevelRank(node: WikiNode): number {
  const slug = node.path?.replace(PAGE_EXTENSION, '').split('/')[0] ?? ''
  const pinnedIndex = PINNED_FIRST.indexOf(slug)
  if (pinnedIndex >= 0) return pinnedIndex
  return slug === PINNED_LAST ? PINNED_FIRST.length + 1 : PINNED_FIRST.length
}

function compareTopLevelNodes(a: WikiNode, b: WikiNode): number {
  return topLevelRank(a) - topLevelRank(b) || a.title.localeCompare(b.title)
}

function enrichNodes(nodes: WikiNode[], pathToDocNumber: Map<string, number | null>): WikiNode[] {
  return nodes.map((node) => ({
    ...node,
    docNumber: node.path ? (pathToDocNumber.get(node.path) ?? null) : null,
    children: node.children ? enrichNodes(node.children, pathToDocNumber) : undefined,
  }))
}

function decodeHref(href: string): string {
  try {
    return decodeURIComponent(href)
  } catch {
    return href
  }
}
