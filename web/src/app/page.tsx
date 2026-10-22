import Link from 'next/link'
import { ArrowRight, BookOpen, FileText, PenTool, Search, GitBranch, History } from 'lucide-react'
import { AuthRedirect } from './AuthRedirect'
import { MotionDiv, MotionP } from './LandingMotion'

const ease: [number, number, number, number] = [0.16, 1, 0.3, 1]

const WIKI_TREE = [
  { label: 'Recent', active: true, depth: 0 },
  { label: 'Overview', depth: 0 },
  { label: 'Concepts', depth: 0, folder: true },
  { label: 'Attention Mechanisms', depth: 1 },
  { label: 'Scaling Laws', depth: 1 },
  { label: 'Entities', depth: 0, folder: true },
  { label: 'Transformer Architecture', depth: 1 },
  { label: 'Sources', depth: 0, folder: true },
]

const RECENT_CHANGES = [
  { time: '10:42', verb: 'Edited', subject: 'Sparse attention', meta: '4 edits' },
  { time: '09:18', verb: 'Added', subject: 'attention-is-all-you-need.pdf', meta: 'PDF' },
  { time: '08:56', verb: 'Created', subject: 'Evaluation methodology', meta: '' },
]

const jsonLd = {
  '@context': 'https://schema.org',
  '@type': 'SoftwareApplication',
  name: 'LLM Wiki',
  applicationCategory: 'ProductivityApplication',
  operatingSystem: 'Web',
  offers: { '@type': 'Offer', price: '0', priceCurrency: 'USD' },
  url: 'https://llmwiki.app',
  description:
    "Free, open-source implementation of Karpathy's LLM Wiki. Upload documents and build a compounding wiki directly via Claude.",
}

