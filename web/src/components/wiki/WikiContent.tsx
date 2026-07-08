'use client'

import * as React from 'react'
import dynamic from 'next/dynamic'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import type { Components } from 'react-markdown'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { FileText, Copy, Check, Network, ChevronLeft, ChevronRight, ArrowRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import { apiFetch } from '@/lib/api'
import { useUserStore } from '@/stores'
import { ExpandableMedia } from './DiagramViewer'
import { WikiHighlighter } from './WikiHighlighter'
import type { DocumentListItem } from '@/lib/types'

const MermaidBlock = dynamic(() => import('./MermaidBlock').then((mod) => mod.MermaidBlock), {
  ssr: false,
  loading: () => (
    <pre className="my-3 overflow-x-auto rounded-lg border border-border bg-muted/60 p-4 text-[13px] leading-relaxed">
      Rendering diagram...
    </pre>
  ),
})

export interface TocItem {
  id: string
  text: string
  level: 2 | 3
}

export function extractTocFromMarkdown(md: string): TocItem[] {
  const items: TocItem[] = []
  const lines = md.split('\n')
  for (const line of lines) {
    const m2 = line.match(/^##\s+(.+)/)
    const m3 = line.match(/^###\s+(.+)/)
    if (m2) {
      const text = m2[1].replace(/\*\*/g, '').replace(/\[([^\]]+)\]\([^)]*\)/g, '$1').trim()
      items.push({ id: slugify(text), text, level: 2 })
    } else if (m3) {
      const text = m3[1].replace(/\*\*/g, '').replace(/\[([^\]]+)\]\([^)]*\)/g, '$1').trim()
      items.push({ id: slugify(text), text, level: 3 })
    }
  }
  return items
}

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\w\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
}

const FRONTMATTER_RE = /^\s*---[ \t]*\n[\s\S]*?\n---[ \t]*\n/

function stripFrontmatter(content: string): string {
  return content.replace(FRONTMATTER_RE, '')
}

