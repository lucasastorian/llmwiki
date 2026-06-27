'use client'

import * as React from 'react'
import { useParams } from 'next/navigation'
import { Loader2 } from 'lucide-react'
import { useKBStore, useUserStore } from '@/stores'
import { KBDetail } from '@/components/kb/KBDetail'
import type { ViewMode } from '@/components/kb/viewMode'

export function KBDetailRoutePage({
  viewMode,
  routeFilesPath = '/',
}: {
  viewMode: ViewMode
  routeFilesPath?: string
}) {
  const params = useParams<{ slug: string }>()
  const knowledgeBases = useKBStore((s) => s.knowledgeBases)
  const kbLoading = useKBStore((s) => s.loading)
  const user = useUserStore((s) => s.user)

  const kb = React.useMemo(
    () => knowledgeBases.find((k) => k.slug === params.slug),
    [knowledgeBases, params.slug],
  )

  if (kbLoading || !user) {
    return (
      <div className="flex h-full items-center justify-center bg-background">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (!kb) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 bg-background">
        <h1 className="text-lg font-medium">Wiki not found</h1>
        <p className="text-sm text-muted-foreground">
          The wiki &ldquo;{params.slug}&rdquo; does not exist or you don&apos;t have access.
        </p>
      </div>
    )
  }

  return (
    <KBDetail
      key={kb.id}
      kbId={kb.id}
      kbSlug={kb.slug}
      kbName={kb.name}
      viewMode={viewMode}
      routeFilesPath={routeFilesPath}
    />
  )
}
