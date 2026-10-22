import { describe, expect, it } from 'vitest'
import {
  buildTreeFromDocs, enrichTreeWithDocNumbers, enrichTreeWithProgress, findFirstPath, flattenLessons, flattenPages,
  pruneMissingPages, resolveWikiHref,
} from './wikiTree'
import type { DocumentListItem, WikiNode } from '@/lib/types'

const tree: WikiNode[] = [
  { title: 'Overview', path: 'overview.md' },
  {
    title: 'Concepts',
    path: 'concepts.md',
    children: [
      { title: 'Attention', path: 'concepts/attention.md' },
      { title: 'Embeddings', path: 'concepts/embeddings.md' },
    ],
  },
  { title: 'Log', path: 'log.md' },
]

function lessonDoc(relativePath: string, status?: string): DocumentListItem {
  const parts = relativePath.split('/')
  const filename = parts.pop()!
  const dir = parts.length ? `/wiki/${parts.join('/')}/` : '/wiki/'
  return {
    id: relativePath,
    path: dir,
    filename,
    metadata: status ? { course: { status } } : {},
  } as unknown as DocumentListItem
}

describe('flattenPages', () => {
  it('returns every path-bearing node in tree order, structural pages included', () => {
    expect(flattenPages(tree).map((n) => n.path)).toEqual([
      'overview.md',
      'concepts.md',
      'concepts/attention.md',
      'concepts/embeddings.md',
      'log.md',
    ])
  })
})

describe('flattenLessons', () => {
  it('excludes structural pages', () => {
    expect(flattenLessons(tree).map((n) => n.path)).toEqual([
      'concepts.md',
      'concepts/attention.md',
      'concepts/embeddings.md',
    ])
  })
})

describe('enrichTreeWithProgress', () => {
  it('locks each lesson until every earlier lesson is complete', () => {
    const docs = [
      lessonDoc('concepts.md', 'complete'),
      lessonDoc('concepts/attention.md'),
      lessonDoc('concepts/embeddings.md'),
    ]
    const lessons = flattenLessons(enrichTreeWithProgress(tree, docs))
    expect(lessons.map((l) => ({ path: l.path, locked: l.locked }))).toEqual([
      { path: 'concepts.md', locked: false },
      { path: 'concepts/attention.md', locked: false },
      { path: 'concepts/embeddings.md', locked: true },
    ])
  })

  it('never locks the first lesson', () => {
    const docs = [lessonDoc('concepts.md'), lessonDoc('concepts/attention.md')]
    const lessons = flattenLessons(enrichTreeWithProgress(tree, docs))
    expect(lessons[0].locked).toBe(false)
    expect(lessons[1].locked).toBe(true)
  })
})

describe('resolveWikiHref', () => {
  const known = new Set(['overview.md', 'concepts/attention.md'])

  it('climbs above the root without looping', () => {
    expect(resolveWikiHref('../sources/a.md', 'overview.md', known)).toBe('sources/a.md')
    expect(resolveWikiHref('../../x.md', 'concepts/attention.md', known)).toBe('x.md')
  })

  it('resolves sibling and nested relative links', () => {
    expect(resolveWikiHref('./scaling.md', 'concepts/attention.md', known)).toBe('concepts/scaling.md')
    expect(resolveWikiHref('../overview.md', 'concepts/attention.md', known)).toBe('overview.md')
  })

  it('handles wiki-absolute links, fragments and encoding', () => {
    expect(resolveWikiHref('/wiki/concepts/attention.md#scaled', 'overview.md', known)).toBe('concepts/attention.md')
    expect(resolveWikiHref('My%20Page.md', 'overview.md', known)).toBe('My Page.md')
    expect(resolveWikiHref('concepts/attention.md', 'overview.md', known)).toBe('concepts/attention.md')
  })
})

function wikiDoc(path: string, filename: string, overrides: Partial<DocumentListItem> = {}): DocumentListItem {
  return {
    id: `${path}${filename}`,
    knowledge_base_id: 'kb-1',
    user_id: 'user-1',
    filename,
    title: '',
    path,
    file_type: 'md',
    file_size: 100,
    status: 'completed',
    page_count: null,
    tags: [],
    date: null,
    metadata: null,
    error_message: null,
    url: null,
    version: 1,
    document_number: null,
    sort_order: null,
    archived: false,
    created_at: '2026-08-10T00:00:00.000Z',
    updated_at: '2026-08-10T00:00:00.000Z',
    ...overrides,
  }
}

