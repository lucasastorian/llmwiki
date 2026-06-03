'use client'

import * as React from 'react'
import { useEditor, EditorContent } from '@tiptap/react'
import { Check, Loader2, MessageSquarePlus, Pencil, X } from 'lucide-react'

import { apiFetch, getDocumentsWsUrl } from '@/lib/api'
import { refreshAccessToken } from '@/lib/auth-token'
import { useUserStore } from '@/stores'
import { cn } from '@/lib/utils'
import { createMarkdownExtensions } from '@/lib/tiptap/extensions'
import { canonicalPlaintextFromTipTapDoc } from '@/lib/highlights/canonicalPlaintext'
import { decorationsFromHighlights } from '@/lib/highlights/applyHighlights'
import { highlightPluginKey } from '@/lib/highlights/decorationPlugin'
import { sanitizeUrl } from '@/components/editor/PropertyEditors'
import type { Highlight, HighlightsResponse, TextAnchor } from '@/lib/highlights/types'
import type { Document } from '@/lib/types'

interface ContentResponse {
  id: string
  content: string
  version: number
}

interface UrlResponse {
  url: string
}

interface WebclipAssetMetadata {
  src?: string
  path?: string
  filename?: string
  document_id?: string
  width?: number | null
  height?: number | null
}

interface DocumentChangeEvent {
  event?: string
  id?: string
}

interface Props {
  documentId: string
  className?: string
}

interface EditorSelection {
  from: number
  to: number
}

const isLocal = process.env.NEXT_PUBLIC_MODE === 'local'
const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
const HIGHLIGHT_POLL_INTERVAL = 2000

