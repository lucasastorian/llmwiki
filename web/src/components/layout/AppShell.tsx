'use client'

import { usePathname } from 'next/navigation'
import { McpConnectionDock } from '@/components/connections/McpConnectionDock'
import { UploadProgressPanel } from '@/components/uploads/UploadProgressPanel'
import { useKBStore } from '@/stores'

const isLocal = process.env.NEXT_PUBLIC_MODE === 'local'

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const knowledgeBases = useKBStore((state) => state.knowledgeBases)
  const wikiSlug = pathname.match(/^\/wikis\/([^/]+)/)?.[1] ?? null
  const wiki = wikiSlug ? knowledgeBases.find((item) => item.slug === wikiSlug) : undefined
  const showConnectionDock = !isLocal && Boolean(wiki)

  return (
    <div className="h-dvh overflow-hidden bg-background">
      <main className="h-full overflow-y-auto">{children}</main>
      {showConnectionDock && <McpConnectionDock key={wiki?.slug} wikiName={wiki?.name} />}
      <UploadProgressPanel raisedForConnectionDock={showConnectionDock} />
    </div>
  )
}