function parseFrontmatterField(content: string, field: string): string | null {
  const fm = content.match(FRONTMATTER_RE)
  if (!fm) return null
  const line = fm[0].match(new RegExp(`^${field}:[ \\t]*(.+)$`, 'm'))
  if (!line) return null
  return line[1].trim().replace(/^["']|["']$/g, '') || null
}

// The page title is the body's leading H1; lift it into the chrome header so the eyebrow
// can sit above it and the description below it, then drop it from the rendered body.
function extractLeadingH1(body: string): { heading: string | null; rest: string } {
  const trimmed = body.replace(/^\s+/, '')
  const match = trimmed.match(/^#\s+(.+)\n?/)
  if (!match) return { heading: null, rest: body }
  return { heading: match[1].replace(/\*\*/g, '').trim(), rest: trimmed.slice(match[0].length) }
}

function humanizeSegment(segment: string): string {
  const text = segment.replace(/\.(md|txt|json)$/i, '').replace(/[-_]/g, ' ').trim()
  return text === text.toLowerCase() ? text.replace(/\b\w/g, (c) => c.toUpperCase()) : text
}

// Folder breadcrumb above the title, e.g. "concepts/policy.md" -> "Concepts".
function pathEyebrow(path: string | undefined): string | null {
  if (!path) return null
  const parts = path.replace(/^\/+/, '').split('/').filter(Boolean)
  parts.pop()
  if (parts.length === 0) return null
  return parts.map(humanizeSegment).join(' · ')
}

// Title-case an all-lowercase page name ("transformer" -> "Transformer"); leave
// intentional casing alone ("GRPO", "MAI-Base-1").
function toDisplayTitle(title: string): string {
  if (title !== title.toLowerCase()) return title
  return title.replace(/\b\w/g, (c) => c.toUpperCase())
}

interface MdastLike {
  type: string
  value?: string
  children?: MdastLike[]
}

// remark-math only parses dollar delimiters; models routinely author \( \) and \[ \],
// which markdown then eats as paren escapes. Convert to $ / $$ outside code fences and spans.
function normalizeMathDelimiters(md: string): string {
  const segments = md.split(/(```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)|`[^`\n]*`)/)
  return segments
    .map((segment, i) => {
      if (i % 2 === 1) return segment
      const converted = segment
        .replace(/\\\[([\s\S]+?)\\\]/g, (_, inner: string) => `$$${inner}$$`)
        .replace(/\\\((.+?)\\\)/g, (_, inner: string) => `$${inner.trim()}$`)
      return escapeCurrencyDollars(converted)
    })
    .join('')
}

// Currency ($100M) and inline math ($x_i$) share the $ delimiter, so remark-math
// mathifies "worth $100M that produces $10M/year". A $ immediately followed by a
// digit is currency — escape it — unless the span to its closing $ contains LaTeX syntax.
const MATH_SYNTAX = /[\\^_{}=+]/

function escapeCurrencyDollars(text: string): string {
  let out = ''
  let i = 0
  while (i < text.length) {
    const ch = text[i]
    if (ch === '\\' && text[i + 1] === '$') {
      out += '\\$'
      i += 2
      continue
    }
    if (ch !== '$') {
      out += ch
      i++
      continue
    }
    if (text[i + 1] === '$') {
      const close = text.indexOf('$$', i + 2)
      const end = close === -1 ? text.length : close + 2
      out += text.slice(i, end)
      i = end
      continue
    }
    if (!/\d/.test(text[i + 1] ?? '')) {
      out += ch
      i++
      continue
    }
    const paragraphEnd = text.indexOf('\n\n', i)
    const searchEnd = paragraphEnd === -1 ? text.length : paragraphEnd
    const close = text.indexOf('$', i + 1)
    const isMath = close !== -1 && close < searchEnd && MATH_SYNTAX.test(text.slice(i + 1, close))
    out += isMath ? ch : '\\$'
    i++
  }
  return out
}

// Models routinely double-escape LaTeX backslashes (\\log instead of \log) when authoring through tools;
// KaTeX reads \\ as a line break and fails. Restore a single backslash before a command letter.
// Genuine \\ line breaks are followed by whitespace or [, never a letter, so they are left intact.
// Also escape bare % — in LaTeX it starts a comment and silently eats the rest of the formula.
function remarkFixOverescapedMath() {
  const restore = (node: MdastLike): void => {
    if ((node.type === 'inlineMath' || node.type === 'math') && typeof node.value === 'string') {
      node.value = node.value
        .replace(/\\\\(?=[a-zA-Z])/g, '\\')
        .replace(/\\%|%/g, (m) => (m === '%' ? '\\%' : m))
    }
    node.children?.forEach(restore)
  }
  return restore
}

function TableOfContents({ items }: { items: TocItem[] }) {
  const [activeIndex, setActiveIndex] = React.useState(0)

  // Scroll-position spy on the real scroll container (the viewport-based
  // IntersectionObserver never fired because content scrolls in a nested div).
  React.useEffect(() => {
    if (items.length === 0) return
    const container = document.getElementById('wiki-scroll-container')
    if (!container) return
    const update = () => {
      const top = container.getBoundingClientRect().top
      let current = 0
      items.forEach((item, i) => {
        const el = document.getElementById(item.id)
        if (el && el.getBoundingClientRect().top - top < 120) current = i
      })
      setActiveIndex(current)
    }
    const raf = requestAnimationFrame(update)
    container.addEventListener('scroll', update, { passive: true })
    return () => {
      cancelAnimationFrame(raf)
      container.removeEventListener('scroll', update)
    }
  }, [items])

  if (items.length === 0) return null

  return (
    <nav>
      <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/50 mb-3 px-1">
        On this page
      </p>
      <div className="relative">
        <div className="absolute left-[3px] top-1.5 bottom-1.5 w-px bg-border" aria-hidden />
        {items.map((item, i) => {
          const state = i < activeIndex ? 'read' : i === activeIndex ? 'current' : 'upcoming'
          return (
            <a
              key={item.id}
              href={`#${item.id}`}
              onClick={(e) => {
                e.preventDefault()
                document.getElementById(item.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
              }}
              className={cn(
                'relative flex items-start py-1 text-xs leading-snug transition-colors',
                item.level === 3 ? 'pl-6' : 'pl-4',
                state === 'current'
                  ? 'text-foreground font-medium'
                  : state === 'read'
                    ? 'text-muted-foreground hover:text-foreground'
                    : 'text-muted-foreground/50 hover:text-muted-foreground',
              )}
            >
              <span
                aria-hidden
                className={cn(
                  'absolute left-0 top-[7px] size-[7px] rounded-full ring-2 ring-background transition-colors',
                  state === 'current'
                    ? 'bg-foreground'
                    : state === 'read'
                      ? 'bg-muted-foreground/50'
                      : 'bg-border',
                )}
              />
              <span className="min-w-0">{item.text}</span>
            </a>
          )
        })}
      </div>
    </nav>
  )
}

function parseFootnoteSources(content: string): Map<string, string> {
  const map = new Map<string, string>()
  // Match footnote definitions: [^1]: full source text until end of line
  const regex = /\[\^(\d+)\]:\s*(.+)$/gm
  let m
  while ((m = regex.exec(content)) !== null) {
    const num = m[1]
    let source = m[2].trim()
    // Strip surrounding bold markers
    source = source.replace(/^\*{1,2}/, '').replace(/\*{1,2}$/, '')
    // Clean up markdown links
    const linkMatch = source.match(/\[([^\]]+)\]\([^)]*\)/)
    if (linkMatch) source = linkMatch[1]
    map.set(num, source)
  }
  return map
}

function CitationBadge({
  num,
  source,
  onSourceClick,
}: {
  num: string
  source: string
  onSourceClick: (source: string, page?: number) => void
}) {
  const [isOpen, setIsOpen] = React.useState(false)
  const hoverTimeoutRef = React.useRef<ReturnType<typeof setTimeout> | null>(null)

  const handleMouseEnter = React.useCallback(() => {
    if (hoverTimeoutRef.current) clearTimeout(hoverTimeoutRef.current)
    hoverTimeoutRef.current = setTimeout(() => setIsOpen(true), 80)
  }, [])

  const handleMouseLeave = React.useCallback(() => {
    if (hoverTimeoutRef.current) clearTimeout(hoverTimeoutRef.current)
    hoverTimeoutRef.current = setTimeout(() => setIsOpen(false), 160)
  }, [])

  React.useEffect(() => {
    return () => {
      if (hoverTimeoutRef.current) clearTimeout(hoverTimeoutRef.current)
    }
  }, [])

  // Parse source into filename and page reference
  const parts = source.match(/^(.+?)(?:,\s*p\.?\s*(.+))?$/)
  const filename = parts?.[1]?.trim() ?? source
  const pageRef = parts?.[2]?.trim()
  const pageNum = pageRef ? parseInt(pageRef, 10) : undefined

  return (
    <Popover open={isOpen} onOpenChange={setIsOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          onMouseEnter={handleMouseEnter}
          onMouseLeave={handleMouseLeave}
          onClick={(e) => {
            e.preventDefault()
            onSourceClick(filename, pageNum)
          }}
          className="inline-flex items-center gap-0.5 px-1.5 py-0 text-[10px] font-medium bg-accent-blue/10 text-accent-blue rounded-full border border-accent-blue/20 hover:bg-accent-blue/20 transition-colors leading-tight cursor-pointer"
        >
          {num}
        </button>
      </PopoverTrigger>
      <PopoverContent
        side="top"
        align="center"
        sideOffset={6}
        className="w-64 p-0 overflow-hidden"
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
      >
        <div
          role="button"
          className="flex items-start gap-2.5 px-3 py-2.5 cursor-pointer hover:bg-accent/50 transition-colors"
          onClick={() => {
            setIsOpen(false)
            onSourceClick(filename, pageNum)
          }}
        >
          <span className="text-muted-foreground shrink-0 mt-0.5">
            <FileText className="size-4" />
          </span>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium line-clamp-2 leading-snug">
              {filename}
            </div>
            {pageRef && (
              <div className="text-xs text-muted-foreground mt-0.5">
                p. {pageRef}
              </div>
            )}
          </div>
        </div>
      </PopoverContent>
    </Popover>
  )
}

function WikiImage({
  src,
  alt,
  documents,
  wikiActivePath,
}: {
  src?: string
  alt?: string
  documents?: DocumentListItem[]
  wikiActivePath?: string
}) {
  const token = useUserStore((s) => s.accessToken)
  const [svgContent, setSvgContent] = React.useState<string | null>(null)
  const [imageUrl, setImageUrl] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(false)

  React.useEffect(() => {
    if (!src || !documents || !token) return
    // Only resolve relative paths (not http:// or data: URIs)
    if (src.startsWith('http') || src.startsWith('data:')) return

    // Resolve relative path: strip leading ./ and resolve against current wiki path
    let filename = src.replace(/^\.\//, '')
    const doc = documents.find((d) => {
      return d.filename === filename || d.filename === filename.split('/').pop()
    })

    if (!doc) return

    const isSvg = doc.file_type === 'svg'
    const isTextAsset = ['svg', 'csv', 'xml', 'html'].includes(doc.file_type)
    const isImageBinary = ['png', 'jpg', 'jpeg', 'webp', 'gif'].includes(doc.file_type)

    setLoading(true)

    if (isSvg || isTextAsset) {
      // Text-based assets stored in the content column — fetch via API
      apiFetch<{ content: string }>(`/v1/documents/${doc.id}/content`, token)
        .then((res) => {
          if (isSvg && res.content) {
            setSvgContent(res.content)
          } else if (res.content) {
            // For non-SVG text assets, render as data URI
            const blob = new Blob([res.content], { type: `image/${doc.file_type}+xml` })
            setImageUrl(URL.createObjectURL(blob))
          }
        })
        .catch(() => { /* silent fail — image just won't render */ })
        .finally(() => setLoading(false))
    } else if (isImageBinary) {
      // Binary images stored in S3 — use the /url endpoint
      apiFetch<{ url: string }>(`/v1/documents/${doc.id}/url`, token)
        .then((res) => setImageUrl(res.url))
        .catch(() => { /* silent fail */ })
        .finally(() => setLoading(false))
    } else {
      setLoading(false)
    }
  }, [src, documents, token, wikiActivePath])

  // Inline SVG rendering
  if (svgContent) {
    const dataUri = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgContent)}`
    return (
      <ExpandableMedia content={svgContent} type="svg" alt={alt}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={dataUri}
          alt={alt || ''}
          className="max-w-full h-auto my-5 mx-auto block"
        />
      </ExpandableMedia>
    )
  }

  // Resolved image URL (binary or data URI)
  if (imageUrl) {
    return (
      <ExpandableMedia content={imageUrl} type="img" alt={alt}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={imageUrl}
          alt={alt || ''}
          className="max-w-full h-auto rounded-lg my-5 border border-border/30"
        />
      </ExpandableMedia>
    )
  }

  // Still loading — use span to avoid div-inside-p hydration error
  if (loading) {
    return (
      <span className="block my-5 flex justify-center">
        <span className="block w-48 h-32 rounded-lg bg-muted/60 animate-pulse" />
      </span>
    )
  }

  // Fallback: render as a normal image tag (external URLs, unresolved paths)
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt={alt || ''}
      className="max-w-full h-auto rounded-lg my-5 border border-border/30"
    />
  )
}

interface WikiContentProps {
  content: string
  title: string
  path?: string
  documentId?: string | null
  onNavigate: (path: string) => void
  onSourceClick?: (filename: string, page?: number) => void
  onGraphClick?: () => void
  documents?: DocumentListItem[]
  courseMode?: boolean
  courseView?: 'overview' | 'lesson' | null
  isComplete?: boolean
  prevLesson?: LessonLink | null
  forwardLabel?: string | null
  onForward?: () => void
  resumeLesson?: LessonLink | null
  onLessonNavigate?: (path: string) => void
  lessonsTotal?: number
  lessonsComplete?: number
}

interface LessonLink {
  title: string
  path: string
}

export function WikiContent({ content, title, path, documentId = null, onNavigate, onSourceClick, onGraphClick, documents, courseMode = false, courseView = null, isComplete = false, prevLesson = null, forwardLabel = null, onForward, resumeLesson = null, onLessonNavigate, lessonsTotal = 0, lessonsComplete = 0 }: WikiContentProps) {
  const scrollRef = React.useRef<HTMLDivElement | null>(null)
  const markdownRef = React.useRef<HTMLDivElement | null>(null)
  const body = React.useMemo(() => stripFrontmatter(content), [content])
  const description = React.useMemo(() => parseFrontmatterField(content, 'description'), [content])
  const { heading, rest } = React.useMemo(() => extractLeadingH1(body), [body])
  const processedContent = React.useMemo(() => normalizeMathDelimiters(rest), [rest])
  const pageTitle = toDisplayTitle(heading ?? title)
  const eyebrow = React.useMemo(() => pathEyebrow(path), [path])
  const tocItems = React.useMemo(() => extractTocFromMarkdown(processedContent), [processedContent])
  const footnoteSources = React.useMemo(() => parseFootnoteSources(processedContent), [processedContent])
  const [copied, setCopied] = React.useState(false)

  const handleCopy = React.useCallback(() => {
    navigator.clipboard.writeText(content).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }, [content])

  const components: Components = React.useMemo(
    () => ({
      h1({ children }) {
        const text = childrenToText(children)
        const id = slugify(text)
        return (
          <h1 id={id} className="text-2xl font-bold tracking-tight mt-8 mb-3 first:mt-0 scroll-mt-20">
            {children}
          </h1>
        )
      },
      h2({ children }) {
        const text = childrenToText(children)
        const id = slugify(text)
        return (
          <h2 id={id} className="text-xl font-semibold tracking-tight mt-6 mb-2 pt-2 border-t border-border/50 first:border-0 first:pt-0 scroll-mt-20">
            {children}
          </h2>
        )
      },
      h3({ children }) {
        const text = childrenToText(children)
        const id = slugify(text)
        return (
          <h3 id={id} className="text-lg font-medium tracking-tight mt-6 mb-1.5 scroll-mt-20">
            {children}
          </h3>
        )
      },
      h4({ children }) {
        const text = childrenToText(children)
        const id = slugify(text)
        return (
          <h4 id={id} className="text-base font-medium mt-5 mb-1 scroll-mt-20">
            {children}
          </h4>
        )
      },
      p({ children }) {
        return <p className="my-2 leading-[1.65] text-foreground/90">{children}</p>
      },
      pre({ children, ...props }) {
        const child = React.Children.toArray(children)[0]
        if (
          React.isValidElement(child) &&
          typeof child.props === 'object' &&
          child.props !== null &&
          'className' in child.props &&
          typeof child.props.className === 'string' &&
          child.props.className.includes('language-mermaid')
        ) {
          const text =
            'children' in child.props
              ? String(child.props.children).replace(/\n$/, '')
              : ''
          return <MermaidBlock chart={text} />
        }
        return (
          <pre
            className="text-[13px] leading-relaxed my-3 bg-muted/60 border border-border rounded-lg p-4 overflow-x-auto"
            {...props}
          >
            {children}
          </pre>
        )
      },
      code({ className, children, ...props }) {
        const isBlock = className?.startsWith('language-')
        if (isBlock) {
          return (
            <code className={className} {...props}>
              {children}
            </code>
          )
        }
        return (
          <code
            className="text-[13px] bg-muted/70 px-1.5 py-0.5 rounded font-mono text-foreground/80"
            {...props}
          >
            {children}
          </code>
        )
      },
      a({ href, children }) {
        // Footnote back-references (↩ arrows) — hide entirely
        if (href?.includes('fnref')) {
          return null
        }
        const text = childrenToText(children)
        if (text.includes('↩') || text.includes('↵')) {
          return null
        }
        if (href?.startsWith('#fn-') || href?.startsWith('#user-content-fn-')) {
          return (
            <a
              href={href}
              className="text-muted-foreground/50 hover:text-muted-foreground no-underline ml-1"
            >
              {children}
            </a>
          )
        }

        // Internal wiki links
        if (
          href &&
          !href.startsWith('http') &&
          !href.startsWith('#') &&
          !href.startsWith('mailto:')
        ) {
          return (
            <button
              onClick={() => onNavigate(href)}
              className="text-accent-blue underline underline-offset-2 decoration-accent-blue/30 hover:decoration-accent-blue transition-colors cursor-pointer font-medium"
            >
              {children}
            </button>
          )
        }

        // Anchor links (headings)
        if (href?.startsWith('#')) {
          return (
            <a
              href={href}
              onClick={(e) => {
                e.preventDefault()
                const id = href.slice(1)
                const el = document.getElementById(id)
                if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
              }}
              className="text-accent-blue underline underline-offset-2 decoration-accent-blue/30 hover:decoration-accent-blue transition-colors"
            >
              {children}
            </a>
          )
        }

        return (
          <a
            href={href ?? undefined}
            target="_blank"
            rel="noopener noreferrer"
            className="text-accent-blue underline underline-offset-2 decoration-accent-blue/30 hover:decoration-accent-blue transition-colors"
          >
            {children}
          </a>
        )
      },
      sup({ children, ...props }) {
        // Detect footnote references like [^1] which render as <sup> with an <a> inside
        const child = React.Children.toArray(children)[0]
        const childProps = React.isValidElement(child) ? (child.props as Record<string, unknown>) : null
        const childHref = childProps && typeof childProps.href === 'string' ? childProps.href : null
        if (childHref && childHref.includes('fn')) {
          const text = childrenToText(children)
          const num = text.replace(/[^\d]/g, '')
          const source = footnoteSources.get(num)
          if (source) {
            return (
              <sup {...props}>
                <CitationBadge
                  num={num}
                  source={source}
                  onSourceClick={(filename, page) => {
                    if (onSourceClick) onSourceClick(filename, page)
                  }}
                />
              </sup>
            )
          }
        }
        return <sup {...props}>{children}</sup>
      },
      table({ children, ...props }) {
        return (
          <div className="overflow-x-auto my-6 rounded-lg border border-border">
            <table className="w-full border-collapse text-sm" {...props}>
              {children}
            </table>
          </div>
        )
      },
      thead({ children, ...props }) {
        return (
          <thead className="bg-muted/50" {...props}>
            {children}
          </thead>
        )
      },
      th({ children, ...props }) {
        return (
          <th
            className="text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground px-3 py-2 border-b border-border"
            {...props}
          >
            {children}
          </th>
        )
      },
      td({ children, ...props }) {
        return (
          <td className="text-sm px-3 py-2 border-b border-border/50" {...props}>
            {children}
          </td>
        )
      },
      blockquote({ children, ...props }) {
        return (
          <blockquote
            className="border-l-[3px] border-accent-blue/40 pl-4 my-3 py-1 text-muted-foreground bg-accent-blue/[0.03] rounded-r-md"
            {...props}
          >
            {children}
          </blockquote>
        )
      },
      ul({ children, ...props }) {
        return (
          <ul className="my-2.5 space-y-0.5 list-disc pl-5 marker:text-muted-foreground/40" {...props}>
            {children}
          </ul>
        )
      },
      ol({ children, ...props }) {
        return (
          <ol className="my-2.5 space-y-0.5 list-decimal pl-5 marker:text-muted-foreground/40" {...props}>
            {children}
          </ol>
        )
      },
      li({ children, ...props }) {
        // Style footnote list items (inside <section data-footnotes>)
        const id = (props as Record<string, unknown>).id
        if (typeof id === 'string' && (id.startsWith('fn-') || id.startsWith('user-content-fn-'))) {
          const text = childrenToText(children).replace(/↩.*$/, '').trim()
          return (
            <li
              id={id}
              className="my-2 text-sm pl-1 scroll-mt-20"
            >
              <button
                onClick={() => onSourceClick?.(text)}
                className="text-muted-foreground hover:text-foreground hover:underline transition-colors cursor-pointer text-left"
              >
                {text}
              </button>
            </li>
          )
        }
        return (
          <li className="my-0.5 leading-[1.65]" {...props}>
            {children}
          </li>
        )
      },
      hr() {
        return <hr className="my-6 border-border/60" />
      },
      img({ src, alt }) {
        return (
          <WikiImage
            src={typeof src === 'string' ? src : undefined}
            alt={typeof alt === 'string' ? alt : undefined}
            documents={documents}
          />
        )
      },
      section({ children, ...props }) {
        // Replace the auto-generated footnotes section with our own clean version
        const dp = props as Record<string, unknown>
        if (dp['data-footnotes'] !== undefined || dp.dataFootnotes !== undefined || dp.className === 'footnotes') {
          // Render our own clean footnotes from parsed sources
          const entries = Array.from(footnoteSources.entries())
          if (entries.length === 0) return null
          return (
            <section className="mt-12 pt-6 border-t border-border">
              <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground/50 mb-3">
                Sources
              </p>
              <ol className="list-decimal pl-5 space-y-1.5">
                {entries.map(([num, source]) => {
                  const filename = source.replace(/,\s*p\.?\s*.+$/, '').trim()
                  return (
                    <li key={num} className="text-sm pl-1">
                      <button
                        onClick={() => onSourceClick?.(filename)}
                        className="text-muted-foreground hover:text-foreground hover:underline transition-colors cursor-pointer text-left"
                      >
                        {source}
                      </button>
                    </li>
                  )
                })}
              </ol>
            </section>
          )
        }
        return <section {...props}>{children}</section>
      },
    }),
    [onNavigate, onSourceClick, footnoteSources, documents],
  )

  const hasToc = tocItems.length > 0

  return (
    <div className="relative h-full overflow-y-auto" id="wiki-scroll-container" ref={scrollRef}>
      <div className={cn(
        'mx-auto px-6 py-10',
        hasToc ? 'max-w-5xl' : 'max-w-3xl',
      )}>
        <div className={cn(
          hasToc && 'flex gap-8',
        )}>
          {/* Main content */}
          <div className={cn(
            'min-w-0',
            hasToc ? 'flex-1 max-w-[720px]' : 'w-full',
          )}>
            <div className="mb-6">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  {eyebrow && (
                    <div className="text-[11px] font-medium uppercase tracking-[0.06em] text-muted-foreground/60 mb-2">
                      {eyebrow}
                    </div>
                  )}
                  {pageTitle && <h1 className="text-3xl font-bold tracking-tight">{pageTitle}</h1>}
                </div>
                <div className="flex items-center gap-1 shrink-0 mt-1.5">
                  <button
                    onClick={handleCopy}
                    className="p-1.5 rounded-md text-muted-foreground/40 hover:text-muted-foreground hover:bg-accent transition-colors cursor-pointer"
                    title="Copy markdown"
                  >
                    {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
                  </button>
                  {onGraphClick && (
                    <button
                      onClick={onGraphClick}
                      className="p-1.5 rounded-md text-muted-foreground/40 hover:text-muted-foreground hover:bg-accent transition-colors cursor-pointer"
                      title="Show in graph"
                    >
                      <Network className="size-3.5" />
                    </button>
                  )}
                </div>
              </div>
              {description && (
                <p className="text-[15px] text-muted-foreground mt-2.5 leading-relaxed">{description}</p>
              )}
            </div>
            <div className="wiki-content text-[15px] leading-relaxed" ref={markdownRef}>
              <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkMath, remarkFixOverescapedMath]}
                rehypePlugins={[rehypeKatex]}
                components={components}
              >
                {processedContent}
              </ReactMarkdown>
            </div>
            {courseMode && courseView === 'overview' && resumeLesson && (
              <div className="mt-12 pt-6 border-t border-border flex items-center justify-between gap-4">
                <div className="text-[13px] text-muted-foreground">
                  {lessonsComplete > 0
                    ? `${lessonsComplete} of ${lessonsTotal} lessons complete`
                    : `${lessonsTotal} ${lessonsTotal === 1 ? 'lesson' : 'lessons'}`}
                </div>
                <button
                  onClick={() => onLessonNavigate?.(resumeLesson.path)}
                  className="inline-flex items-center gap-2 rounded-md bg-foreground text-background font-semibold text-[13px] px-4 py-2 hover:opacity-90 transition-opacity cursor-pointer"
                >
                  {lessonsTotal > 0 && lessonsComplete >= lessonsTotal ? 'Review course' : lessonsComplete > 0 ? 'Continue' : 'Start course'}
                  <ArrowRight className="size-4" />
                </button>
              </div>
            )}
            {courseMode && courseView === 'lesson' && (
              <div className="mt-12 pt-5 border-t border-border flex items-center justify-between gap-4">
                {prevLesson ? (
                  <button
                    onClick={() => onLessonNavigate?.(prevLesson.path)}
                    className="flex items-center gap-1.5 min-w-0 text-[13px] text-muted-foreground/60 hover:text-foreground transition-colors cursor-pointer"
                    title={`Previous: ${prevLesson.title}`}
                  >
                    <ChevronLeft className="size-4 shrink-0" />
                    <span className="truncate max-w-[160px]">{prevLesson.title}</span>
                  </button>
                ) : (
                  <span className="w-6" />
                )}
                {isComplete ? (
                  <span className="inline-flex items-center gap-1.5 text-[13px] font-medium text-emerald-600 dark:text-emerald-400">
                    <Check className="size-3.5" />Completed
                  </span>
                ) : (
                  <span />
                )}
                {forwardLabel ? (
                  <button
                    onClick={onForward}
                    className="flex items-center justify-end gap-1.5 min-w-0 text-[13px] font-medium text-foreground/80 hover:text-foreground transition-colors cursor-pointer"
                    title={`Next: ${forwardLabel}`}
                  >
                    <span className="truncate max-w-[160px]">{forwardLabel}</span>
                    <ChevronRight className="size-4 shrink-0" />
                  </button>
                ) : (
                  <span className="w-6" />
                )}
              </div>
            )}
          </div>

          {/* Right sidebar — "On this page" ToC */}
          {hasToc && (
            <aside className="hidden lg:block w-48 shrink-0">
              <div className="sticky top-10">
                <TableOfContents items={tocItems} />
              </div>
            </aside>
          )}
        </div>
      </div>
      {documentId && (
        <WikiHighlighter
          scrollRef={scrollRef}
          contentRef={markdownRef}
          documentId={documentId}
          contentKey={processedContent}
        />
      )}
    </div>
  )
}

function childrenToText(children: React.ReactNode): string {
  if (typeof children === 'string') return children
  if (typeof children === 'number') return String(children)
  if (Array.isArray(children)) return children.map(childrenToText).join('')
  if (React.isValidElement(children) && children.props) {
    const props = children.props as Record<string, unknown>
    if (props.children) return childrenToText(props.children as React.ReactNode)
  }
  return ''
}
