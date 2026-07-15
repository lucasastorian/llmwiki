'use client'

import * as React from 'react'
import { domPlaintextFromContainer, rangeFromOffsets } from '@/lib/highlights/domPlaintext'
import { resolveHighlightOffsets } from '@/lib/highlights/resolveHighlightOffsets'
import { ReplyThread } from './ReplyThread'
import type { Highlight } from '@/lib/highlights/types'

export function WikiComments({
  highlights,
  contentRef,
}: {
  highlights: Highlight[]
  contentRef: React.RefObject<HTMLDivElement | null>
}) {
  const noted = React.useMemo(
    () =>
      highlights
        .filter((h) => (h.comment || (h.replies?.length ?? 0) > 0) && h.type !== 'pdf')
        .sort((a, b) => (a.textAnchor?.textStart ?? 0) - (b.textAnchor?.textStart ?? 0)),
    [highlights],
  )

  const scrollToHighlight = React.useCallback(
    (highlight: Highlight) => {
      const content = contentRef.current
      if (!content) return
      const dp = domPlaintextFromContainer(content)
      const offsets = resolveHighlightOffsets(highlight, dp)
      if (!offsets) return
      const range = rangeFromOffsets(dp, offsets.start, offsets.end)
      const target = range?.startContainer.parentElement
      target?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    },
    [contentRef],
  )

  if (noted.length === 0) return null

  return (
    <section className="mt-12 pt-6 border-t border-border">
      <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground/50 mb-4">
        Notes
      </p>
      <div className="space-y-5">
        {noted.map((highlight) => (
          <button
            key={highlight.id}
            onClick={() => scrollToHighlight(highlight)}
            className="group block w-full cursor-pointer text-left"
          >
            <blockquote className="border-l-2 border-amber-400/60 pl-3 text-[13px] leading-relaxed text-muted-foreground line-clamp-2 transition-colors group-hover:text-foreground">
              {(highlight.textAnchor ?? highlight.anchor)?.textContent}
            </blockquote>
            {highlight.comment && (
              <p className="mt-1.5 pl-3 text-sm leading-relaxed text-foreground/90 whitespace-pre-wrap">
                {highlight.comment}
              </p>
            )}
            <div className="ml-3">
              <ReplyThread replies={highlight.replies ?? []} />
            </div>
          </button>
        ))}
      </div>
    </section>
  )
}