export default function LandingPage() {
  return (
    <div className="min-h-svh bg-background text-foreground">
      <AuthRedirect />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />

      <nav className="fixed top-0 inset-x-0 z-50 flex items-center justify-between px-6 lg:px-10 h-14 bg-background/80 backdrop-blur-sm">
        <span className="flex items-center gap-2.5 text-sm font-semibold tracking-tight">
          <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 32 32">
            <rect width="32" height="32" rx="7" fill="currentColor" className="text-foreground" />
            <polyline points="11,8 21,16 11,24" fill="none" stroke="currentColor" className="text-background" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          LLM Wiki
        </span>
        <div className="flex items-center gap-5">
          <Link
            href="https://github.com/lucasastorian/llmwiki"
            className="text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            GitHub
          </Link>
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

      <section className="pt-32 pb-20 px-6 lg:px-10">
        <div className="max-w-2xl mx-auto text-center">
          <MotionDiv
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.8, ease }}
          >
            <p className="text-sm text-muted-foreground mb-4">
              Open-source implementation of{' '}
              <Link
                href="https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f"
                className="text-foreground underline underline-offset-2 decoration-foreground/30 hover:decoration-foreground transition-colors"
              >
                Karpathy&apos;s LLM&nbsp;Wiki
              </Link>
            </p>
            <h1 className="text-4xl sm:text-5xl md:text-6xl font-bold tracking-tight leading-[1.05]">
              LLM Wiki
            </h1>
          </MotionDiv>

          <MotionP
            initial={{ opacity: 0, y: 16 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.8, delay: 0.12, ease }}
            className="mt-6 text-base sm:text-lg text-muted-foreground max-w-md mx-auto leading-relaxed"
          >
            Your LLM compiles and maintains a structured wiki from raw&nbsp;sources.
          </MotionP>

          <MotionDiv
            initial={{ opacity: 0, y: 12 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.7, delay: 0.25, ease }}
            className="mt-9 flex items-center justify-center gap-3"
          >
            <Link
              href="/signup"
              className="inline-flex items-center gap-2 rounded-full bg-foreground text-background px-6 py-2.5 text-sm font-medium hover:opacity-90 transition-opacity"
            >
              Get started
              <ArrowRight className="size-3.5 opacity-60" />
            </Link>
            <Link
              href="https://github.com/lucasastorian/llmwiki"
              className="inline-flex items-center gap-2 rounded-full border border-border px-6 py-2.5 text-sm font-medium hover:bg-accent transition-colors"
            >
              GitHub
            </Link>
          </MotionDiv>
        </div>
      </section>

      <section className="px-6 lg:px-10 pb-28">
        <MotionDiv
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.9, delay: 0.4, ease }}
          className="max-w-5xl mx-auto"
        >
          <div className="bg-card rounded-2xl border border-border shadow-lg overflow-hidden">
            <div className="flex items-center gap-2 px-4 py-3 border-b border-border bg-muted/30">
              <div className="flex gap-1.5">
                <div className="size-2.5 rounded-full bg-border" />
                <div className="size-2.5 rounded-full bg-border" />
                <div className="size-2.5 rounded-full bg-border" />
              </div>
              <div className="flex-1 flex justify-center">
                <span className="text-xs text-muted-foreground/50 font-mono">
                  llmwiki.app
                </span>
              </div>
              <div className="w-14" />
            </div>

            <div className="flex min-h-[400px]">
              <div className="w-52 shrink-0 border-r border-border p-3 hidden sm:block">
                <div className="flex items-center gap-2 px-2 py-1.5 mb-2">
                  <Search className="size-3 text-muted-foreground/30" />
                  <span className="text-xs text-muted-foreground/30">Search wiki...</span>
                </div>
                <div className="space-y-0.5">
                  {WIKI_TREE.map((item, i) => (
                    <div
                      key={i}
                      className={`flex items-center gap-1.5 px-2 py-1 rounded text-xs ${
                        item.active
                          ? 'bg-accent font-medium text-foreground'
                          : 'text-muted-foreground'
                      }`}
                      style={{ paddingLeft: `${item.depth * 14 + 8}px` }}
                    >
                      {item.label === 'Recent' ? (
                        <History className="size-3 opacity-40" />
                      ) : item.folder ? (
                        <GitBranch className="size-3 opacity-40" />
                      ) : (
                        <FileText className="size-3 opacity-40" />
                      )}
                      {item.label}
                    </div>
                  ))}
                </div>
              </div>

              <div className="flex-1 p-8 sm:p-10">
                <div className="max-w-xl">
                  <p className="mb-2 text-[9px] font-semibold uppercase tracking-[0.1em] text-muted-foreground/50">
                    Transformer research
                  </p>
                  <h2 className="text-xl font-semibold tracking-tight">Recent changes</h2>
                  <p className="mt-1 text-xs text-muted-foreground">
                    The latest pages, edits, and sources in this wiki.
                  </p>
                  <div className="mt-9">
                    <h3 className="mb-1 text-[9px] font-semibold uppercase tracking-[0.1em] text-muted-foreground/50">
                      Today
                    </h3>
                    {RECENT_CHANGES.map((change) => (
                      <div
                        key={`${change.time}-${change.subject}`}
                        className="grid grid-cols-[2.75rem_1.5rem_minmax(0,1fr)] items-center gap-2.5 border-b border-border/70 py-3 text-xs"
                      >
                        <span className="tabular-nums text-[10px] text-muted-foreground/50">{change.time}</span>
                        <span className="grid size-6 place-items-center rounded-full bg-muted/60 text-muted-foreground">
                          <FileText className="size-3" />
                        </span>
                        <span className="min-w-0 truncate">
                          <span className="mr-1.5 text-muted-foreground">{change.verb}</span>
                          <span className="font-medium text-foreground">{change.subject}</span>
                          {change.meta && (
                            <span className="ml-2 text-[10px] text-muted-foreground/45">{change.meta}</span>
                          )}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </MotionDiv>
      </section>

      <div className="max-w-5xl mx-auto border-t border-border" />

      <section className="px-6 lg:px-10 py-24">
        <div className="max-w-5xl mx-auto">
          <MotionDiv
            initial={{ opacity: 0 }}
            whileInView={{ opacity: 1 }}
            viewport={{ once: true, margin: '-100px' }}
            transition={{ duration: 0.6 }}
            className="text-center mb-14"
          >
            <h2 className="text-2xl sm:text-3xl font-bold tracking-tight">Three layers</h2>
            <p className="mt-3 text-muted-foreground max-w-md mx-auto">
              You rarely ever write the wiki yourself &mdash; the wiki is the domain of the LLM.
            </p>
          </MotionDiv>

          <div className="grid sm:grid-cols-3 gap-6">
            {[
              {
                icon: FileText,
                title: 'Raw Sources',
                body: 'Articles, papers, notes, transcripts. Your immutable source of truth. The LLM reads from them but never modifies them.',
              },
              {
                icon: BookOpen,
                title: 'The Wiki',
                body: 'LLM-generated markdown pages with summaries, entity pages, and cross-references. The LLM owns this layer. You read it; the LLM writes it.',
              },
              {
                icon: PenTool,
                title: 'The Schema',
                body: 'A config file that tells the LLM how the wiki is structured, what conventions to follow, and what workflows to run on ingest.',
              },
            ].map((item, i) => (
              <MotionDiv
                key={item.title}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: '-50px' }}
                transition={{ duration: 0.5, delay: i * 0.1 }}
                className="bg-card rounded-xl border border-border p-6"
              >
                <item.icon className="size-5 text-muted-foreground mb-4" strokeWidth={1.5} />
                <h3 className="font-semibold text-sm mb-2">{item.title}</h3>
                <p className="text-sm text-muted-foreground leading-relaxed">{item.body}</p>
              </MotionDiv>
            ))}
          </div>
        </div>
      </section>

      <div className="max-w-5xl mx-auto border-t border-border" />

      <section className="px-6 lg:px-10 py-24">
        <div className="max-w-5xl mx-auto">
          <MotionDiv
            initial={{ opacity: 0 }}
            whileInView={{ opacity: 1 }}
            viewport={{ once: true, margin: '-100px' }}
            transition={{ duration: 0.6 }}
            className="text-center mb-14"
          >
            <h2 className="text-2xl sm:text-3xl font-bold tracking-tight">How it works</h2>
          </MotionDiv>

          <div className="grid sm:grid-cols-3 gap-10 sm:gap-8">
            {[
              {
                step: '01',
                title: 'Ingest',
                body: 'Drop a source into raw/. The LLM reads it, writes a summary, updates entity and concept pages across the wiki, and flags anything that contradicts existing knowledge. A single source might touch 10\u201315 wiki pages.',
              },
              {
                step: '02',
                title: 'Query',
                body: 'Ask complex questions against the compiled wiki. Knowledge is already synthesized \u2014 not re-derived from raw chunks each time. Good answers get filed back as new pages, so your explorations compound.',
              },
              {
                step: '03',
                title: 'Lint',
                body: 'Run health checks over the wiki. Find inconsistent data, stale claims, orphan pages, missing cross-references. The LLM suggests new questions to ask and new sources to look for.',
              },
            ].map((item, i) => (
              <MotionDiv
                key={item.step}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: '-50px' }}
                transition={{ duration: 0.5, delay: i * 0.1 }}
              >
                <span className="text-xs font-mono text-muted-foreground/40 mb-3 block">{item.step}</span>
                <h3 className="font-semibold mb-2">{item.title}</h3>
                <p className="text-sm text-muted-foreground leading-relaxed">{item.body}</p>
              </MotionDiv>
            ))}
          </div>
        </div>
      </section>

      <div className="max-w-5xl mx-auto border-t border-border" />

      <section className="px-6 lg:px-10 py-24">
        <MotionDiv
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true, margin: '-80px' }}
          transition={{ duration: 0.8 }}
          className="max-w-2xl mx-auto text-center"
        >
          <blockquote className="text-lg sm:text-xl leading-relaxed text-foreground/80 italic">
            &ldquo;The tedious part of maintaining a knowledge base is not the reading or the thinking &mdash; it&apos;s the bookkeeping. LLMs don&apos;t get bored, don&apos;t forget to update a cross-reference, and can touch 15 files in one pass.&rdquo;
          </blockquote>
          <p className="mt-5 text-sm text-muted-foreground">
            Andrej Karpathy
          </p>
        </MotionDiv>
      </section>

      <div className="max-w-5xl mx-auto border-t border-border" />

      <section className="px-6 lg:px-10 py-24">
        <MotionDiv
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-60px' }}
          transition={{ duration: 0.6 }}
          className="max-w-md mx-auto text-center"
        >
          <h2 className="text-2xl sm:text-3xl font-bold tracking-tight mb-4">Start building your wiki</h2>
          <p className="text-muted-foreground mb-8">
            An incredible product instead of a hacky collection of scripts.
          </p>
          <Link
            href="/signup"
            className="inline-flex items-center gap-2 rounded-full bg-foreground text-background px-7 py-3 text-sm font-medium hover:opacity-90 transition-opacity"
          >
            Get started free
            <ArrowRight className="size-3.5 opacity-60" />
          </Link>
        </MotionDiv>
      </section>

      <footer className="border-t border-border px-6 lg:px-10 py-6 flex items-center justify-between text-xs text-muted-foreground/50">
        <span>LLM Wiki</span>
        <div className="flex items-center gap-4">
          <Link href="/terms" className="hover:text-muted-foreground transition-colors">Terms</Link>
          <Link href="/privacy" className="hover:text-muted-foreground transition-colors">Privacy</Link>
          <Link href="/dmca" className="hover:text-muted-foreground transition-colors">DMCA</Link>
          <span>Free &amp; open source &middot; Apache 2.0</span>
        </div>
      </footer>
    </div>
  )
}
