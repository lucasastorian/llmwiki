'use client'

import * as React from 'react'
import { Maximize2 } from 'lucide-react'
import { DiagramViewer } from './DiagramViewer'

function useIsDarkMode(): boolean {
  const [isDark, setIsDark] = React.useState(false)
  React.useEffect(() => {
    const root = document.documentElement
    const update = () => setIsDark(root.classList.contains('dark'))
    update()
    const observer = new MutationObserver(update)
    observer.observe(root, { attributes: true, attributeFilter: ['class'] })
    return () => observer.disconnect()
  }, [])
  return isDark
}

export function MermaidBlock({ chart }: { chart: string }) {
  const containerRef = React.useRef<HTMLDivElement>(null)
  const idRef = React.useRef(`mermaid-${Math.random().toString(36).slice(2, 9)}`)
  const [svgContent, setSvgContent] = React.useState<string | null>(null)
  const [failed, setFailed] = React.useState(false)
  const [fullscreen, setFullscreen] = React.useState(false)
  const isDark = useIsDarkMode()

  React.useEffect(() => {
    let cancelled = false
    setFailed(false)
    import('mermaid').then(({ default: mermaid }) => {
      // Without suppressErrorRendering, a parse failure ALSO injects mermaid's
      // bomb error SVG into document.body — the promise rejection alone is not
      // the whole failure mode.
      mermaid.initialize({
        startOnLoad: false,
        suppressErrorRendering: true,
        theme: isDark ? 'dark' : 'neutral',
      })
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
          if (!cancelled) {
            setSvgContent(null)
            setFailed(true)
          }
        })
    })
    return () => {
      cancelled = true
    }
  }, [chart, isDark])

  if (failed) {
    return (
      <pre className="my-3 overflow-x-auto rounded-lg border border-border bg-muted/60 p-4 text-[13px] leading-relaxed text-muted-foreground">
        {chart}
      </pre>
    )
  }

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
