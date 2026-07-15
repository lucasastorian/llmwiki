'use client'

import * as React from 'react'
import {
  ArrowUpRight,
  Check,
  ChevronDown,
  Copy,
  MessageSquare,
  Plug,
  Sparkles,
  TerminalSquare,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  buildCodexMcpConfig,
  buildStarterPrompt,
  MCP_URL,
} from '@/lib/mcp'

export type McpClient = 'claude' | 'chatgpt' | 'codex' | 'other'

type ClientDefinition = {
  id: McpClient
  name: string
  shortDescription: string
  note?: string
  icon: React.ComponentType<{ className?: string }>
  steps: string[]
  configLabel: string
  configValue: string
  openLabel?: string
  openHref?: string
}

const CLIENTS: ClientDefinition[] = [
  {
    id: 'claude',
    name: 'Claude',
    shortDescription: 'The simplest way to build and maintain your LLM Wiki.',
    icon: Sparkles,
    steps: [
      'Open Settings, then Connectors, and select Add custom connector.',
      'Name it LLM Wiki and paste the connection URL.',
      'Add the connector, then select Connect to sign in.',
    ],
    configLabel: 'Connection URL',
    configValue: MCP_URL,
    openLabel: 'Copy URL and open Claude',
    openHref: 'https://claude.ai/new#settings/customize-connectors',
  },
  {
    id: 'chatgpt',
    name: 'ChatGPT',
    shortDescription: 'Connect through a custom MCP app in Developer Mode.',
    note: 'Wiki editing requires full MCP support, currently in beta on ChatGPT Business, Enterprise, and Edu on the web. Admin setup may be required.',
    icon: MessageSquare,
    steps: [
      'Open Settings, then Apps and Advanced Settings, and enable Developer Mode.',
      'Select Create app, paste the connection URL, and scan tools.',
      'Complete sign-in, then create the app.',
    ],
    configLabel: 'Connection URL',
    configValue: MCP_URL,
    openLabel: 'Copy URL and open ChatGPT',
    openHref: 'https://chatgpt.com/',
  },
  {
    id: 'codex',
    name: 'Codex',
    shortDescription: 'Connect from Codex desktop, the CLI, or the IDE extension.',
    icon: TerminalSquare,
    steps: [
      'Open Settings, then MCP servers, and select Add server.',
      'Choose Streamable HTTP and enter the LLM Wiki URL.',
      'Save, restart Codex, then authenticate when prompted.',
    ],
    configLabel: 'Codex config.toml',
    configValue: buildCodexMcpConfig(),
    openLabel: 'Copy config and open Codex guide',
    openHref: 'https://developers.openai.com/codex/mcp',
  },
  {
    id: 'other',
    name: 'Other',
    shortDescription: 'Use a client that supports remote Streamable HTTP servers and OAuth. Setup varies by client.',
    icon: Plug,
    steps: [
      'Open your client’s MCP settings.',
      'Add a Streamable HTTP server using the connection URL.',
      'Complete OAuth sign-in when your client prompts you.',
    ],
    configLabel: 'Connection URL',
    configValue: MCP_URL,
  },
]

async function writeClipboard(value: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    try {
      await new Promise<void>((resolve, reject) => {
        const timeout = window.setTimeout(() => reject(new Error('Clipboard timed out')), 1500)
        navigator.clipboard.writeText(value).then(
          () => {
            window.clearTimeout(timeout)
            resolve()
          },
          (error) => {
            window.clearTimeout(timeout)
            reject(error)
          },
        )
      })
      return
    } catch {
      // Fall through to the selection-based copy path.
    }
  }

  const textarea = document.createElement('textarea')
  textarea.value = value
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  const copied = document.execCommand('copy')
  textarea.remove()
  if (!copied) throw new Error('Clipboard unavailable')
}

function CopyBlock({
  label,
  value,
  copied,
  onCopy,
}: {
  label: string
  value: string
  copied: boolean
  onCopy: () => void
}) {
  const multiline = value.includes('\n') || value.length > 120
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between gap-3">
        <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground/60">
          {label}
        </p>
        <button
          type="button"
          onClick={onCopy}
          className="inline-flex h-6 items-center gap-1.5 rounded-md px-2 -mr-2 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      {multiline ? (
        <pre className="max-h-40 select-all overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border/60 bg-muted/40 p-3 text-xs leading-relaxed text-foreground">
          {value}
        </pre>
      ) : (
        <code
          className="block min-w-0 select-all overflow-x-auto whitespace-nowrap rounded-lg border border-border/60 bg-muted/40 px-3 py-2.5 text-xs text-foreground"
          title={value}
        >
          {value}
        </code>
      )}
    </div>
  )
}

