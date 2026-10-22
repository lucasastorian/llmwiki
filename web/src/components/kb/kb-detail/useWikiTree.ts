import * as React from 'react'
import { apiFetch } from '@/lib/api'
import type { DocumentListItem, WikiNode } from '@/lib/types'
import { buildTreeFromDocs, enrichTreeWithDocNumbers, pruneMissingPages, wikiRelativePath } from '@/lib/wikiTree'
import { wikiTreeFingerprint } from '@/lib/wikiTreeFingerprint'

const SCAFFOLD_FILES = new Set(['index.json', 'overview.md', 'log.md'])

export interface WikiTreeState {
  wikiTree: WikiNode[]
  indexLoaded: boolean
  hasNavigableWiki: boolean
}

/** Loads the wiki nav tree from index.json, falling back to one derived from the wiki docs. */
export function useWikiTree(wikiDocs: DocumentListItem[], token: string | null): WikiTreeState {
  const indexDoc = wikiDocs.find((d) => d.filename === 'index.json' && d.path === '/wiki/')
  const hasNavigableWiki = React.useMemo(
    () => wikiDocs.some((d) => d.path === '/wiki/' ? !SCAFFOLD_FILES.has(d.filename) : true),
    [wikiDocs],
  )
  const [wikiTree, setWikiTree] = React.useState<WikiNode[]>([])
  const [indexLoaded, setIndexLoaded] = React.useState(false)

  const treeFingerprint = React.useMemo(() => wikiTreeFingerprint(wikiDocs), [wikiDocs])

  React.useEffect(() => {
    setIndexLoaded(false)
    if (!indexDoc || !token) {
      setWikiTree(buildTreeFromDocs(wikiDocs))
      setIndexLoaded(true)
      return
    }
    let cancelled = false
    apiFetch<{ content: string }>(`/v1/documents/${indexDoc.id}/content`, token)
      .then((res) => {
        if (cancelled) return
        setWikiTree(parseIndexTree(res.content, wikiDocs) ?? treeWithoutIndex(wikiDocs, indexDoc.id))
        setIndexLoaded(true)
      })
      .catch(() => {
        if (cancelled) return
        setWikiTree(treeWithoutIndex(wikiDocs, indexDoc.id))
        setIndexLoaded(true)
      })
    return () => { cancelled = true }
  }, [indexDoc?.id, indexDoc?.version, token, treeFingerprint])

  return { wikiTree, indexLoaded, hasNavigableWiki }
}

function parseIndexTree(content: string, wikiDocs: DocumentListItem[]): WikiNode[] | null {
  try {
    const parsed = JSON.parse(content)
    const existingPaths = new Set(wikiDocs.map(wikiRelativePath))
    return pruneMissingPages(enrichTreeWithDocNumbers(parsed.tree || [], wikiDocs), existingPaths)
  } catch {
    return null
  }
}

function treeWithoutIndex(wikiDocs: DocumentListItem[], indexDocId: string): WikiNode[] {
  return buildTreeFromDocs(wikiDocs.filter((d) => d.id !== indexDocId))
}
