'use client'

import * as React from 'react'
import { Maximize2, X } from 'lucide-react'

export function MermaidBlock({ chart }: { chart: string }) {
  const containerRef = React.useRef<HTMLDivElement>(null)
  const idRef = React.useRef(`mermaid-${Math.random().toString(36).slice(2, 9)}`)
  const [svgContent, setSvgContent] = React.useState<string | null>(null)
  const [fullscreen, setFullscreen] = React.useState(false)

  React.useEffect(() => {
    let cancelled = false
    import('mermaid').then(({ default: mermaid }) => {
      mermaid.initialize({ startOnLoad: false, theme: 'neutral' })
      mermaid
        .render(idRef.current, chart)
        .then(({ svg }) => {
          if (!cancelled) {
            setSvgContent(svg)
            if (containerRef.current) {
              containerRef.current.innerHTML = svg
            }
          }
        })
        .catch(() => {
          if (!cancelled && containerRef.current) {
            containerRef.current.textContent = chart
          }
        })
    })
    return () => {
      cancelled = true
    }
  }, [chart])

  return (
    <>
      <div className="my-6 relative group">
        <div
          ref={containerRef}
          className="flex justify-center [&_svg]:max-w-full cursor-pointer"
          onClick={() => svgContent && setFullscreen(true)}
        />
        {svgContent && (
          <button
            onClick={() => setFullscreen(true)}
            className="absolute top-2 right-2 p-1.5 rounded-md bg-background/80 border border-border text-muted-foreground hover:text-foreground opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer"
            title="View fullscreen"
          >
            <Maximize2 className="size-3.5" />
          </button>
        )}
      </div>

      {fullscreen && svgContent && (
        <div
          className="fixed inset-0 z-50 bg-background/90 backdrop-blur-sm flex items-center justify-center p-8"
          onClick={() => setFullscreen(false)}
        >
          <button
            onClick={() => setFullscreen(false)}
            className="absolute top-4 right-4 p-2 rounded-md bg-muted hover:bg-accent text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
          >
            <X className="size-5" />
          </button>
          <div
            className="max-w-full max-h-full overflow-auto [&_svg]:max-w-none [&_svg]:max-h-[85vh]"
            onClick={(e) => e.stopPropagation()}
            dangerouslySetInnerHTML={{ __html: svgContent }}
          />
        </div>
      )}
    </>
  )
}
