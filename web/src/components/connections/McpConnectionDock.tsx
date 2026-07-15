'use client'

import * as React from 'react'
import { PlugZap } from 'lucide-react'
import { McpConnectionSetup } from '@/components/connections/McpConnectionSetup'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'

const isLocal = process.env.NEXT_PUBLIC_MODE === 'local'
export const OPEN_MCP_CONNECTIONS_EVENT = 'llmwiki:open-mcp-connections'

export function openMcpConnectionDock() {
  window.dispatchEvent(new Event(OPEN_MCP_CONNECTIONS_EVENT))
}

export function McpConnectionDock({ wikiName }: { wikiName?: string }) {
  const [open, setOpen] = React.useState(false)

  React.useEffect(() => {
    const handleOpen = () => setOpen(true)
    window.addEventListener(OPEN_MCP_CONNECTIONS_EVENT, handleOpen)
    return () => window.removeEventListener(OPEN_MCP_CONNECTIONS_EVENT, handleOpen)
  }, [])

  if (isLocal) return null

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <button
          type="button"
          data-testid="mcp-connection-dock-trigger"
          aria-label="Connect Claude or another AI client"
          style={{
            bottom: 'max(1rem, env(safe-area-inset-bottom))',
            right: 'max(1rem, env(safe-area-inset-right))',
          }}
          className="fixed z-30 inline-flex min-h-11 items-center gap-2 rounded-full border border-accent-blue/25 bg-background px-3.5 text-xs font-medium text-foreground shadow-lg transition-colors hover:border-accent-blue/45 hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-blue/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        >
          <span className="relative flex size-5 items-center justify-center">
            <PlugZap className="size-4 text-accent-blue" />
            <span className="absolute -right-0.5 -top-0.5 size-1.5 rounded-full bg-accent-blue" aria-hidden />
          </span>
          <span className="hidden sm:inline">Connect AI</span>
        </button>
      </SheetTrigger>
      <SheetContent className="w-[calc(100%-1rem)] max-w-[30rem] gap-0 overflow-y-auto data-[state=closed]:duration-150 data-[state=open]:duration-200 sm:max-w-[30rem]">
        <SheetHeader className="border-b border-border px-5 py-4 pr-12">
          <SheetTitle>Connect AI</SheetTitle>
          <SheetDescription>
            Link an AI client to read and write this wiki.
          </SheetDescription>
        </SheetHeader>
        <div className="px-5 py-4">
          <McpConnectionSetup wikiName={wikiName} />
        </div>
      </SheetContent>
    </Sheet>
  )
}
