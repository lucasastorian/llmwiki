'use client'

import * as React from 'react'
import { useParams, useSearchParams, useRouter } from 'next/navigation'
import { useKBStore, useUserStore } from '@/stores'
import { useKBDocuments } from '@/hooks/useKBDocuments'
import { KBDetail } from '@/components/kb/KBDetail'
import { Loader2 } from 'lucide-react'

export type ViewMode = 'wiki' | 'files' | 'graph'

interface ParsedRoute {
  view: ViewMode
  filesPath: string
}

function parseRoute(pathSegments?: string[]): ParsedRoute {
  if (!pathSegments || pathSegments.length === 0) {
    return { view: 'wiki', filesPath: '/' }
  }
  switch (pathSegments[0]) {
    case 'files': {
      const rest = pathSegments.slice(1)
      const filesPath = rest.length > 0
        ? '/' + rest.map(decodeURIComponent).join('/') + '/'
        : '/'
      return { view: 'files', filesPath }
    }
    case 'graph':
      return { view: 'graph', filesPath: '/' }
    default:
      return { view: 'wiki', filesPath: '/' }
  }
}

export default function KBPage() {
  const router = useRouter()
  const params = useParams<{ slug: string; path?: string[] }>()
  const searchParams = useSearchParams()
  const knowledgeBases = useKBStore((s) => s.knowledgeBases)
  const kbLoading = useKBStore((s) => s.loading)
  const user = useUserStore((s) => s.user)

  const kb = React.useMemo(
    () => knowledgeBases.find((k) => k.slug === params.slug),
    [knowledgeBases, params.slug],
  )

  // ── Legacy param redirects ──────────────────────────────────
  const legacyPage = searchParams.get('page')
  const legacyDoc = searchParams.get('doc')

  // ?doc=N → /files?doc=N (no lookup needed)
  // ?page=X → need to look up document_number from path
  const needsDocLookup = !!legacyPage
  const { documents: legacyDocs, loading: legacyLoading } = useKBDocuments(
    needsDocLookup ? (kb?.id ?? '') : '',
  )

  React.useEffect(() => {
    if (!kb) return
    if (legacyDoc) {
      router.replace(`/wikis/${kb.slug}?p=${legacyDoc}`)
      return
    }
    if (legacyPage && !legacyLoading) {
      const wikiPath = legacyPage.replace(/^\/wiki\/?/, '')
      const doc = legacyDocs.find((d) => {
        const relative = (d.path + d.filename).replace(/^\/wiki\/?/, '')
        return relative === wikiPath
      })
      if (doc?.document_number != null) {
        router.replace(`/wikis/${kb.slug}?p=${doc.document_number}`)
      } else {
        router.replace(`/wikis/${kb.slug}`)
      }
    }
  }, [legacyDoc, legacyPage, kb, legacyLoading, legacyDocs, router])

  // Show spinner while redirecting legacy params or loading KB list
  if (kbLoading || !user || legacyDoc || legacyPage) {
    return (
      <div className="flex items-center justify-center h-full bg-background">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (!kb) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-2 bg-background">
        <h1 className="text-lg font-medium">Wiki not found</h1>
        <p className="text-sm text-muted-foreground">
          The wiki &ldquo;{params.slug}&rdquo; does not exist or you don&apos;t have access.
        </p>
      </div>
    )
  }

  const route = parseRoute(params.path)

  return (
    <KBDetail
      key={kb.id}
      kbId={kb.id}
      kbSlug={kb.slug}
      kbName={kb.name}
      viewMode={route.view}
      routeFilesPath={route.filesPath}
    />
  )
}
