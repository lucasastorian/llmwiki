'use client'

import * as React from 'react'
import { useEditor, EditorContent } from '@tiptap/react'
import { Loader2 } from 'lucide-react'

import { apiFetch } from '@/lib/api'
import { useUserStore } from '@/stores'
import { cn } from '@/lib/utils'
import { createMarkdownExtensions } from '@/lib/tiptap/extensions'
import { canonicalPlaintextFromTipTapDoc } from '@/lib/highlights/canonicalPlaintext'
import { decorationsFromHighlights } from '@/lib/highlights/applyHighlights'
import { highlightPluginKey } from '@/lib/highlights/decorationPlugin'
import { sanitizeUrl } from '@/components/editor/PropertyEditors'
import type { Highlight, HighlightsResponse } from '@/lib/highlights/types'

interface ContentResponse {
  id: string
  content: string
  version: number
}

interface Props {
  documentId: string
  className?: string
}

export default function MarkdownClipViewer({ documentId, className }: Props) {
  const token = useUserStore((s) => s.accessToken)
  const [markdown, setMarkdown] = React.useState<string | null>(null)
  const [highlights, setHighlights] = React.useState<Highlight[] | null>(null)
  const [error, setError] = React.useState<string | null>(null)

  const editor = useEditor({
    immediatelyRender: false,
    editable: false,
    extensions: createMarkdownExtensions(),
    editorProps: {
      attributes: {
        class:
          'prose prose-sm dark:prose-invert max-w-none focus:outline-none select-text',
      },
      // Read mode: links don't open by default (Link extension is configured
      // with openOnClick: false in the shared factory). Keep that off so
      // selection inside a link doesn't navigate, but still let an explicit
      // click open the URL safely in a new tab.
      handleClick: (_view, _pos, event) => {
        const anchor = (event.target as HTMLElement).closest('a')
        if (!anchor) return false
        const href = anchor.getAttribute('href')
        if (!href) return false
        const safeHref = sanitizeUrl(href)
        if (safeHref) window.open(safeHref, '_blank', 'noopener,noreferrer')
        return true
      },
    },
  })

  React.useEffect(() => {
    if (!token) return
    let cancelled = false
    setError(null)
    setMarkdown(null)
    setHighlights(null)

    const loadContent = apiFetch<ContentResponse>(
      `/v1/documents/${documentId}/content`,
      token,
    ).then((res) => {
      if (!cancelled) setMarkdown(res.content ?? '')
    })

    const loadHighlights = apiFetch<HighlightsResponse>(
      `/v1/documents/${documentId}/highlights`,
      token,
    )
      .then((res) => {
        if (!cancelled) setHighlights(res.highlights ?? [])
      })
      .catch(() => {
        if (!cancelled) setHighlights([])
      })

    Promise.all([loadContent, loadHighlights]).catch((err) => {
      if (!cancelled) setError(err?.message ?? 'Failed to load document')
    })

    return () => {
      cancelled = true
    }
  }, [documentId, token])

  // Set content on the editor once markdown is loaded.
  React.useEffect(() => {
    if (!editor || markdown === null) return
    editor.commands.setContent(markdown, { emitUpdate: false })
  }, [editor, markdown])

  // Apply highlights once both editor + highlights are ready. Done in a
  // requestAnimationFrame to give the editor a chance to settle after
  // setContent (TipTap rebuilds the doc tree synchronously, but waiting
  // one frame avoids occasional stale-doc issues with very large docs).
  React.useEffect(() => {
    if (!editor || markdown === null || highlights === null) return
    let raf = 0
    raf = requestAnimationFrame(() => {
      const canonical = canonicalPlaintextFromTipTapDoc(editor.state.doc)
      const ranges = decorationsFromHighlights(highlights, canonical)
      editor.view.dispatch(
        editor.state.tr.setMeta(highlightPluginKey, { setDecorations: ranges }),
      )
    })
    return () => cancelAnimationFrame(raf)
  }, [editor, markdown, highlights])

  if (error) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-sm text-destructive">{error}</p>
      </div>
    )
  }

  if (markdown === null || !editor) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className={cn('h-full overflow-y-auto bg-background', className)}>
      <div className="max-w-3xl mx-auto px-8 py-10">
        <EditorContent editor={editor} />
      </div>
    </div>
  )
}
