'use client'

import * as React from 'react'
import { useParams } from 'next/navigation'
import { useKBStore } from '@/stores'
import { KBDetail } from '@/components/kb/KBDetail'
import { Loader2 } from 'lucide-react'

export default function KBPage() {
  const params = useParams<{ slug: string }>()
  const knowledgeBases = useKBStore((s) => s.knowledgeBases)
  const loading = useKBStore((s) => s.loading)

  const kb = React.useMemo(
    () => knowledgeBases.find((k) => k.slug === params.slug),
    [knowledgeBases, params.slug]
  )

  if (loading) {
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

  return <KBDetail key={kb.id} kbId={kb.id} kbSlug={kb.slug} kbName={kb.name} />
}
