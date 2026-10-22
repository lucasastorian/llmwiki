import { Upload as UploadIcon, BookOpen, ArrowUpRight, PlugZap } from 'lucide-react'
import { openMcpConnectionDock } from '@/components/connections/McpConnectionDock'

const isLocal = process.env.NEXT_PUBLIC_MODE === 'local'

export function WikiEmptyState({ onUpload }: { onUpload: () => void }) {
  return (
    <>
      <BookOpen className="size-10 text-muted-foreground/20" />
      <div className="text-center max-w-sm">
        <h3 className="text-base font-medium mb-1.5">No wiki yet</h3>
        <p className="text-sm text-muted-foreground leading-relaxed">
          Connect an AI to create the first pages, or add sources for it to work from.
        </p>
      </div>
      <div className="flex items-center gap-3 mt-2">
        <button
          onClick={onUpload}
          className="inline-flex items-center gap-2 rounded-full bg-foreground text-background px-5 py-2 text-sm font-medium hover:opacity-90 transition-opacity cursor-pointer"
        >
          <UploadIcon className="size-3.5 opacity-60" />
          Upload sources
        </button>
        {isLocal ? (
          <a
            href="https://claude.ai"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 rounded-full border border-border px-5 py-2 text-sm font-medium hover:bg-accent transition-colors"
          >
            Open Claude
            <ArrowUpRight className="size-3.5 opacity-60" />
          </a>
        ) : (
          <button
            type="button"
            onClick={openMcpConnectionDock}
            className="inline-flex items-center gap-2 rounded-full border border-border px-5 py-2 text-sm font-medium hover:bg-accent transition-colors"
          >
            Connect AI
            <PlugZap className="size-3.5 text-accent-blue" />
          </button>
        )}
      </div>
    </>
  )
}