export default function MarkdownClipViewer({ documentId, className }: Props) {
  const token = useUserStore((s) => s.accessToken)
  const [markdown, setMarkdown] = React.useState<string | null>(null)
  const [highlights, setHighlights] = React.useState<Highlight[] | null>(null)
  const [highlightVersion, setHighlightVersion] = React.useState<number>(0)
  const [knowledgeBaseId, setKnowledgeBaseId] = React.useState<string | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [isEditing, setIsEditing] = React.useState(false)
  const [selection, setSelection] = React.useState<EditorSelection | null>(null)
  const [commentOpen, setCommentOpen] = React.useState(false)
  const [commentDraft, setCommentDraft] = React.useState('')
  const [commentError, setCommentError] = React.useState<string | null>(null)
  const [savingComment, setSavingComment] = React.useState(false)
  const [savingEdit, setSavingEdit] = React.useState(false)
  const [notice, setNotice] = React.useState<string | null>(null)
  const docRef = React.useRef<Document | null>(null)
  const imageUrlsRef = React.useRef<Record<string, string>>({})
  const imageAttrsRef = React.useRef<Record<string, Record<string, unknown>>>({})

  const loadHighlights = React.useCallback(async () => {
    if (!isLocal && !token) return
    const res = await apiFetch<HighlightsResponse>(
      `/v1/documents/${documentId}/highlights`,
      token ?? '',
    )
    setHighlights(res.highlights ?? [])
    setHighlightVersion(res.version ?? 0)
  }, [documentId, token])

  const editor = useEditor({
    immediatelyRender: false,
    editable: false,
    extensions: createMarkdownExtensions({
      imageSrcResolver: (src) => {
        const resolved = imageUrlsRef.current[normalizeImageSrc(src)]
        if (resolved) return resolved
        return localWebclipFileUrl(docRef.current, src) ?? src
      },
      imageAttrsResolver: (src) => imageAttrsRef.current[normalizeImageSrc(src)] ?? {},
    }),
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
    if (!notice) return
    const timeout = window.setTimeout(() => setNotice(null), 2400)
    return () => window.clearTimeout(timeout)
  }, [notice])

  React.useEffect(() => {
    if (!isLocal && !token) return
    let cancelled = false
    const apiToken = token ?? ''
    setError(null)
    setMarkdown(null)
    setHighlights(null)
    setHighlightVersion(0)
    setKnowledgeBaseId(null)
    setIsEditing(false)
    setSelection(null)
    setCommentOpen(false)
    setCommentDraft('')
    setCommentError(null)
    setNotice(null)
    docRef.current = null
    imageUrlsRef.current = {}
    imageAttrsRef.current = {}

    Promise.all([
      apiFetch<Document>(`/v1/documents/${documentId}`, apiToken),
      apiFetch<ContentResponse>(`/v1/documents/${documentId}/content`, apiToken),
      apiFetch<HighlightsResponse>(`/v1/documents/${documentId}/highlights`, apiToken).catch(
        () => ({ id: documentId, version: 0, highlights: [] }),
      ),
    ])
      .then(async ([doc, content, highlightResponse]) => {
        const imageUrls = await resolveWebclipAssetUrls(doc, apiToken)
        if (cancelled) return
        docRef.current = doc
        imageUrlsRef.current = imageUrls
        imageAttrsRef.current = resolveWebclipImageAttrs(doc)
        setKnowledgeBaseId(doc.knowledge_base_id)
        setMarkdown(content.content ?? '')
        setHighlights(highlightResponse.highlights ?? [])
        setHighlightVersion(highlightResponse.version ?? 0)
      })
      .catch((err) => {
        if (!cancelled) setError(err?.message ?? 'Failed to load document')
      })

    return () => {
      cancelled = true
    }
  }, [documentId, token])

  React.useEffect(() => {
    if (!editor) return
    editor.setEditable(isEditing)
  }, [editor, isEditing])

  React.useEffect(() => {
    if (!editor) return

    const updateSelection = () => {
      const { from, to, empty } = editor.state.selection
      if (empty || isEditing) {
        setSelection(null)
        return
      }

      const selectedText = editor.state.doc.textBetween(from, to, ' ').trim()
      setSelection(selectedText ? { from, to } : null)
    }

    updateSelection()
    editor.on('selectionUpdate', updateSelection)
    editor.on('transaction', updateSelection)
    return () => {
      editor.off('selectionUpdate', updateSelection)
      editor.off('transaction', updateSelection)
    }
  }, [editor, isEditing])

  React.useEffect(() => {
    if ((!isLocal && !token) || !knowledgeBaseId) return

    if (isLocal) {
      const interval = setInterval(() => {
        loadHighlights().catch(() => {})
      }, HIGHLIGHT_POLL_INTERVAL)
      return () => clearInterval(interval)
    }

    let cancelled = false
    const wsToken = token
    if (!wsToken) return
    const ws = new WebSocket(getDocumentsWsUrl(knowledgeBaseId))

    ws.onopen = () => {
      ws.send(wsToken)
    }

    ws.onmessage = (message) => {
      if (cancelled) return
      let event: DocumentChangeEvent | null = null
      try {
        event = JSON.parse(message.data)
      } catch {
        return
      }
      if (event?.id !== documentId || event.event !== 'UPDATE') return
      loadHighlights().catch(() => {})
    }

    ws.onclose = (event) => {
      if (cancelled || event.code !== 4001) return
      refreshAccessToken().catch(() => {})
    }

    return () => {
      cancelled = true
      ws.onclose = null
      ws.close()
    }
  }, [documentId, knowledgeBaseId, loadHighlights, token])

  React.useEffect(() => {
    if (!isLocal && !token) return

    const refresh = () => {
      if (document.visibilityState === 'hidden') return
      loadHighlights().catch(() => {})
    }

    document.addEventListener('visibilitychange', refresh)
    window.addEventListener('focus', refresh)
    return () => {
      document.removeEventListener('visibilitychange', refresh)
      window.removeEventListener('focus', refresh)
    }
  }, [loadHighlights, token])

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
  }, [editor, markdown, highlights, highlightVersion])

  const beginEdit = React.useCallback(() => {
    if (!editor) return
    setCommentOpen(false)
    setCommentError(null)
    setIsEditing(true)
    window.requestAnimationFrame(() => editor.commands.focus())
  }, [editor])

  const saveEdit = React.useCallback(async () => {
    if (!editor || (!isLocal && !token) || savingEdit) return
    setSavingEdit(true)
    setError(null)
    try {
      const content = String((editor.storage as { markdown?: { getMarkdown?: () => string } }).markdown?.getMarkdown?.() ?? '')
      const res = await apiFetch<ContentResponse>(
        `/v1/documents/${documentId}/content`,
        token ?? '',
        {
          method: 'PUT',
          body: JSON.stringify({ content }),
        },
      )
      setMarkdown(res.content ?? content)
      setIsEditing(false)
      setNotice('Saved')
    } catch (err) {
      setNotice(null)
      setError(err instanceof Error ? err.message : 'Failed to save document')
    } finally {
      setSavingEdit(false)
    }
  }, [documentId, editor, savingEdit, token])

  const openComment = React.useCallback(() => {
    if (!selection || isEditing) return
    setCommentDraft('')
    setCommentError(null)
    setCommentOpen(true)
  }, [isEditing, selection])

  const saveComment = React.useCallback(async () => {
    if (!editor || (!isLocal && !token) || !selection || savingComment) return
    const textAnchor = textAnchorFromSelection(
      canonicalPlaintextFromTipTapDoc(editor.state.doc),
      selection.from,
      selection.to,
    )
    if (!textAnchor) {
      setCommentError('Select text in the article first.')
      return
    }

    setSavingComment(true)
    setCommentError(null)
    try {
      const highlight: Highlight = {
        id: createHighlightId(),
        type: 'text',
        anchor: null,
        textAnchor,
        comment: commentDraft.trim() || null,
        color: 'yellow',
        createdAt: new Date().toISOString(),
      }
      const res = await apiFetch<HighlightsResponse>(
        `/v1/documents/${documentId}/highlights`,
        token ?? '',
        {
          method: 'POST',
          body: JSON.stringify({ highlight }),
        },
      )
      setHighlights(res.highlights ?? [])
      setHighlightVersion(res.version ?? highlightVersion + 1)
      setCommentOpen(false)
      setCommentDraft('')
      setSelection(null)
      setNotice(commentDraft.trim() ? 'Comment saved' : 'Highlight saved')
      editor.commands.setTextSelection(selection.to)
    } catch (err) {
      setCommentError(err instanceof Error ? err.message : 'Failed to save comment')
    } finally {
      setSavingComment(false)
    }
  }, [commentDraft, documentId, editor, highlightVersion, savingComment, selection, token])

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
    <div className={cn('relative h-full overflow-y-auto bg-background', className)}>
      <div className="sticky top-3 z-20 mx-auto flex max-w-3xl justify-end px-8 pointer-events-none">
        <div className="relative flex items-center gap-1 rounded-md border border-border/80 bg-background/95 p-1 shadow-sm pointer-events-auto">
          {notice && (
            <span className="px-2 text-xs font-medium text-emerald-700 dark:text-emerald-400">
              {notice}
            </span>
          )}
          {!isEditing && (
            <button
              type="button"
              onMouseDown={(event) => event.preventDefault()}
              onClick={openComment}
              disabled={!selection}
              className={cn(
                'inline-flex size-7 items-center justify-center rounded-sm transition-colors',
                selection
                  ? 'text-muted-foreground hover:bg-accent hover:text-foreground'
                  : 'text-muted-foreground/35 cursor-default',
              )}
              title="Add comment"
              aria-label="Add comment"
            >
              <MessageSquarePlus className="size-3.5" />
            </button>
          )}
          {isEditing ? (
            <button
              type="button"
              onClick={saveEdit}
              disabled={savingEdit}
              className="inline-flex size-7 items-center justify-center rounded-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:cursor-default disabled:opacity-60"
              title="Save"
              aria-label="Save"
            >
              {savingEdit ? <Loader2 className="size-3.5 animate-spin" /> : <Check className="size-3.5" />}
            </button>
          ) : (
            <button
              type="button"
              onClick={beginEdit}
              className="inline-flex size-7 items-center justify-center rounded-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              title="Edit"
              aria-label="Edit"
            >
              <Pencil className="size-3.5" />
            </button>
          )}

          {commentOpen && (
            <div className="absolute right-0 top-[calc(100%+8px)] w-72 rounded-md border border-border bg-popover p-3 shadow-lg">
              <div className="flex items-center gap-2">
                <textarea
                  value={commentDraft}
                  onChange={(event) => setCommentDraft(event.target.value)}
                  placeholder="Comment"
                  rows={3}
                  className="min-h-20 w-full resize-none rounded-md border border-input bg-background px-2.5 py-2 text-sm outline-none transition-colors placeholder:text-muted-foreground focus:border-ring"
                  autoFocus
                />
                <button
                  type="button"
                  onClick={() => {
                    setCommentOpen(false)
                    setCommentDraft('')
                    setCommentError(null)
                  }}
                  className="self-start rounded-sm p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                  aria-label="Cancel"
                  title="Cancel"
                >
                  <X className="size-3.5" />
                </button>
              </div>
              {commentError && (
                <p className="mt-2 text-xs text-destructive">{commentError}</p>
              )}
              <div className="mt-3 flex justify-end">
                <button
                  type="button"
                  onClick={saveComment}
                  disabled={savingComment}
                  className="inline-flex h-7 items-center gap-1.5 rounded-md bg-primary px-2.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-default disabled:opacity-60"
                >
                  {savingComment && <Loader2 className="size-3 animate-spin" />}
                  Save
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
      <div className="max-w-3xl mx-auto px-8 py-10">
        <EditorContent editor={editor} />
      </div>
    </div>
  )
}

