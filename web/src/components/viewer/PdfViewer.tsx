'use client'

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { flushSync } from 'react-dom'
import { Document, Page } from 'react-pdf'
import { ChevronUp, ChevronDown, Search, X, Download, ZoomIn, ZoomOut, MessageSquare } from 'lucide-react'
import { cn } from '@/lib/utils'
import { ensurePdfWorker } from '@/lib/pdfjs'
import { useDocumentHighlights } from '@/hooks/useWikiHighlights'
import { createHighlightId } from '@/lib/highlights/ids'
import type { Highlight, PdfAnchor } from '@/lib/highlights/types'
import { computePdfAnchor, pdfRectsToViewport } from '@/lib/highlights/pdfAnchor'

import 'react-pdf/dist/Page/TextLayer.css'
import 'react-pdf/dist/Page/AnnotationLayer.css'

ensurePdfWorker()

type Props = {
  fileUrl: string
  documentId?: string
  title?: string
  className?: string
  initialPage?: number
  hideToolbar?: boolean
}

const VIRTUALIZE_BUFFER = 2

export default function PdfViewer({ fileUrl, documentId, title, className, initialPage, hideToolbar }: Props) {
  const [numPages, setNumPages] = useState(0)
  const [currentPage, setCurrentPage] = useState(1)
  const containerRef = useRef<HTMLDivElement>(null)
  const pageRefs = useRef<Map<number, HTMLDivElement>>(new Map())

  const [visiblePages, setVisiblePages] = useState<Set<number>>(() => new Set([1]))

  const [pageInputActive, setPageInputActive] = useState(false)
  const [pageInputValue, setPageInputValue] = useState('')
  const pageInputRef = useRef<HTMLInputElement>(null)

  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [matchCount, setMatchCount] = useState(0)
  const [currentMatchIndex, setCurrentMatchIndex] = useState(-1)
  const searchMarksRef = useRef<HTMLElement[]>([])
  const modifiedSpansRef = useRef<Map<HTMLSpanElement, string>>(new Map())
  const searchInputRef = useRef<HTMLInputElement>(null)

  const [isIndexing, setIsIndexing] = useState(false)
  const searchPagesRef = useRef<Set<number>>(new Set())
  const searchRafRef = useRef<number>(0)
  const searchTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined)
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined)

  const [scale, setScale] = useState(1)
  const scaleRef = useRef(1)
  const visualScaleRef = useRef(1)
  const gestureTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined)
  const pagesWrapperRef = useRef<HTMLDivElement>(null)
  const [displayScale, setDisplayScale] = useState(1)

  const commitZoom = useCallback((next: number) => {
    const clamped = Math.min(Math.max(next, 0.25), 3)
    const container = containerRef.current
    const oldCommitted = scaleRef.current
    scaleRef.current = clamped
    visualScaleRef.current = clamped
    const scrollTop = container?.scrollTop ?? 0
    const ratio = clamped / oldCommitted
    flushSync(() => { setScale(clamped); setDisplayScale(clamped) })
    if (container) container.scrollTop = scrollTop * ratio
    if (pagesWrapperRef.current) pagesWrapperRef.current.style.transform = ''
  }, [])

  const zoomIn = useCallback(() => commitZoom(scaleRef.current + 0.25), [commitZoom])
  const zoomOut = useCallback(() => commitZoom(scaleRef.current - 0.25), [commitZoom])
  const zoomReset = useCallback(() => commitZoom(1), [commitZoom])

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const pdfDocRef = useRef<any>(null)
  const [pageTexts, setPageTexts] = useState<Map<number, string>>(new Map())

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  function onDocLoad(pdf: any) {
    setNumPages(pdf.numPages)
    pdfDocRef.current = pdf
  }

  // Extract text from all pages at load time for full-document search
  useEffect(() => {
    const doc = pdfDocRef.current
    if (!doc || !numPages) return
    let cancelled = false
    setIsIndexing(true)

    const extractAll = async () => {
      const texts = new Map<number, string>()
      for (let p = 1; p <= numPages; p++) {
        if (cancelled) return
        const page = await doc.getPage(p)
        const content = await page.getTextContent()
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const text = content.items.map((item: any) => item.str).join(' ')
        texts.set(p, text)
      }
      if (!cancelled) {
        setPageTexts(texts)
        setIsIndexing(false)
      }
    }
    extractAll()
    return () => { cancelled = true }
  }, [numPages])

  const scrollToPage = useCallback((page: number) => {
    const el = pageRefs.current.get(page)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      setCurrentPage(page)
    }
  }, [])

  // Scroll to initial page (e.g., from citation click) after pages render
  const initialPageScrolled = useRef(false)
  useEffect(() => {
    if (!initialPage || initialPage <= 1 || !numPages || initialPageScrolled.current) return
    const target = Math.min(initialPage, numPages)
    setVisiblePages((prev) => {
      const next = new Set(prev)
      for (let p = Math.max(1, target - VIRTUALIZE_BUFFER); p <= Math.min(numPages, target + VIRTUALIZE_BUFFER); p++) {
        next.add(p)
      }
      return next
    })
    const timer = setTimeout(() => {
      scrollToPage(target)
      initialPageScrolled.current = true
    }, 200)
    return () => clearTimeout(timer)
  }, [initialPage, numPages, scrollToPage])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const onScroll = () => {
      const containerTop = container.getBoundingClientRect().top
      let closest = 1
      let minDist = Infinity

      pageRefs.current.forEach((el, page) => {
        const dist = Math.abs(el.getBoundingClientRect().top - containerTop)
        if (dist < minDist) {
          minDist = dist
          closest = page
        }
      })

      setCurrentPage(closest)
    }

    container.addEventListener('scroll', onScroll, { passive: true })
    return () => container.removeEventListener('scroll', onScroll)
  }, [numPages])

  const [containerWidth, setContainerWidth] = useState(0)
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setContainerWidth(el.clientWidth))
    ro.observe(el)
    setContainerWidth(el.clientWidth)
    return () => ro.disconnect()
  }, [])

  const baseWidth = Math.min(containerWidth - 32, 900)
  const pageWidth = baseWidth * scale

  const pageAspectRef = useRef<Map<number, number>>(new Map())
  const estimatedPageHeight = pageWidth > 0 ? pageWidth * 1.414 : 800

  // react-pdf renders pages from `width`, not from our UI zoom scalar. Any
  // PDF.js viewport used for anchor conversion must mirror the rendered width
  // or saved PDF-space rects drift after resize / fit-width changes.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const renderedViewport = useCallback((page: any) => {
    const base = page.getViewport({ scale: 1 })
    const renderedWidth = pageWidth > 0 ? pageWidth : base.width
    return page.getViewport({ scale: renderedWidth / base.width })
  }, [pageWidth])

  useEffect(() => {
    const container = containerRef.current
    if (!container || !numPages) return

    const observer = new IntersectionObserver(
      (entries) => {
        const toAdd: number[] = []
        for (const entry of entries) {
          if (!entry.isIntersecting) continue
          const pageNum = Number((entry.target as HTMLElement).dataset.page)
          if (!pageNum) continue
          for (let p = Math.max(1, pageNum - VIRTUALIZE_BUFFER); p <= Math.min(numPages, pageNum + VIRTUALIZE_BUFFER); p++) {
            toAdd.push(p)
          }
        }
        if (toAdd.length === 0) return
        setVisiblePages((prev) => {
          let changed = false
          for (const p of toAdd) {
            if (!prev.has(p)) { changed = true; break }
          }
          if (!changed) return prev
          const next = new Set(prev)
          for (const p of toAdd) next.add(p)
          return next
        })
      },
      { root: container, rootMargin: '100% 0px' }
    )

    pageRefs.current.forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [numPages])

  // Page proxies in state so highlight overlays re-render the moment a
  // proxy becomes available (no global render-version counter needed).
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [pageProxies, setPageProxies] = useState<Map<number, any>>(() => new Map())

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const onPageLoadSuccess = useCallback((pageNumber: number, page: any) => {
    const vp = page.getViewport({ scale: 1 })
    pageAspectRef.current.set(pageNumber, vp.height / vp.width)
    setPageProxies((prev) => {
      if (prev.get(pageNumber) === page) return prev
      const next = new Map(prev)
      next.set(pageNumber, page)
      return next
    })
  }, [])

  // ─── Highlights ────────────────────────────────────────────────────
  const {
    highlights,
    saveHighlight: persistHighlight,
    updateComment,
    removeHighlight,
  } = useDocumentHighlights(documentId ?? null)
  type PopoverState =
    | {
        mode: 'create'
        pageNumber: number
        anchor: Omit<PdfAnchor, 'page'>
        position: { left: number; top: number }
      }
    | {
        mode: 'edit'
        pageNumber: number
        highlight: Highlight
        position: { left: number; top: number }
      }
  const [popover, setPopover] = useState<PopoverState | null>(null)
  const [commentDraft, setCommentDraft] = useState('')
  const [commentExpanded, setCommentExpanded] = useState(false)
  const [savingHighlight, setSavingHighlight] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false
    return window.localStorage.getItem('llmwiki.pdfHighlightsDrawer') === '1'
  })

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem('llmwiki.pdfHighlightsDrawer', drawerOpen ? '1' : '0')
  }, [drawerOpen])

  useEffect(() => {
    if (!notice) return
    const id = window.setTimeout(() => setNotice(null), 2400)
    return () => window.clearTimeout(id)
  }, [notice])

  const pdfHighlightsByPage = useMemo(() => {
    const m = new Map<number, Highlight[]>()
    for (const h of highlights) {
      if (h.type !== 'pdf' || !h.pdfAnchor) continue
      const list = m.get(h.pdfAnchor.page) ?? []
      list.push(h)
      m.set(h.pdfAnchor.page, list)
    }
    return m
  }, [highlights])

  const pdfHighlightsSorted = useMemo(() => {
    return highlights
      .filter((h): h is Highlight & { pdfAnchor: PdfAnchor } => h.type === 'pdf' && !!h.pdfAnchor)
      .sort((a, b) => a.pdfAnchor.page - b.pdfAnchor.page || a.createdAt.localeCompare(b.createdAt))
  }, [highlights])

  const pdfHighlightCount = pdfHighlightsSorted.length

  const handlePageMouseUp = useCallback(
    (pageNumber: number, pageEl: HTMLDivElement) => {
      if (!documentId) return
      const sel = window.getSelection()
      if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return
      const range = sel.getRangeAt(0)

      // Cross-page guard: both selection endpoints must live inside this
      // page wrapper. `commonAncestorContainer` would walk to a shared
      // ancestor *above* both pages when selecting across pages, so anchor
      // + focus node containment is the reliable check.
      const anchorNode = sel.anchorNode
      const focusNode = sel.focusNode
      const inThisPage = (node: Node | null) => !!node && pageEl.contains(node)
      if (!inThisPage(anchorNode) || !inThisPage(focusNode)) {
        // If either endpoint is in a different page wrapper, surface the
        // toast. Otherwise the selection isn't ours — silent return.
        const otherPageWrapper =
          [anchorNode, focusNode].find(
            (n) => n && !inThisPage(n) && (n as HTMLElement).closest?.('[data-page]') !== null,
          ) ?? null
        if (otherPageWrapper) setNotice('Highlight must stay on one page')
        return
      }

      const proxy = pageProxies.get(pageNumber)
      if (!proxy) return
      const viewport = renderedViewport(proxy)
      const pageText = pageTexts.get(pageNumber) ?? ''
      const computed = computePdfAnchor({ range, viewport, pageContainer: pageEl, pageText })
      if (!computed) return

      // Position the popover under the last visual line of the selection.
      // Use pdfRectsToViewport so the rect is already y-axis-normalized,
      // not the raw convertToViewportRectangle tuple (which can land at the
      // top of the line after PDF's bottom-left origin flip).
      const lastRect = computed.rects[computed.rects.length - 1]
      const [vpRect] = pdfRectsToViewport([lastRect], viewport)
      setPopover({
        mode: 'create',
        pageNumber,
        anchor: computed,
        position: {
          left: Math.min(Math.max(0, vpRect.left), Math.max(0, viewport.width - 240)),
          top: Math.max(0, vpRect.top + vpRect.height + 6),
        },
      })
      setCommentDraft('')
      setCommentExpanded(false)
    },
    [documentId, pageProxies, pageTexts, renderedViewport],
  )

  const handleHighlightClick = useCallback(
    (highlight: Highlight) => {
      if (!highlight.pdfAnchor) return
      const proxy = pageProxies.get(highlight.pdfAnchor.page)
      if (!proxy) return
      const viewport = renderedViewport(proxy)
      const [vpRect] = pdfRectsToViewport([highlight.pdfAnchor.rects[0]], viewport)
      setPopover({
        mode: 'edit',
        pageNumber: highlight.pdfAnchor.page,
        highlight,
        position: {
          left: Math.min(Math.max(0, vpRect.left), Math.max(0, viewport.width - 240)),
          top: Math.max(0, vpRect.top + vpRect.height + 6),
        },
      })
      setCommentDraft(highlight.comment ?? '')
      // Compact pill on overlay click ([Note] [Delete]); user expands to
      // textarea only when they actually want to edit the note.
      setCommentExpanded(false)
    },
    [pageProxies, renderedViewport],
  )

  // "Note" pressed in CREATE mode: save the highlight immediately so the
  // yellow rect renders, then switch the popover to edit-expanded for that
  // just-saved highlight so the user can type their note on top of it.
  const startNoteFromCreate = useCallback(async () => {
    if (!documentId || !popover || popover.mode !== 'create' || savingHighlight) return
    setSavingHighlight(true)
    try {
      const highlight: Highlight = {
        id: createHighlightId(),
        type: 'pdf',
        anchor: null,
        textAnchor: null,
        pdfAnchor: {
          page: popover.pageNumber,
          textStart: popover.anchor.textStart,
          textEnd: popover.anchor.textEnd,
          textContent: popover.anchor.textContent,
          prefix: popover.anchor.prefix,
          suffix: popover.anchor.suffix,
          rects: popover.anchor.rects,
        },
        comment: null,
        color: 'yellow',
        createdAt: new Date().toISOString(),
      }
      await persistHighlight(highlight)
      window.getSelection()?.removeAllRanges()
      setPopover({
        mode: 'edit',
        pageNumber: popover.pageNumber,
        highlight,
        position: popover.position,
      })
      setCommentDraft('')
      setCommentExpanded(true)
    } catch {
      // Stay in create mode so the user can retry.
    } finally {
      setSavingHighlight(false)
    }
  }, [documentId, persistHighlight, popover, savingHighlight])

  const saveHighlight = useCallback(async () => {
    if (!documentId || !popover || savingHighlight) return
    setSavingHighlight(true)
    try {
      const highlight: Highlight =
        popover.mode === 'create'
          ? {
              id: createHighlightId(),
              type: 'pdf',
              anchor: null,
              textAnchor: null,
              pdfAnchor: {
                page: popover.pageNumber,
                textStart: popover.anchor.textStart,
                textEnd: popover.anchor.textEnd,
                textContent: popover.anchor.textContent,
                prefix: popover.anchor.prefix,
                suffix: popover.anchor.suffix,
                rects: popover.anchor.rects,
              },
              comment: commentDraft.trim() || null,
              color: 'yellow',
              createdAt: new Date().toISOString(),
            }
          : { ...popover.highlight, comment: commentDraft.trim() || null }

      if (popover.mode === 'create') {
        await persistHighlight(highlight)
      } else {
        await updateComment(highlight.id, highlight.comment)
      }
      setPopover(null)
      setCommentDraft('')
      setCommentExpanded(false)
      window.getSelection()?.removeAllRanges()
    } catch {
      // Popover stays open so user can retry; no toast infra to surface details.
    } finally {
      setSavingHighlight(false)
    }
  }, [commentDraft, documentId, persistHighlight, popover, savingHighlight, updateComment])

  const deleteHighlight = useCallback(async () => {
    if (!documentId || !popover || popover.mode !== 'edit' || savingHighlight) return
    setSavingHighlight(true)
    try {
      await removeHighlight(popover.highlight.id)
      setPopover(null)
      setCommentDraft('')
      setCommentExpanded(false)
    } catch {
      // Same as save: leave popover open so user can retry.
    } finally {
      setSavingHighlight(false)
    }
  }, [documentId, popover, removeHighlight, savingHighlight])

  const cancelPopover = useCallback(() => {
    setPopover(null)
    setCommentDraft('')
    setCommentExpanded(false)
  }, [])

  // Dismiss the popover on click-outside or Escape. Clicks on existing
  // highlight overlays don't dismiss — the click handler there re-opens
  // with a fresh edit popover anyway.
  useEffect(() => {
    if (!popover) return
    const onDocMouseDown = (e: MouseEvent) => {
      const target = e.target as HTMLElement | null
      if (!target) return
      if (target.closest('.pdf-highlight-popover') || target.closest('.pdf-hl-rect')) return
      cancelPopover()
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') cancelPopover()
    }
    document.addEventListener('mousedown', onDocMouseDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onDocMouseDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [popover, cancelPopover])

  const jumpToHighlight = useCallback(
    (h: Highlight) => {
      if (!h.pdfAnchor) return
      const page = h.pdfAnchor.page
      setVisiblePages((prev) => {
        if (prev.has(page)) return prev
        const next = new Set(prev)
        for (let p = Math.max(1, page - VIRTUALIZE_BUFFER); p <= Math.min(numPages, page + VIRTUALIZE_BUFFER); p++) {
          next.add(p)
        }
        return next
      })
      window.setTimeout(() => {
        scrollToPage(page)
        window.setTimeout(() => handleHighlightClick(h), 250)
      }, 80)
    },
    [handleHighlightClick, numPages, scrollToPage],
  )

  const activatePageInput = useCallback(() => {
    setPageInputValue(String(currentPage))
    setPageInputActive(true)
    setTimeout(() => pageInputRef.current?.select(), 0)
  }, [currentPage])

  const commitPageInput = useCallback(() => {
    setPageInputActive(false)
    const p = parseInt(pageInputValue, 10)
    if (!isNaN(p) && p >= 1 && p <= numPages) scrollToPage(p)
  }, [pageInputValue, numPages, scrollToPage])

  const clearSearchHighlights = useCallback(() => {
    for (const [span, original] of modifiedSpansRef.current) {
      span.textContent = original
    }
    modifiedSpansRef.current.clear()
    searchMarksRef.current = []
    setMatchCount(0)
    setCurrentMatchIndex(-1)
  }, [])

  const applyDomHighlights = useCallback((query: string): HTMLElement[] => {
    const marks: HTMLElement[] = []
    const lowerQuery = query.toLowerCase()
    const escapeHtml = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

    for (let p = 1; p <= numPages; p++) {
      const pageEl = pageRefs.current.get(p)
      if (!pageEl) continue
      const textLayer =
        pageEl.querySelector('.react-pdf__Page__textContent') ??
        pageEl.querySelector('.textLayer')
      if (!textLayer) continue

      const spans = textLayer.querySelectorAll('span')
      for (const span of spans) {
        const text = span.textContent ?? ''
        const lowerText = text.toLowerCase()
        if (!lowerText.includes(lowerQuery)) continue

        modifiedSpansRef.current.set(span as HTMLSpanElement, text)

        let html = ''
        let lastIdx = 0
        let idx: number
        while ((idx = lowerText.indexOf(lowerQuery, lastIdx)) !== -1) {
          html += escapeHtml(text.slice(lastIdx, idx))
          html += `<mark class="search-mark">${escapeHtml(text.slice(idx, idx + query.length))}</mark>`
          lastIdx = idx + query.length
        }
        html += escapeHtml(text.slice(lastIdx))
        span.innerHTML = html

        const spanMarks = span.querySelectorAll('mark.search-mark')
        for (const m of spanMarks) marks.push(m as HTMLElement)
      }
    }
    return marks
  }, [numPages])

  const cancelPendingSearch = useCallback(() => {
    cancelAnimationFrame(searchRafRef.current)
    clearTimeout(searchTimerRef.current)
    clearTimeout(debounceTimerRef.current)
  }, [])

  const performSearch = useCallback((query: string) => {
    cancelPendingSearch()
    clearSearchHighlights()
    if (!query.trim()) return

    const lowerQuery = query.toLowerCase()

    // Step 1: Find matching pages via in-memory text index (searches ALL pages)
    const matchingPages: number[] = []
    let indexOccurrences = 0
    if (pageTexts.size > 0) {
      for (const [page, text] of pageTexts) {
        const lower = text.toLowerCase()
        let idx = 0
        let count = 0
        while ((idx = lower.indexOf(lowerQuery, idx)) !== -1) {
          count++
          idx += lowerQuery.length
        }
        if (count > 0) {
          matchingPages.push(page)
          indexOccurrences += count
        }
      }
    }

    // Step 2: Ensure matching pages are rendered so DOM highlighting works
    if (matchingPages.length > 0) {
      const newSearchPages = new Set<number>()
      setVisiblePages((prev) => {
        const next = new Set(prev)
        for (const p of matchingPages) {
          if (!prev.has(p)) newSearchPages.add(p)
          next.add(p)
        }
        return next
      })
      searchPagesRef.current = newSearchPages
    }

    // Step 3: Apply DOM highlighting after a frame (gives React time to render new pages)
    searchRafRef.current = requestAnimationFrame(() => {
      searchTimerRef.current = setTimeout(() => {
        const marks = applyDomHighlights(query)
        searchMarksRef.current = marks

        // Use real occurrence count from text index when DOM marks aren't all ready yet
        setMatchCount(marks.length || indexOccurrences)

        if (marks.length > 0) {
          setCurrentMatchIndex(0)
          marks[0].classList.add('search-mark-active')
          marks[0].scrollIntoView({ behavior: 'smooth', block: 'center' })
        }
      }, 100)
    })
  }, [pageTexts, clearSearchHighlights, applyDomHighlights, cancelPendingSearch])

  const navigateMatch = useCallback((delta: number) => {
    const marks = searchMarksRef.current
    if (marks.length === 0) return

    if (currentMatchIndex >= 0 && currentMatchIndex < marks.length) {
      marks[currentMatchIndex].classList.remove('search-mark-active')
    }

    const next = (currentMatchIndex + delta + marks.length) % marks.length
    setCurrentMatchIndex(next)
    marks[next].classList.add('search-mark-active')
    marks[next].scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [currentMatchIndex])

  // Clean up pending search timers on unmount
  useEffect(() => {
    return () => {
      cancelAnimationFrame(searchRafRef.current)
      clearTimeout(searchTimerRef.current)
      clearTimeout(debounceTimerRef.current)
    }
  }, [])

  const openSearch = useCallback(() => {
    setSearchOpen(true)
    setTimeout(() => searchInputRef.current?.focus(), 0)
  }, [])

  const closeSearch = useCallback(() => {
    cancelPendingSearch()
    setSearchOpen(false)
    setSearchQuery('')
    clearSearchHighlights()
    // Remove pages that were only added for search results
    if (searchPagesRef.current.size > 0) {
      const toRemove = searchPagesRef.current
      setVisiblePages((prev) => {
        const next = new Set(prev)
        for (const p of toRemove) next.delete(p)
        return next
      })
      searchPagesRef.current = new Set()
    }
  }, [clearSearchHighlights, cancelPendingSearch])

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'f') {
        e.preventDefault()
        e.stopPropagation()
        if (searchOpen) searchInputRef.current?.select()
        else openSearch()
      }
      if (e.key === 'Escape' && searchOpen) closeSearch()
    }
    document.addEventListener('keydown', onKeyDown, true)
    return () => document.removeEventListener('keydown', onKeyDown, true)
  }, [searchOpen, openSearch, closeSearch])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const onWheel = (e: WheelEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return
      e.preventDefault()
      const delta = -e.deltaY * 0.01
      const next = Math.min(Math.max(visualScaleRef.current + delta, 0.25), 3)
      visualScaleRef.current = next

      const wrapper = pagesWrapperRef.current
      if (wrapper) {
        const ratio = next / scaleRef.current
        wrapper.style.transform = `scale(${ratio})`
        wrapper.style.transformOrigin = 'top center'
      }
      setDisplayScale(next)

      clearTimeout(gestureTimerRef.current)
      gestureTimerRef.current = setTimeout(() => {
        const final = visualScaleRef.current
        const oldCommitted = scaleRef.current
        const scrollTop = container.scrollTop
        const ratio = final / oldCommitted
        scaleRef.current = final
        flushSync(() => setScale(final))
        container.scrollTop = scrollTop * ratio
        if (pagesWrapperRef.current) pagesWrapperRef.current.style.transform = ''
      }, 150)
    }
    container.addEventListener('wheel', onWheel, { passive: false })
    return () => {
      container.removeEventListener('wheel', onWheel)
      clearTimeout(gestureTimerRef.current)
    }
  }, [])

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey)) return
      if (e.key === '=' || e.key === '+') { e.preventDefault(); zoomIn() }
      else if (e.key === '-') { e.preventDefault(); zoomOut() }
      else if (e.key === '0') { e.preventDefault(); zoomReset() }
    }
    document.addEventListener('keydown', onKeyDown, true)
    return () => document.removeEventListener('keydown', onKeyDown, true)
  }, [zoomIn, zoomOut, zoomReset])

  return (
    <div className={cn('relative flex flex-col h-full', className)}>
      {numPages > 0 && !hideToolbar && (
        <div className="flex items-center gap-0.5 px-4 py-1.5 border-b border-border text-xs text-muted-foreground flex-shrink-0">
          {searchOpen ? (
            <>
              <div className="flex items-center flex-1 gap-1.5 min-w-0">
                <Search className="size-3 flex-shrink-0 opacity-50" />
                <input
                  ref={searchInputRef}
                  type="text"
                  value={searchQuery}
                  onChange={(e) => {
                    const value = e.target.value
                    setSearchQuery(value)
                    clearTimeout(debounceTimerRef.current)
                    debounceTimerRef.current = setTimeout(() => performSearch(value), 200)
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') { e.preventDefault(); navigateMatch(e.shiftKey ? -1 : 1) }
                    if (e.key === 'Escape') closeSearch()
                  }}
                  placeholder="Find in document..."
                  aria-label="Find in document"
                  className="flex-1 min-w-0 bg-transparent outline-none text-foreground placeholder:text-muted-foreground/50"
                />
              </div>
              {matchCount > 0 && (
                <span className="tabular-nums text-[10px] flex-shrink-0">{currentMatchIndex + 1}/{matchCount}</span>
              )}
              {searchQuery && matchCount === 0 && !isIndexing && (
                <span className="text-[10px] flex-shrink-0 opacity-50">No results</span>
              )}
              {isIndexing && searchQuery && (
                <span className="text-[10px] flex-shrink-0 opacity-50">Indexing...</span>
              )}
              <button onClick={() => navigateMatch(-1)} disabled={matchCount === 0} aria-label="Previous match" className="p-1.5 rounded-md hover:text-foreground hover:bg-accent disabled:opacity-30 cursor-pointer">
                <ChevronUp className="size-3.5" />
              </button>
              <button onClick={() => navigateMatch(1)} disabled={matchCount === 0} aria-label="Next match" className="p-1.5 rounded-md hover:text-foreground hover:bg-accent disabled:opacity-30 cursor-pointer">
                <ChevronDown className="size-3.5" />
              </button>
              <button onClick={closeSearch} aria-label="Close search" className="p-1.5 rounded-md hover:text-foreground hover:bg-accent cursor-pointer">
                <X className="size-3.5" />
              </button>
            </>
          ) : (
            <>
              {title && <span className="min-w-0 truncate text-foreground mr-auto">{title}</span>}
              {!title && <div className="flex-1" />}
              <button onClick={openSearch} aria-label="Find in document" className="p-1.5 rounded-md hover:text-foreground hover:bg-accent cursor-pointer" title="Find (Cmd+F)">
                <Search className="size-3.5" />
              </button>
              {documentId && (
                <button
                  onClick={() => setDrawerOpen((v) => !v)}
                  aria-label="Highlights"
                  className={cn(
                    'p-1.5 rounded-md hover:text-foreground hover:bg-accent cursor-pointer',
                    drawerOpen && 'text-foreground bg-accent',
                  )}
                  title={`Highlights (${pdfHighlightCount})`}
                >
                  <MessageSquare className="size-3.5" />
                </button>
              )}
              <a href={fileUrl} download className="p-1.5 rounded-md hover:text-foreground hover:bg-accent" title="Download PDF">
                <Download className="size-3.5" />
              </a>
              <div className="w-px h-4 bg-border mx-1" />
              <div className="flex items-center gap-0.5">
                <button onClick={() => scrollToPage(Math.max(1, currentPage - 1))} disabled={currentPage <= 1} className="p-1.5 rounded-md hover:text-foreground hover:bg-accent disabled:opacity-30 cursor-pointer">
                  <ChevronUp className="size-3.5" />
                </button>
                {pageInputActive ? (
                  <input
                    ref={pageInputRef}
                    type="text"
                    inputMode="numeric"
                    value={pageInputValue}
                    onChange={(e) => setPageInputValue(e.target.value.replace(/\D/g, ''))}
                    onKeyDown={(e) => { if (e.key === 'Enter') commitPageInput(); if (e.key === 'Escape') setPageInputActive(false) }}
                    onBlur={commitPageInput}
                    className="w-8 text-center bg-muted/50 rounded px-1 py-0.5 outline-none text-foreground tabular-nums"
                  />
                ) : (
                  <button onClick={activatePageInput} className="tabular-nums hover:text-foreground cursor-text" title="Go to page">
                    {currentPage}
                  </button>
                )}
                <span className="opacity-50">/ {numPages}</span>
                <button onClick={() => scrollToPage(Math.min(numPages, currentPage + 1))} disabled={currentPage >= numPages} className="p-1.5 rounded-md hover:text-foreground hover:bg-accent disabled:opacity-30 cursor-pointer">
                  <ChevronDown className="size-3.5" />
                </button>
              </div>
              <div className="w-px h-4 bg-border mx-1" />
              <div className="flex items-center gap-0.5">
                <button onClick={zoomOut} disabled={displayScale <= 0.25} className="p-1.5 rounded-md hover:text-foreground hover:bg-accent disabled:opacity-30 cursor-pointer" title="Zoom out">
                  <ZoomOut className="size-3.5" />
                </button>
                <button onClick={zoomReset} className="tabular-nums hover:text-foreground min-w-[3ch] text-center cursor-pointer" title="Reset zoom">
                  {Math.round(displayScale * 100)}%
                </button>
                <button onClick={zoomIn} disabled={displayScale >= 3} className="p-1.5 rounded-md hover:text-foreground hover:bg-accent disabled:opacity-30 cursor-pointer" title="Zoom in">
                  <ZoomIn className="size-3.5" />
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {notice && (
        <div className="pointer-events-none absolute left-1/2 top-3 z-20 -translate-x-1/2 rounded-md border border-zinc-200 bg-white px-3 py-1.5 text-xs text-zinc-700 shadow">
          {notice}
        </div>
      )}

      <div className="flex flex-1 min-h-0">
      <div ref={containerRef} className="relative flex-1 overflow-auto no-scrollbar bg-muted/30">
        <div ref={pagesWrapperRef}>
          <Document
            file={fileUrl}
            onLoadSuccess={onDocLoad}
            loading={
              <div className="flex items-center justify-center py-16">
                <div className="size-5 border-2 border-muted-foreground/20 border-t-muted-foreground rounded-full animate-spin" />
              </div>
            }
            error={
              <div className="text-center py-16 text-sm text-destructive">
                <p>Failed to load PDF</p>
              </div>
            }
          >
            {numPages > 0 &&
              Array.from({ length: numPages }, (_, i) => i + 1).map((pageNum) => {
                const shouldRender = visiblePages.has(pageNum)
                const aspect = pageAspectRef.current.get(pageNum)
                const placeholderH = aspect ? pageWidth * aspect : estimatedPageHeight

                return (
                  <div
                    key={pageNum}
                    data-page={pageNum}
                    ref={(el) => {
                      if (el) pageRefs.current.set(pageNum, el)
                      else pageRefs.current.delete(pageNum)
                    }}
                    onMouseUp={(e) => handlePageMouseUp(pageNum, e.currentTarget)}
                    className="relative mx-auto mb-4"
                    style={{
                      width: pageWidth > 0 ? pageWidth : undefined,
                      height: shouldRender ? undefined : placeholderH,
                    }}
                  >
                    {shouldRender && (
                      <Page
                        pageNumber={pageNum}
                        width={pageWidth > 0 ? pageWidth : undefined}
                        renderTextLayer
                        renderAnnotationLayer={false}
                        loading={<div style={{ height: placeholderH }} />}
                        onLoadSuccess={(page) => onPageLoadSuccess(pageNum, page)}
                      />
                    )}
                    {shouldRender && documentId && (
                      <PdfHighlightLayer
                        pageWidth={pageWidth}
                        proxy={pageProxies.get(pageNum)}
                        highlights={pdfHighlightsByPage.get(pageNum) ?? []}
                        onHighlightClick={handleHighlightClick}
                      />
                    )}
                    {shouldRender && popover?.pageNumber === pageNum && !commentExpanded && popover.mode === 'create' && (
                      <div
                        className="pdf-highlight-popover absolute z-10 flex items-center gap-1 rounded-full bg-zinc-900 px-1.5 py-1 text-xs text-white shadow-lg"
                        style={{ left: popover.position.left, top: popover.position.top }}
                        onMouseDown={(e) => e.stopPropagation()}
                      >
                        <button
                          onClick={saveHighlight}
                          disabled={savingHighlight}
                          className="rounded-full px-3 py-1 font-medium hover:bg-white/10 disabled:opacity-50"
                        >
                          {savingHighlight ? 'Saving…' : 'Highlight'}
                        </button>
                        <button
                          onClick={startNoteFromCreate}
                          disabled={savingHighlight}
                          className="rounded-full px-3 py-1 font-medium hover:bg-white/10 disabled:opacity-50"
                        >
                          Note
                        </button>
                      </div>
                    )}
                    {shouldRender && popover?.pageNumber === pageNum && !commentExpanded && popover.mode === 'edit' && !popover.highlight.comment && (
                      <div
                        className="pdf-highlight-popover absolute z-10 flex items-center gap-1 rounded-full bg-zinc-900 px-1.5 py-1 text-xs text-white shadow-lg"
                        style={{ left: popover.position.left, top: popover.position.top }}
                        onMouseDown={(e) => e.stopPropagation()}
                      >
                        <button
                          onClick={() => setCommentExpanded(true)}
                          disabled={savingHighlight}
                          className="rounded-full px-3 py-1 font-medium hover:bg-white/10 disabled:opacity-50"
                        >
                          Add note
                        </button>
                        <button
                          onClick={deleteHighlight}
                          disabled={savingHighlight}
                          className="rounded-full px-3 py-1 font-medium text-red-300 hover:bg-white/10 disabled:opacity-50"
                        >
                          {savingHighlight ? 'Deleting…' : 'Delete'}
                        </button>
                      </div>
                    )}
                    {shouldRender && popover?.pageNumber === pageNum && !commentExpanded && popover.mode === 'edit' && popover.highlight.comment && (
                      <div
                        className="pdf-highlight-popover absolute z-10 flex flex-col gap-2 rounded-md border border-zinc-200 bg-white p-3 shadow-lg"
                        style={{ left: popover.position.left, top: popover.position.top, width: 260 }}
                        onMouseDown={(e) => e.stopPropagation()}
                      >
                        <p className="whitespace-pre-wrap text-xs leading-snug text-zinc-700">
                          {popover.highlight.comment}
                        </p>
                        <div className="flex items-center justify-end gap-1 border-t border-zinc-100 pt-2">
                          <button
                            onClick={deleteHighlight}
                            disabled={savingHighlight}
                            className="rounded px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
                          >
                            {savingHighlight ? 'Deleting…' : 'Delete'}
                          </button>
                          <button
                            onClick={() => setCommentExpanded(true)}
                            disabled={savingHighlight}
                            className="rounded bg-zinc-950 px-2 py-1 text-xs font-medium text-white hover:bg-zinc-800 disabled:opacity-50"
                          >
                            Edit
                          </button>
                        </div>
                      </div>
                    )}
                    {shouldRender && popover?.pageNumber === pageNum && commentExpanded && (
                      <div
                        className="pdf-highlight-popover absolute z-10 flex flex-col gap-2 rounded-md border border-zinc-200 bg-white p-2 shadow-lg"
                        style={{
                          left: popover.position.left,
                          top: popover.position.top,
                          width: 240,
                        }}
                        onMouseDown={(e) => e.stopPropagation()}
                      >
                        <textarea
                          autoFocus
                          rows={2}
                          placeholder="Add a comment (optional)"
                          value={commentDraft}
                          onChange={(e) => setCommentDraft(e.target.value)}
                          className="w-full resize-none rounded border border-zinc-200 px-2 py-1 text-xs outline-none focus:border-zinc-400"
                        />
                        <div className="flex items-center justify-between gap-1">
                          {popover.mode === 'edit' ? (
                            <button
                              onClick={deleteHighlight}
                              disabled={savingHighlight}
                              className="rounded px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
                            >
                              Delete
                            </button>
                          ) : (
                            <span />
                          )}
                          <div className="flex gap-1">
                            <button
                              onClick={cancelPopover}
                              className="rounded px-2 py-1 text-xs font-medium text-zinc-500 hover:bg-zinc-100"
                            >
                              Cancel
                            </button>
                            <button
                              onClick={saveHighlight}
                              disabled={savingHighlight}
                              className="rounded bg-zinc-950 px-2 py-1 text-xs font-medium text-white hover:bg-zinc-800 disabled:opacity-50"
                            >
                              {savingHighlight ? 'Saving…' : popover.mode === 'edit' ? 'Save' : 'Highlight'}
                            </button>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                )
              })}
          </Document>
        </div>
      </div>

      {documentId && drawerOpen && (
        <aside className="hidden w-72 shrink-0 border-l border-border bg-background md:flex md:flex-col">
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <div className="text-xs font-semibold text-foreground">
              Highlights {pdfHighlightCount > 0 ? `(${pdfHighlightCount})` : ''}
            </div>
            <button
              onClick={() => setDrawerOpen(false)}
              className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
              aria-label="Close highlights drawer"
            >
              <X className="size-3.5" />
            </button>
          </div>
          <div className="flex-1 overflow-auto">
            {pdfHighlightsSorted.length === 0 ? (
              <div className="px-3 py-6 text-center text-xs text-muted-foreground">
                Select text in the PDF to highlight or add a comment.
              </div>
            ) : (
              <ul className="divide-y divide-border">
                {pdfHighlightsSorted.map((h) => (
                  <li key={h.id}>
                    <button
                      onClick={() => jumpToHighlight(h)}
                      className="block w-full px-3 py-2 text-left transition-colors hover:bg-accent/50"
                    >
                      <div className="line-clamp-3 text-xs text-foreground">
                        &ldquo;{h.pdfAnchor.textContent}&rdquo;
                      </div>
                      <div className="mt-1 flex items-center gap-2 text-[11px] text-muted-foreground">
                        <span>Page {h.pdfAnchor.page}</span>
                        {h.comment && <span className="truncate">· {h.comment}</span>}
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>
      )}
      </div>

      <style jsx global>{`
        .search-mark {
          background: rgba(255, 235, 59, 0.45);
          border-radius: 1px;
          color: inherit;
          padding: 0;
        }
        .search-mark-active {
          background: rgba(255, 150, 0, 0.7);
        }
        .pdf-hl-rect {
          position: absolute;
          background: rgba(255, 224, 84, 0.42);
          mix-blend-mode: multiply;
          border-radius: 2px;
          pointer-events: auto;
          cursor: pointer;
          z-index: 5;
        }
        .pdf-hl-rect:hover {
          background: rgba(255, 213, 43, 0.6);
        }
        .pdf-hl-note-badge {
          position: absolute;
          z-index: 6;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          width: 14px;
          height: 14px;
          border-radius: 9999px;
          background: rgb(234, 179, 8);
          color: white;
          font-size: 10px;
          font-weight: 600;
          line-height: 1;
          box-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
          pointer-events: auto;
          cursor: pointer;
        }
        .pdf-hl-note-badge:hover {
          background: rgb(202, 138, 4);
        }
      `}</style>
    </div>
  )
}

interface PdfHighlightLayerProps {
  pageWidth: number
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  proxy: any | undefined
  highlights: Highlight[]
  onHighlightClick: (h: Highlight) => void
}

function PdfHighlightLayer({ pageWidth, proxy, highlights, onHighlightClick }: PdfHighlightLayerProps) {
  if (!proxy || highlights.length === 0) return null
  const base = proxy.getViewport({ scale: 1 })
  const renderedWidth = pageWidth > 0 ? pageWidth : base.width
  const viewport = proxy.getViewport({ scale: renderedWidth / base.width })

  return (
    <>
      {highlights.map((h) => {
        if (!h.pdfAnchor) return null
        const rects = pdfRectsToViewport(h.pdfAnchor.rects, viewport)
        const lastRect = rects[rects.length - 1]
        return (
          <React.Fragment key={h.id}>
            {rects.map((r, idx) => (
              <div
                key={`${h.id}-${idx}`}
                className="pdf-hl-rect"
                title={h.comment ?? undefined}
                style={{ left: r.left, top: r.top, width: r.width, height: r.height }}
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => { e.stopPropagation(); onHighlightClick(h) }}
              />
            ))}
            {h.comment && lastRect && (
              <div
                className="pdf-hl-note-badge"
                title={h.comment}
                style={{ left: lastRect.left + lastRect.width - 4, top: lastRect.top - 6 }}
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => { e.stopPropagation(); onHighlightClick(h) }}
              >
                ●
              </div>
            )}
          </React.Fragment>
        )
      })}
    </>
  )
}
