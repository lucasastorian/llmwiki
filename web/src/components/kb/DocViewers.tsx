'use client'

import * as React from 'react'
import { Loader2, FileText } from 'lucide-react'
import { useUserStore } from '@/stores'
import { apiFetch } from '@/lib/api'
import dynamic from 'next/dynamic'

const PdfViewer = dynamic(() => import('@/components/viewer/PdfViewer'), { ssr: false })
const HtmlViewer = dynamic(() => import('@/components/viewer/HtmlViewer'), { ssr: false })

function useDocumentUrl(documentId: string) {
  const token = useUserStore((s) => s.accessToken)
  const [url, setUrl] = React.useState<string | null>(null)
  const [error, setError] = React.useState(false)

  React.useEffect(() => {
    if (!token) return
    let cancelled = false
    apiFetch<{ url: string }>(`/v1/documents/${documentId}/url`, token)
      .then((res) => { if (!cancelled) setUrl(res.url) })
      .catch(() => { if (!cancelled) setError(true) })
    return () => { cancelled = true }
  }, [documentId, token])

  return { url, error }
}

function LoadingSpinner() {
  return (
    <div className="flex items-center justify-center h-full">
      <Loader2 className="size-5 animate-spin text-muted-foreground" />
    </div>
  )
}

function ErrorMessage({ message }: { message: string }) {
  return (
    <div className="flex items-center justify-center h-full">
      <p className="text-sm text-destructive">{message}</p>
    </div>
  )
}

export function PdfDocViewer({ documentId, title }: { documentId: string; title: string }) {
  const { url, error } = useDocumentUrl(documentId)
  if (error) return <ErrorMessage message="Failed to load PDF" />
  if (!url) return <LoadingSpinner />
  return <PdfViewer fileUrl={url} title={title} />
}

export function ImageViewer({ documentId, title }: { documentId: string; title: string }) {
  const { url, error } = useDocumentUrl(documentId)
  if (error) return <ErrorMessage message="Failed to load image" />
  if (!url) return <LoadingSpinner />

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center px-4 py-1.5 border-b border-border text-xs text-muted-foreground shrink-0">
        <span className="truncate text-foreground">{title}</span>
      </div>
      <div className="flex-1 overflow-auto flex items-center justify-center p-4 bg-muted/30">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={url} alt={title} className="max-w-full max-h-full object-contain rounded-md" />
      </div>
    </div>
  )
}

export function HtmlDocViewer({ documentId, title }: { documentId: string; title: string }) {
  const { url, error } = useDocumentUrl(documentId)
  if (error) return <ErrorMessage message="Failed to load HTML" />
  if (!url) return <LoadingSpinner />

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center px-4 py-1.5 border-b border-border text-xs text-muted-foreground shrink-0">
        <span className="truncate text-foreground">{title}</span>
      </div>
      <HtmlViewer fileUrl={url} className="flex-1" />
    </div>
  )
}

export function ContentViewer({ documentId, title, fileType }: { documentId: string; title: string; fileType: string }) {
  const token = useUserStore((s) => s.accessToken)
  const [content, setContent] = React.useState<string | null>(null)
  const [error, setError] = React.useState(false)

  React.useEffect(() => {
    if (!token) return
    let cancelled = false
    apiFetch<{ content: string }>(`/v1/documents/${documentId}/content`, token)
      .then((res) => { if (!cancelled) setContent(res.content ?? '') })
      .catch(() => { if (!cancelled) setError(true) })
    return () => { cancelled = true }
  }, [documentId, token])

  if (error) return <ErrorMessage message="Failed to load content" />
  if (content === null) return <LoadingSpinner />

  const isHtml = fileType === 'html' || fileType === 'htm'

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center px-4 py-1.5 border-b border-border text-xs text-muted-foreground shrink-0">
        <span className="truncate text-foreground">{title}</span>
      </div>
      {isHtml ? (
        <iframe
          srcDoc={content}
          sandbox="allow-same-origin"
          className="flex-1 w-full bg-white"
          title={title}
        />
      ) : (
        <div className="flex-1 overflow-auto">
          <div className="max-w-3xl mx-auto px-8 py-6 prose prose-sm dark:prose-invert">
            <pre className="whitespace-pre-wrap text-sm font-mono">{content}</pre>
          </div>
        </div>
      )}
    </div>
  )
}

export function UnsupportedViewer({ title }: { title: string }) {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4 p-8">
      <div className="flex items-center justify-center w-16 h-16 rounded-xl bg-muted">
        <FileText size={28} className="text-muted-foreground" />
      </div>
      <div className="text-center">
        <h1 className="text-lg font-medium">{title}</h1>
        <p className="text-xs text-muted-foreground mt-2">File viewer coming soon</p>
      </div>
    </div>
  )
}

export function ProcessingViewer({ title }: { title: string }) {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4 p-8">
      <Loader2 className="size-8 animate-spin text-muted-foreground" />
      <div className="text-center">
        <h1 className="text-lg font-medium">{title}</h1>
        <p className="text-xs text-muted-foreground mt-2">Processing document...</p>
      </div>
    </div>
  )
}

export function FailedViewer({ title, errorMessage }: { title: string; errorMessage?: string | null }) {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4 p-8">
      <div className="flex items-center justify-center w-16 h-16 rounded-xl bg-destructive/10">
        <FileText size={28} className="text-destructive" />
      </div>
      <div className="text-center">
        <h1 className="text-lg font-medium">{title}</h1>
        <p className="text-xs text-destructive mt-2">Processing failed</p>
        {errorMessage && (
          <p className="text-xs text-muted-foreground mt-1 max-w-sm">{errorMessage}</p>
        )}
      </div>
    </div>
  )
}
