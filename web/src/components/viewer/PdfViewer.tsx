'use client'

import React, { useCallback, useEffect, useRef, useState } from 'react'
import { flushSync } from 'react-dom'
import { Document, Page } from 'react-pdf'
import { ChevronUp, ChevronDown, Search, X, Download, ZoomIn, ZoomOut } from 'lucide-react'
import { cn } from '@/lib/utils'
import { ensurePdfWorker } from '@/lib/pdfjs'

import 'react-pdf/dist/Page/TextLayer.css'
import 'react-pdf/dist/Page/AnnotationLayer.css'

ensurePdfWorker()

type Props = {
  fileUrl: string
  title?: string
  className?: string
  initialPage?: number
  hideToolbar?: boolean
}

const VIRTUALIZE_BUFFER = 2

export default function PdfViewer({ fileUrl, title, className, initialPage, hideToolbar }: Props) {
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

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const onPageLoadSuccess = useCallback((pageNumber: number, page: any) => {
    const vp = page.getViewport({ scale: 1 })
    pageAspectRef.current.set(pageNumber, vp.height / vp.width)
  }, [])

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
    <div className={cn('flex flex-col h-full', className)}>
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

      <div ref={containerRef} className="flex-1 overflow-auto no-scrollbar bg-muted/30">
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
                  </div>
                )
              })}
          </Document>
        </div>
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
      `}</style>
    </div>
  )
}
