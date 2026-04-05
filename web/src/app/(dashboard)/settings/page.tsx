'use client'

import * as React from 'react'
import { Copy, Check, Key, Plus, Trash2, Loader2, ArrowLeft } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { cn } from '@/lib/utils'
import { apiFetch } from '@/lib/api'
import { buildApiKeyMcpConfig, buildOAuthMcpConfig, MCP_URL } from '@/lib/mcp'
import { useUserStore } from '@/stores'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from '@/components/ui/dialog'

interface APIKey {
  id: string
  name: string | null
  key_prefix: string
  created_at: string
  last_used_at: string | null
}

interface Usage {
  total_pages: number
  total_storage_bytes: number
  document_count: number
  max_pages: number
  max_storage_bytes: number
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  const value = bytes / Math.pow(1024, i)
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[i]}`
}

function relativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return 'Just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  const months = Math.floor(days / 30)
  if (months < 12) return `${months}mo ago`
  return `${Math.floor(months / 12)}y ago`
}

export default function SettingsPage() {
  const router = useRouter()
  const token = useUserStore((s) => s.accessToken)
  const [keys, setKeys] = React.useState<APIKey[]>([])
  const [usage, setUsage] = React.useState<Usage | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [generating, setGenerating] = React.useState(false)
  const [newKey, setNewKey] = React.useState<string | null>(null)
  const [copied, setCopied] = React.useState(false)
  const [configCopied, setConfigCopied] = React.useState(false)
  const [revoking, setRevoking] = React.useState<string | null>(null)

  const oauthConfigJson = buildOAuthMcpConfig()
  const apiKeyConfigJson = newKey ? buildApiKeyMcpConfig(newKey) : null

  React.useEffect(() => {
    if (!token) return
    Promise.all([
      apiFetch<APIKey[]>('/v1/api-keys', token).catch(() => [] as APIKey[]),
      apiFetch<Usage>('/v1/usage', token).catch(() => null),
    ]).then(([fetchedKeys, fetchedUsage]) => {
      setKeys(fetchedKeys)
      if (fetchedUsage) setUsage(fetchedUsage)
    }).finally(() => setLoading(false))
  }, [token])

  const handleGenerate = async () => {
    if (!token) return
    setGenerating(true)
    try {
      const result = await apiFetch<APIKey & { key: string }>('/v1/api-keys', token, {
        method: 'POST',
        body: JSON.stringify({ name: 'Default' }),
      })
      setNewKey(result.key)
      setKeys((prev) => [{ id: result.id, name: result.name, key_prefix: result.key_prefix, created_at: result.created_at, last_used_at: null }, ...prev])
    } catch (err) {
      console.error('Failed to generate key:', err)
    } finally {
      setGenerating(false)
    }
  }

  const handleRevoke = async (keyId: string) => {
    if (!token) return
    setRevoking(keyId)
    try {
      await apiFetch(`/v1/api-keys/${keyId}`, token, { method: 'DELETE' })
      setKeys((prev) => prev.filter((k) => k.id !== keyId))
    } catch (err) {
      console.error('Failed to revoke key:', err)
    } finally {
      setRevoking(null)
    }
  }

  const handleCopyConfig = async () => {
    try {
      await navigator.clipboard.writeText(oauthConfigJson)
      setConfigCopied(true)
      setTimeout(() => setConfigCopied(false), 2000)
    } catch {
      console.error('Failed to copy')
    }
  }

  const handleCopyKey = async () => {
    if (!newKey) return
    try {
      await navigator.clipboard.writeText(newKey)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      console.error('Failed to copy')
    }
  }

  return (
    <div className="max-w-2xl mx-auto p-8">
      <div className="flex items-center gap-3 mb-8">
        <button
          onClick={() => router.back()}
          className="p-1 rounded-md hover:bg-accent transition-colors cursor-pointer text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
        </button>
        <h1 className="text-xl font-semibold tracking-tight">Settings</h1>
      </div>

      {/* Usage */}
      {usage && (
        <section>
          <h2 className="text-base font-medium">Usage</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {usage.document_count} document{usage.document_count !== 1 ? 's' : ''} uploaded
          </p>
          <div className="mt-4 space-y-4">
            <div>
              <div className="flex items-center justify-between text-sm mb-1.5">
                <span className="text-muted-foreground">Storage</span>
                <span className="font-mono text-xs">
                  {formatBytes(usage.total_storage_bytes)} / {formatBytes(usage.max_storage_bytes)}
                </span>
              </div>
              <div className="h-2 rounded-full bg-muted overflow-hidden">
                <div
                  className={cn(
                    'h-full rounded-full transition-all',
                    usage.total_storage_bytes / usage.max_storage_bytes > 0.9
                      ? 'bg-destructive'
                      : usage.total_storage_bytes / usage.max_storage_bytes > 0.7
                        ? 'bg-yellow-500'
                        : 'bg-primary'
                  )}
                  style={{ width: `${Math.min(100, (usage.total_storage_bytes / usage.max_storage_bytes) * 100)}%` }}
                />
              </div>
            </div>
            <div>
              <div className="flex items-center justify-between text-sm mb-1.5">
                <span className="text-muted-foreground">OCR Pages</span>
                <span className="font-mono text-xs">
                  {usage.total_pages.toLocaleString()} / {usage.max_pages.toLocaleString()}
                </span>
              </div>
              <div className="h-2 rounded-full bg-muted overflow-hidden">
                <div
                  className={cn(
                    'h-full rounded-full transition-all',
                    usage.total_pages / usage.max_pages > 0.9
                      ? 'bg-destructive'
                      : usage.total_pages / usage.max_pages > 0.7
                        ? 'bg-yellow-500'
                        : 'bg-primary'
                  )}
                  style={{ width: `${Math.min(100, (usage.total_pages / usage.max_pages) * 100)}%` }}
                />
              </div>
            </div>
          </div>
        </section>
      )}

      {usage && <div className="h-px bg-border my-8" />}

      {/* MCP Config */}
      <section>
        <h2 className="text-base font-medium">Connect via OAuth</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Add this configuration to your MCP client. On first connection, it should prompt you to sign in with Supabase.
        </p>
        <div className="relative mt-4">
          <pre className="rounded-lg bg-muted border border-border p-4 text-sm font-mono overflow-x-auto text-foreground">
            {oauthConfigJson}
          </pre>
          <button
            onClick={handleCopyConfig}
            className={cn(
              'absolute top-3 right-3 flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs transition-colors cursor-pointer',
              configCopied
                ? 'bg-green-500/10 text-green-600 dark:text-green-400'
                : 'bg-background border border-border text-muted-foreground hover:text-foreground hover:bg-accent'
            )}
          >
            {configCopied ? <><Check size={12} />Copied</> : <><Copy size={12} />Copy</>}
          </button>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          MCP URL:
          {' '}
          <code className="text-xs bg-muted px-1.5 py-0.5 rounded font-mono">{MCP_URL}</code>
        </p>
        <p className="mt-2 text-xs text-muted-foreground">
          If your client cannot complete OAuth yet, you can still use a static API key from the section below.
        </p>
      </section>

      <div className="h-px bg-border my-8" />

      {/* API Keys */}
      <section>
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-medium">API Keys</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Optional fallback for clients that require a static bearer token.
            </p>
          </div>
          <button
            onClick={handleGenerate}
            disabled={generating}
            className="flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors cursor-pointer disabled:opacity-50"
          >
            {generating ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
            Generate Key
          </button>
        </div>

        <div className="mt-6">
          {loading ? (
            <div className="flex items-center justify-center py-10">
              <Loader2 className="size-5 animate-spin text-muted-foreground" />
            </div>
          ) : keys.length === 0 ? (
            <div className="rounded-lg border border-border flex items-center justify-center py-10 text-muted-foreground">
              <div className="text-center">
                <Key size={24} className="mx-auto mb-2 text-muted-foreground/50" />
                <p className="text-sm">No API keys yet</p>
                <p className="text-xs text-muted-foreground/60 mt-1">Generate a key to get started</p>
              </div>
            </div>
          ) : (
            <div className="rounded-lg border border-border divide-y divide-border">
              {keys.map((k) => (
                <div key={k.id} className="flex items-center gap-3 px-4 py-3">
                  <Key size={14} className="text-muted-foreground/50 shrink-0" />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <code className="text-sm font-mono text-foreground">{k.key_prefix}...</code>
                      {k.name && <span className="text-xs text-muted-foreground">{k.name}</span>}
                    </div>
                    <div className="text-[11px] text-muted-foreground/50 mt-0.5">
                      Created {relativeTime(k.created_at)}
                      {k.last_used_at && <> · Last used {relativeTime(k.last_used_at)}</>}
                    </div>
                  </div>
                  <button
                    onClick={() => handleRevoke(k.id)}
                    disabled={revoking === k.id}
                    className="p-1.5 rounded-md text-muted-foreground/40 hover:text-destructive hover:bg-destructive/10 transition-colors cursor-pointer disabled:opacity-50"
                    title="Revoke key"
                  >
                    {revoking === k.id ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* New key dialog */}
      <Dialog open={!!newKey} onOpenChange={(open) => { if (!open) setNewKey(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>API Key Generated</DialogTitle>
            <DialogDescription>
              Copy this key now — you won't be able to see it again. Use it only if your client cannot complete OAuth.
            </DialogDescription>
          </DialogHeader>
          <div className="flex items-center gap-2">
            <code className="flex-1 text-sm font-mono bg-muted rounded-md px-3 py-2 break-all select-all">
              {newKey}
            </code>
            <button
              onClick={handleCopyKey}
              className={cn(
                'shrink-0 p-2 rounded-md transition-colors cursor-pointer',
                copied
                  ? 'bg-green-500/10 text-green-600 dark:text-green-400'
                  : 'bg-muted text-muted-foreground hover:text-foreground'
              )}
            >
              {copied ? <Check size={14} /> : <Copy size={14} />}
            </button>
          </div>
          {apiKeyConfigJson && (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">Manual bearer-token config:</p>
              <pre className="rounded-lg bg-muted border border-border p-3 text-xs font-mono overflow-x-auto text-foreground">
                {apiKeyConfigJson}
              </pre>
            </div>
          )}
          <DialogFooter>
            <button
              onClick={() => setNewKey(null)}
              className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 cursor-pointer"
            >
              Done
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
