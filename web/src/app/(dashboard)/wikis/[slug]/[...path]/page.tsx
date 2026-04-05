'use client'

import * as React from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useKBStore } from '@/stores'
import { useKBDocuments } from '@/hooks/useKBDocuments'
import { Loader2 } from 'lucide-react'

function normalizeRequestedPath(pathSegments: string[] | undefined): string {
  if (!pathSegments || pathSegments.length === 0) return '/'
  return `/${pathSegments.map((segment) => decodeURIComponent(segment)).join('/')}`
}

function buildDocumentPath(path: string, filename: string): string {
  return `${path}${filename}`.replace(/\/+/g, '/')
}

export default function FilePage() {
  const router = useRouter()
  const params = useParams<{ slug: string; path: string[] }>()
  const knowledgeBases = useKBStore((s) => s.knowledgeBases)
  const kbLoading = useKBStore((s) => s.loading)

  const kb = React.useMemo(
    () => knowledgeBases.find((k) => k.slug === params.slug),
    [knowledgeBases, params.slug]
  )

  const { documents, loading: docsLoading } = useKBDocuments(kb?.id ?? '')

  const requestedPath = React.useMemo(
    () => normalizeRequestedPath(params.path),
    [params.path],
  )
  const legacyDocNumber = React.useMemo(
    () => parseInt(params.path?.[0] ?? '', 10),
    [params.path],
  )

  const document = React.useMemo(() => {
    if (!documents.length) return null

    const exactMatch = documents.find((d) => buildDocumentPath(d.path, d.filename) === requestedPath)
    if (exactMatch) return exactMatch

    if (!Number.isNaN(legacyDocNumber)) {
      return documents.find((d) => d.document_number === legacyDocNumber) ?? null
    }

    return null
  }, [documents, requestedPath, legacyDocNumber])

  React.useEffect(() => {
    if (kbLoading || !kb || docsLoading || !document) return

    const fullPath = buildDocumentPath(document.path, document.filename)
    if (document.path.startsWith('/wiki/')) {
      const wikiPath = fullPath.replace(/^\/wiki\/?/, '')
      router.replace(`/wikis/${params.slug}?page=${encodeURIComponent(wikiPath)}`)
      return
    }

    if (document.document_number != null) {
      router.replace(`/wikis/${params.slug}?doc=${document.document_number}`)
      return
    }

    router.replace(`/wikis/${params.slug}`)
  }, [kbLoading, kb, docsLoading, document, params.slug, router])

  if (kbLoading || (kb && docsLoading) || document) {
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
      </div>
    )
  }

  if (!document) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-2 bg-background">
        <h1 className="text-lg font-medium">Document not found</h1>
        <p className="text-sm text-muted-foreground">
          {requestedPath} does not exist in this wiki.
        </p>
        <button
          onClick={() => router.push(`/wikis/${params.slug}`)}
          className="mt-2 text-sm text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
        >
          Back to {kb.name}
        </button>
      </div>
    )
  }
}
