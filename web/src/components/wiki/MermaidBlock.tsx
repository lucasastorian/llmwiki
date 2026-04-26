'use client'

import * as React from 'react'
import { Maximize2 } from 'lucide-react'
import { DiagramViewer } from './DiagramViewer'

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
      <div
        className="my-6 relative group"
        onClick={() => svgContent && setFullscreen(true)}
      >
        <div
          ref={containerRef}
          className="flex justify-center [&_svg]:max-w-full cursor-pointer"
        />
        {svgContent && (
          <button
            onClick={(e) => { e.stopPropagation(); setFullscreen(true) }}
            className="absolute top-2 right-2 p-1.5 rounded-md bg-background/80 border border-border text-muted-foreground hover:text-foreground opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer"
            title="View fullscreen"
          >
            <Maximize2 className="size-3.5" />
          </button>
        )}
      </div>

      {fullscreen && svgContent && (
        <DiagramViewer content={svgContent} type="svg" onClose={() => setFullscreen(false)} />
      )}
    </>
  )
}