export function McpConnectionSetup({
  defaultClient = 'claude',
  wikiName,
  className,
  showClientHeading = true,
  showStarterPrompt = true,
  onClientChange,
}: {
  defaultClient?: McpClient
  wikiName?: string
  className?: string
  showClientHeading?: boolean
  showStarterPrompt?: boolean
  onClientChange?: (client: McpClient) => void
}) {
  const [activeClient, setActiveClient] = React.useState<McpClient>(defaultClient)
  const [showOptions, setShowOptions] = React.useState(defaultClient !== 'claude')
  const [copiedKey, setCopiedKey] = React.useState<'config' | 'prompt' | null>(null)
  const [copyError, setCopyError] = React.useState<string | null>(null)
  const timerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null)

  React.useEffect(() => () => {
    if (timerRef.current) clearTimeout(timerRef.current)
  }, [])

  const client = CLIENTS.find((item) => item.id === activeClient) ?? CLIENTS[0]
  const starterPrompt = buildStarterPrompt(wikiName)

  const copyText = React.useCallback(async (value: string, key: 'config' | 'prompt') => {
    setCopyError(null)
    try {
      await writeClipboard(value)
      setCopiedKey(key)
      if (timerRef.current) clearTimeout(timerRef.current)
      timerRef.current = setTimeout(() => setCopiedKey(null), 2000)
      return true
    } catch {
      setCopyError('Could not copy automatically. Select the text and copy it manually.')
      return false
    }
  }, [])

  return (
    <div className={cn('min-w-0', className)}>
      <section>
        {showClientHeading && (
          <div className="pb-5">
            <div className="flex items-start gap-3">
              <client.icon className="mt-0.5 size-4 shrink-0 text-accent-blue" />
              <div className="min-w-0">
                <h3 className="text-sm font-semibold text-foreground">Connect {client.name}</h3>
                <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                  {client.shortDescription}
                </p>
                {client.note && (
                  <p className="mt-2 text-xs leading-relaxed text-muted-foreground/70">
                    {client.note}
                  </p>
                )}
              </div>
            </div>
          </div>
        )}

        <div className="space-y-5">
          <CopyBlock
            label={client.configLabel}
            value={client.configValue}
            copied={copiedKey === 'config'}
            onCopy={() => void copyText(client.configValue, 'config')}
          />

          <ol className="space-y-2" aria-label={`${client.name} setup steps`}>
            {client.steps.map((step, index) => (
              <li key={step} className="flex gap-2.5 text-sm leading-relaxed text-foreground/80">
                <span className="mt-[3px] flex size-4 shrink-0 items-center justify-center rounded-full bg-muted text-[10px] font-semibold text-muted-foreground">
                  {index + 1}
                </span>
                <span>{step}</span>
              </li>
            ))}
          </ol>

          {client.openHref && client.openLabel && (
            <Button asChild variant="outline" className="w-full">
              <a
                href={client.openHref}
                target="_blank"
                rel="noopener noreferrer"
                onClick={() => void copyText(client.configValue, 'config')}
              >
                {client.openLabel}
                <ArrowUpRight className="size-3.5" />
              </a>
            </Button>
          )}

          {copyError && (
            <p aria-live="polite" className="text-xs text-destructive">
              {copyError}
            </p>
          )}

          <div className="border-t border-border/60 pt-2.5">
            <button
              type="button"
              aria-expanded={showOptions}
              onClick={() => setShowOptions((value) => !value)}
              className="flex min-h-8 w-full items-center justify-between text-xs font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              Use a different client
              <ChevronDown className={cn('size-3.5 transition-transform duration-200', showOptions && 'rotate-180')} />
            </button>

            {showOptions && (
              <div
                role="group"
                aria-label="Choose an AI client"
                className="mt-2 grid grid-cols-2 gap-1 rounded-lg bg-muted/50 p-1 sm:grid-cols-4"
              >
                {CLIENTS.map((item) => {
                  const Icon = item.icon
                  const selected = item.id === client.id
                  return (
                    <button
                      key={item.id}
                      type="button"
                      data-mcp-client={item.id}
                      aria-pressed={selected}
                      onClick={() => {
                        if (timerRef.current) clearTimeout(timerRef.current)
                        setActiveClient(item.id)
                        onClientChange?.(item.id)
                        setCopiedKey(null)
                        setCopyError(null)
                      }}
                      className={cn(
                        'flex min-h-10 items-center justify-center gap-2 rounded-md px-2.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                        selected
                          ? 'bg-background text-foreground shadow-sm'
                          : 'text-muted-foreground hover:bg-background/60 hover:text-foreground',
                      )}
                    >
                      <Icon className="size-3.5" />
                      {item.name}
                    </button>
                  )
                })}
              </div>
            )}
          </div>

          {showStarterPrompt && (
            <details className="group border-t border-border/60 pt-2.5 !mt-3">
              <summary className="flex min-h-8 cursor-pointer list-none items-center justify-between text-xs font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
                First prompt to send
                <ChevronDown className="size-3.5 transition-transform duration-200 group-open:rotate-180" />
              </summary>
              <div className="pb-1 pt-2">
                <CopyBlock
                  label="Starter prompt"
                  value={starterPrompt}
                  copied={copiedKey === 'prompt'}
                  onCopy={() => void copyText(starterPrompt, 'prompt')}
                />
              </div>
            </details>
          )}
        </div>
      </section>
    </div>
  )
}