describe('buildTreeFromDocs', () => {
  it('nests folder pages under a same-slug parent and orders overview first, log last', () => {
    const tree = buildTreeFromDocs([
      wikiDoc('/wiki/', 'log.md', { document_number: 9 }),
      wikiDoc('/wiki/', 'zebra.md', { title: 'Zebra', document_number: 3 }),
      wikiDoc('/wiki/zebra/', 'stripes.md', { document_number: 4 }),
      wikiDoc('/wiki/', 'overview.md', { title: 'Overview', document_number: 1 }),
      wikiDoc('/wiki/', 'apple_pie.md', { document_number: 2 }),
    ])

    expect(tree).toEqual([
      { title: 'Overview', path: 'overview.md', docNumber: 1 },
      { title: 'apple pie', path: 'apple_pie.md', docNumber: 2 },
      {
        title: 'Zebra', path: 'zebra.md', docNumber: 3,
        children: [{ title: 'stripes', path: 'zebra/stripes.md', docNumber: 4 }],
      },
      { title: 'log', path: 'log.md', docNumber: 9 },
    ])
  })

  it('pins the plan page right after overview, ahead of alphabetical pages', () => {
    const tree = buildTreeFromDocs([
      wikiDoc('/wiki/', 'log.md'),
      wikiDoc('/wiki/', 'plan.md', { title: 'Plan' }),
      wikiDoc('/wiki/', 'attention.md', { title: 'Attention' }),
      wikiDoc('/wiki/', 'overview.md', { title: 'Overview' }),
    ])
    expect(tree.map((n) => n.path)).toEqual(['overview.md', 'plan.md', 'attention.md', 'log.md'])
  })

  it('orders the same regardless of input order', () => {
    const docs = [
      wikiDoc('/wiki/', 'plan.md'),
      wikiDoc('/wiki/', 'log.md'),
      wikiDoc('/wiki/', 'overview.md'),
      wikiDoc('/wiki/', 'beta.md'),
      wikiDoc('/wiki/', 'alpha.md'),
    ]
    const expected = ['overview.md', 'plan.md', 'alpha.md', 'beta.md', 'log.md']
    expect(buildTreeFromDocs(docs).map((n) => n.path)).toEqual(expected)
    expect(buildTreeFromDocs([...docs].reverse()).map((n) => n.path)).toEqual(expected)
  })

  it('creates a title-cased folder node for orphan folders', () => {
    const tree = buildTreeFromDocs([wikiDoc('/wiki/deep-dives/', 'one.md', { document_number: 5 })])
    expect(tree).toEqual([
      { title: 'Deep Dives', children: [{ title: 'one', path: 'deep-dives/one.md', docNumber: 5 }] },
    ])
  })

  it('respects sort_order for children', () => {
    const tree = buildTreeFromDocs([
      wikiDoc('/wiki/topics/', 'b.md', { sort_order: 2 }),
      wikiDoc('/wiki/topics/', 'a.md', { sort_order: 1 }),
    ])
    expect(tree[0].children?.map((c) => c.path)).toEqual(['topics/a.md', 'topics/b.md'])
  })
})

describe('enrichTreeWithDocNumbers', () => {
  it('fills docNumber from matching docs and nulls unmatched or folder nodes', () => {
    const tree: WikiNode[] = [
      { title: 'A', path: 'a.md', children: [{ title: 'B', path: 'a/b.md' }] },
      { title: 'Folder', children: [{ title: 'Missing', path: 'missing.md' }] },
    ]
    const docs = [
      wikiDoc('/wiki/', 'a.md', { document_number: 1 }),
      wikiDoc('/wiki/a/', 'b.md', { document_number: 2 }),
    ]

    expect(enrichTreeWithDocNumbers(tree, docs)).toEqual([
      { title: 'A', path: 'a.md', docNumber: 1, children: [{ title: 'B', path: 'a/b.md', docNumber: 2, children: undefined }] },
      { title: 'Folder', docNumber: null, children: [{ title: 'Missing', path: 'missing.md', docNumber: null, children: undefined }] },
    ])
  })
})

describe('pruneMissingPages', () => {
  it('drops deleted leaves and keeps a deleted parent only as a folder for its surviving children', () => {
    const tree: WikiNode[] = [
      { title: 'Gone', path: 'gone.md', docNumber: 1 },
      { title: 'Deleted parent', path: 'parent.md', docNumber: 2, children: [{ title: 'Kept', path: 'parent/kept.md', docNumber: 3 }] },
      { title: 'Kept top', path: 'kept.md', docNumber: 4 },
    ]
    expect(pruneMissingPages(tree, new Set(['parent/kept.md', 'kept.md']))).toEqual([
      {
        title: 'Deleted parent', path: undefined, docNumber: null,
        children: [{ title: 'Kept', path: 'parent/kept.md', docNumber: 3, children: undefined }],
      },
      { title: 'Kept top', path: 'kept.md', docNumber: 4, children: undefined },
    ])
  })
})

describe('findFirstPath', () => {
  it('returns the first node with a path, depth-first', () => {
    const tree: WikiNode[] = [
      { title: 'Folder', children: [{ title: 'Inner', path: 'inner.md', docNumber: 7 }] },
      { title: 'Later', path: 'later.md', docNumber: 8 },
    ]
    expect(findFirstPath(tree)).toEqual({ path: 'inner.md', docNumber: 7 })
  })

  it('returns null when no node has a path', () => {
    expect(findFirstPath([{ title: 'Empty', children: [] }])).toBeNull()
  })
})