function normalizeImageSrc(src: string): string {
  return src.trim().replace(/^\.?\//, '')
}

function localWebclipFileUrl(doc: Document | null, src: string): string | null {
  if (!isLocal || !doc) return null
  const trimmed = src.trim()
  if (!trimmed || /^[a-z][a-z0-9+.-]*:/i.test(trimmed)) return null

  const normalizedSrc = normalizeImageSrc(trimmed)
  const docDir = String(doc.path ?? '').trim().replace(/^\/+|\/+$/g, '')
  const key = docDir && !normalizedSrc.startsWith(`${docDir}/`)
    ? `${docDir}/${normalizedSrc}`
    : normalizedSrc
  if (!key) return null

  const encodedKey = key.split('/').map(encodeURIComponent).join('/')
  return `${API_URL.replace(/\/+$/, '')}/v1/files/${encodedKey}`
}

async function resolveWebclipAssetUrls(doc: Document, token: string): Promise<Record<string, string>> {
  const metadata = doc.metadata ?? {}
  const assets = Array.isArray(metadata.assets)
    ? (metadata.assets as WebclipAssetMetadata[])
    : []
  if (!assets.length) return {}

  const urls: Record<string, string> = {}
  if (isLocal) {
    for (const asset of assets) {
      const keys = [asset.src, asset.path, asset.filename].filter(Boolean) as string[]
      for (const key of keys) {
        const localUrl = localWebclipFileUrl(doc, key)
        if (localUrl) urls[normalizeImageSrc(key)] = localUrl
      }
    }
  }

  const pairs = await Promise.all(
    assets.map(async (asset) => {
      if (!asset.document_id) return null
      try {
        const res = await apiFetch<UrlResponse>(`/v1/documents/${asset.document_id}/url`, token)
        const keys = [asset.src, asset.path, asset.filename].filter(Boolean) as string[]
        return { keys, url: res.url }
      } catch {
        return null
      }
    }),
  )

  for (const pair of pairs) {
    if (!pair) continue
    for (const key of pair.keys) {
      urls[normalizeImageSrc(key)] = pair.url
    }
  }
  return urls
}

function resolveWebclipImageAttrs(doc: Document): Record<string, Record<string, unknown>> {
  const metadata = doc.metadata ?? {}
  const assets = Array.isArray(metadata.assets)
    ? (metadata.assets as WebclipAssetMetadata[])
    : []
  if (!assets.length) return {}

  const attrs: Record<string, Record<string, unknown>> = {}
  for (const asset of assets) {
    const width = normalizeDimension(asset.width)
    const height = normalizeDimension(asset.height)
    if (!width && !height) continue

    const renderedAttrs: Record<string, unknown> = {}
    if (width) renderedAttrs.width = width
    if (height) renderedAttrs.height = height

    const maxWidth = width ? Math.min(width, 736) : 736
    const maxHeight = height ? Math.min(height, 560) : 560
    renderedAttrs.style = [
      `width: ${width ? `${width}px` : 'auto'}`,
      `max-width: min(100%, ${maxWidth}px)`,
      `max-height: ${maxHeight}px`,
      'height: auto',
      'object-fit: contain',
    ].join('; ')

    const keys = [asset.src, asset.path, asset.filename].filter(Boolean) as string[]
    for (const key of keys) {
      attrs[normalizeImageSrc(key)] = renderedAttrs
    }
  }
  return attrs
}

function normalizeDimension(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  const rounded = Math.round(value)
  return rounded > 0 ? rounded : null
}

function createHighlightId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
}

function textAnchorFromSelection(
  canonical: ReturnType<typeof canonicalPlaintextFromTipTapDoc>,
  from: number,
  to: number,
): TextAnchor | null {
  let start = -1
  let end = -1

  for (let i = 0; i < canonical.charToPos.length; i += 1) {
    const pos = canonical.charToPos[i]
    if (pos === null || pos < from || pos >= to) continue
    if (start === -1) start = i
    end = i + 1
  }

  if (start === -1 || end <= start) return null

  while (start < end && /\s/.test(canonical.text[start])) start += 1
  while (end > start && /\s/.test(canonical.text[end - 1])) end -= 1
  if (end <= start) return null

  const textContent = canonical.text.slice(start, end)
  return {
    textStart: start,
    textEnd: end,
    textContent,
    prefix: canonical.text.slice(Math.max(0, start - 80), start) || null,
    suffix: canonical.text.slice(end, end + 80) || null,
  }
}
