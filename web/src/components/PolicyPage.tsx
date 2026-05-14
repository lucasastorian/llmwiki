'use client'

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import Link from 'next/link'

export function PolicyPage({ content }: { content: string }) {
  return (
    <div className="min-h-svh bg-background text-foreground">
      {/* Nav */}
      <nav className="fixed top-0 inset-x-0 z-50 flex items-center justify-between px-6 lg:px-10 h-14 bg-background/80 backdrop-blur-sm border-b border-border">
        <Link href="/" className="flex items-center gap-2.5 text-sm font-semibold tracking-tight">
          <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 32 32">
            <rect width="32" height="32" rx="7" fill="currentColor" className="text-foreground" />
            <polyline points="11,8 21,16 11,24" fill="none" stroke="currentColor" className="text-background" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          LLM Wiki
        </Link>
        <div className="flex items-center gap-5">
          <Link
            href="/login"
            className="text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            Sign in
          </Link>
          <Link
            href="/signup"
            className="hidden sm:inline-flex items-center gap-1.5 rounded-full bg-foreground text-background px-4 py-1.5 text-sm font-medium hover:opacity-90 transition-opacity"
          >
            Get started
          </Link>
        </div>
      </nav>

      {/* Content */}
      <article className="max-w-2xl mx-auto px-6 pt-28 pb-20">
        <div className="policy-prose">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              a: ({ href, children }) => {
                if (href?.startsWith('/')) {
                  return <Link href={href} className="text-foreground underline underline-offset-2 decoration-foreground/30 hover:decoration-foreground transition-colors">{children}</Link>
                }
                return <a href={href} target="_blank" rel="noopener noreferrer" className="text-foreground underline underline-offset-2 decoration-foreground/30 hover:decoration-foreground transition-colors">{children}</a>
              },
              table: ({ children }) => (
                <div className="overflow-x-auto my-6">
                  <table className="w-full text-sm border-collapse">{children}</table>
                </div>
              ),
              th: ({ children }) => (
                <th className="text-left font-medium text-foreground border-b border-border px-3 py-2 bg-muted/50">{children}</th>
              ),
              td: ({ children }) => (
                <td className="text-muted-foreground border-b border-border px-3 py-2">{children}</td>
              ),
            }}
          >
            {content}
          </ReactMarkdown>
        </div>
      </article>

      {/* Footer */}
      <footer className="border-t border-border px-6 lg:px-10 py-6 flex items-center justify-between text-xs text-muted-foreground/50">
        <span>LLM Wiki</span>
        <div className="flex items-center gap-4">
          <Link href="/terms" className="hover:text-muted-foreground transition-colors">Terms</Link>
          <Link href="/privacy" className="hover:text-muted-foreground transition-colors">Privacy</Link>
        </div>
      </footer>
    </div>
  )
}
