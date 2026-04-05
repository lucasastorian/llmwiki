'use client'

import React, { useEffect, useRef, useState } from 'react'
import { ExternalLink, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'

type Props = {
  fileUrl: string
  sourceUrl?: string | null
  highlightIds?: string[]
  className?: string
}

function buildHighlightCss(ids: string[]): string {
  if (!ids.length) return ''

  const selectors = ids.map((id) => `#${CSS.escape(id)}`).join(',\n')

  return `
<style>
${selectors} {
  background-color: rgba(255, 235, 59, 0.55) !important;
  outline: 1.5px solid rgba(255, 180, 0, 0.7);
  border-radius: 2px;
}
</style>`
}

export default function HtmlViewer({ fileUrl, sourceUrl, highlightIds = [], className }: Props) {
  const iframeRef = useRef<HTMLIFrameElement>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [srcdoc, setSrcdoc] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    setSrcdoc(null)

    fetch(fileUrl)
      .then((res) => {
        if (!res.ok) throw new Error(`Failed to load: ${res.status}`)
        return res.text()
      })
      .then((html) => {
        if (cancelled) return
        const highlighted = html + buildHighlightCss(highlightIds)
        setSrcdoc(highlighted)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => { cancelled = true }
  }, [fileUrl, highlightIds])

  const handleIframeLoad = () => {
    setLoading(false)
    if (highlightIds.length && iframeRef.current?.contentDocument) {
      const el = iframeRef.current.contentDocument.getElementById(highlightIds[0])
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3">
        <p className="text-sm text-muted-foreground">Failed to load document</p>
        {sourceUrl && (
          <a
            href={sourceUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
          >
            <ExternalLink className="size-3.5" />
            Open original page
          </a>
        )}
      </div>
    )
  }

  return (
    <iframe
      ref={iframeRef}
      srcDoc={srcdoc ?? ''}
      sandbox="allow-same-origin"
      className={cn('w-full h-full border-0 bg-white', className)}
      title="Document viewer"
      onLoad={handleIframeLoad}
    />
  )
}
