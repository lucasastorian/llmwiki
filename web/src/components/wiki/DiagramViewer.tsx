'use client'

import * as React from 'react'
import { X, ZoomIn, ZoomOut, Maximize2 } from 'lucide-react'

const MIN_SCALE = 0.25
const MAX_SCALE = 5
const ZOOM_STEP = 0.25

interface DiagramViewerProps {
  content: string
  type: 'svg' | 'img'
  alt?: string
  onClose: () => void
}

function buildSrcdoc(content: string, type: 'svg' | 'img', alt?: string): string {
  const body = type === 'svg'
    ? content
    : `<img src="${content}" alt="${alt || ''}" style="max-width:100%;height:auto" />`

  return `<!DOCTYPE html>
<html><head><style>
  html, body { margin: 0; padding: 0; overflow: hidden; display: flex; align-items: center; justify-content: center; width: 100%; height: 100%; background: transparent; }
  svg { max-width: none; height: auto; }
  img { max-width: none; height: auto; }
</style></head><body>${body}</body></html>`
}

export function DiagramViewer({ content, type, alt, onClose }: DiagramViewerProps) {
  const [scale, setScale] = React.useState(1.25)
  const [translate, setTranslate] = React.useState({ x: 0, y: 0 })
  const dragging = React.useRef(false)
  const lastPos = React.useRef({ x: 0, y: 0 })

  const zoomIn = () => setScale((s) => Math.min(s + ZOOM_STEP, MAX_SCALE))
  const zoomOut = () => setScale((s) => Math.max(s - ZOOM_STEP, MIN_SCALE))
  const zoomReset = () => { setScale(1.25); setTranslate({ x: 0, y: 0 }) }

  const handleWheel = React.useCallback((e: React.WheelEvent) => {
    e.preventDefault()
    const delta = e.deltaY > 0 ? -ZOOM_STEP : ZOOM_STEP
    setScale((s) => Math.min(Math.max(s + delta, MIN_SCALE), MAX_SCALE))
  }, [])

  const handlePointerDown = React.useCallback((e: React.PointerEvent) => {
    dragging.current = true
    lastPos.current = { x: e.clientX, y: e.clientY }
    ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
  }, [])

  const handlePointerMove = React.useCallback((e: React.PointerEvent) => {
    if (!dragging.current) return
    const dx = e.clientX - lastPos.current.x
    const dy = e.clientY - lastPos.current.y
    lastPos.current = { x: e.clientX, y: e.clientY }
    setTranslate((t) => ({ x: t.x + dx, y: t.y + dy }))
  }, [])

  const handlePointerUp = React.useCallback(() => {
    dragging.current = false
  }, [])

  React.useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if (e.key === '=' || e.key === '+') zoomIn()
      if (e.key === '-') zoomOut()
      if (e.key === '0') zoomReset()
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [onClose])

  const srcdoc = React.useMemo(() => buildSrcdoc(content, type, alt), [content, type, alt])

  return (
    <div className="fixed inset-0 z-50 bg-background/90 backdrop-blur-sm flex flex-col">
      {/* Controls */}
      <div className="shrink-0 flex items-center justify-between px-4 h-10">
        <div className="flex items-center gap-1 text-xs text-muted-foreground">
          <button onClick={zoomOut} disabled={scale <= MIN_SCALE} className="p-1.5 rounded-md hover:bg-accent hover:text-foreground disabled:opacity-30 cursor-pointer" title="Zoom out">
            <ZoomOut className="size-3.5" />
          </button>
          <button onClick={zoomReset} className="tabular-nums hover:text-foreground cursor-pointer min-w-[3.5ch] text-center" title="Reset zoom">
            {Math.round(scale * 100)}%
          </button>
          <button onClick={zoomIn} disabled={scale >= MAX_SCALE} className="p-1.5 rounded-md hover:bg-accent hover:text-foreground disabled:opacity-30 cursor-pointer" title="Zoom in">
            <ZoomIn className="size-3.5" />
          </button>
        </div>
        <button onClick={onClose} className="p-1.5 rounded-md hover:bg-accent text-muted-foreground hover:text-foreground cursor-pointer" title="Close">
          <X className="size-4" />
        </button>
      </div>

      {/* Canvas */}
      <div
        className="flex-1 overflow-hidden cursor-grab active:cursor-grabbing"
        onWheel={handleWheel}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
      >
        <div
          className="w-full h-full flex items-center justify-center"
          style={{
            transform: `translate(${translate.x}px, ${translate.y}px) scale(${scale})`,
            transformOrigin: 'center center',
          }}
        >
          <iframe
            srcDoc={srcdoc}
            sandbox="allow-same-origin"
            title={alt || 'Diagram'}
            className="border-none bg-transparent pointer-events-none"
            style={{ width: '80vw', height: '80vh' }}
          />
        </div>
      </div>
    </div>
  )
}

export function ExpandableMedia({
  children,
  content,
  type,
  alt,
}: {
  children: React.ReactNode
  content: string
  type: 'svg' | 'img'
  alt?: string
}) {
  const [fullscreen, setFullscreen] = React.useState(false)

  return (
    <>
      <div className="relative group cursor-pointer" onClick={() => setFullscreen(true)}>
        {children}
        <button
          onClick={(e) => { e.stopPropagation(); setFullscreen(true) }}
          className="absolute top-2 right-2 p-1.5 rounded-md bg-background/80 border border-border text-muted-foreground hover:text-foreground opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer"
          title="View fullscreen"
        >
          <Maximize2 className="size-3.5" />
        </button>
      </div>

      {fullscreen && (
        <DiagramViewer content={content} type={type} alt={alt} onClose={() => setFullscreen(false)} />
      )}
    </>
  )
}
