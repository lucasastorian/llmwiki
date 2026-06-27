'use client'

import * as React from 'react'
import { useParams, useSearchParams, useRouter } from 'next/navigation'
import { useKBStore, useUserStore } from '@/stores'
import { useKBDocuments } from '@/hooks/useKBDocuments'
import { WikiOnlyDetail } from '@/components/kb/WikiOnlyDetail'
import { Loader2 } from 'lucide-react'

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

  // ── Legacy ?page= redirect (old URL format) ─────────────────
  const legacyPage = searchParams.get('page')
  const needsDocLookup = !!legacyPage
  const { documents: legacyDocs, loading: legacyLoading } = useKBDocuments(
    needsDocLookup ? (kb?.id ?? '') : '',
  )

  React.useEffect(() => {
    if (!kb || !legacyPage || legacyLoading) return
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
  }, [legacyPage, kb, legacyLoading, legacyDocs, router])

  // Show spinner while redirecting legacy params or loading KB list
  if (kbLoading || !user || legacyPage) {
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

  return (
    <WikiOnlyDetail
      key={kb.id}
      kbId={kb.id}
      kbSlug={kb.slug}
      kbName={kb.name}
    />
  )
}
