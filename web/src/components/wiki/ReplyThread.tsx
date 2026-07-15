'use client'

import type { HighlightReply } from '@/lib/highlights/types'

export function ReplyThread({ replies }: { replies: HighlightReply[] }) {
  if (replies.length === 0) return null
  return (
    <div className="mt-2 space-y-1.5">
      {replies.map((reply) => (
        <div key={reply.id} className="border-l-2 border-border pl-2.5">
          <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground/60">
            {reply.author === 'agent' ? 'Claude' : 'You'}
          </span>
          <p className="mt-0.5 whitespace-pre-wrap text-[13px] leading-relaxed text-foreground/80">
            {reply.text}
          </p>
        </div>
      ))}
    </div>
  )
}
