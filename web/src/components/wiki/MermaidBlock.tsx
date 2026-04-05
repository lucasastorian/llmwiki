'use client'

import * as React from 'react'

export function MermaidBlock({ chart }: { chart: string }) {
  const containerRef = React.useRef<HTMLDivElement>(null)
  const idRef = React.useRef(`mermaid-${Math.random().toString(36).slice(2, 9)}`)

  React.useEffect(() => {
    let cancelled = false
    import('mermaid').then(({ default: mermaid }) => {
      mermaid.initialize({ startOnLoad: false, theme: 'neutral' })
      mermaid
        .render(idRef.current, chart)
        .then(({ svg }) => {
          if (!cancelled && containerRef.current) {
            containerRef.current.innerHTML = svg
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
    <div
      ref={containerRef}
      className="my-6 flex justify-center [&_svg]:max-w-full"
    />
  )
}
