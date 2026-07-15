'use client'

import * as React from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { AlertCircle, CheckCircle2, ChevronDown, FileText, Loader2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useUploadStore, type UploadItem } from '@/stores'
import { cn } from '@/lib/utils'

export function UploadProgressPanel({ raisedForConnectionDock = false }: { raisedForConnectionDock?: boolean }) {
  const router = useRouter()
  const pathname = usePathname()
  const items = useUploadStore((s) => s.items)
  const dismiss = useUploadStore((s) => s.dismiss)
  const clearFinished = useUploadStore((s) => s.clearFinished)
  const requestOpenDocument = useUploadStore((s) => s.requestOpenDocument)
  const [collapsed, setCollapsed] = React.useState(false)

  const inFlight = items.filter((item) => item.phase === 'uploading' || item.phase === 'processing').length

  const handleView = React.useCallback((item: UploadItem) => {
    if (item.documentNumber == null) return
    requestOpenDocument(item.kbId, item.documentNumber)
    const base = `/wikis/${item.kbSlug}`
    const onTargetWiki = pathname === base || pathname.startsWith(`${base}/`)
    if (!onTargetWiki) router.push(`${base}/files`)
  }, [pathname, requestOpenDocument, router])

  if (items.length === 0) return null

  return (
    <div
      style={{
        bottom: raisedForConnectionDock
          ? 'calc(max(1rem, env(safe-area-inset-bottom)) + 3rem)'
          : 'max(1rem, env(safe-area-inset-bottom))',
        right: 'max(1rem, env(safe-area-inset-right))',
      }}
      className={cn(
        'fixed z-50 w-[min(20rem,calc(100vw-2rem))] overflow-hidden rounded-lg border bg-background shadow-lg transition-[bottom] duration-200',
      )}
    >
      <div className="flex items-center justify-between border-b px-3 py-2">
        <span className="text-sm font-medium">{headerLabel(inFlight, items.length)}</span>
        <div className="flex items-center gap-0.5">
          <Button
            variant="ghost"
            size="icon"
            className="size-6 text-muted-foreground"
            onClick={() => setCollapsed((v) => !v)}
            aria-label={collapsed ? 'Expand' : 'Collapse'}
          >
            <ChevronDown className={`size-4 transition-transform ${collapsed ? '-rotate-180' : ''}`} />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="size-6 text-muted-foreground"
            onClick={clearFinished}
            disabled={inFlight === items.length}
            aria-label="Clear completed"
          >
            <X className="size-4" />
          </Button>
        </div>
      </div>

      {!collapsed && (
        <ul className="max-h-72 divide-y overflow-y-auto">
          {items.map((item) => (
            <UploadRow key={item.id} item={item} onView={handleView} onDismiss={dismiss} />
          ))}
        </ul>
      )}
    </div>
  )
}

function headerLabel(inFlight: number, total: number): string {
  if (inFlight > 0) return `Uploading ${inFlight} item${inFlight > 1 ? 's' : ''}`
  return `${total} upload${total > 1 ? 's' : ''} complete`
}

function UploadRow({
  item,
  onView,
  onDismiss,
}: {
  item: UploadItem
  onView: (item: UploadItem) => void
  onDismiss: (id: string) => void
}) {
  return (
    <li className="flex items-center gap-3 px-3 py-2.5">
      <StatusIcon phase={item.phase} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm" title={item.filename}>
          {item.filename}
        </p>
        <RowStatus item={item} />
      </div>
      <RowAction item={item} onView={onView} onDismiss={onDismiss} />
    </li>
  )
}

function StatusIcon({ phase }: { phase: UploadItem['phase'] }) {
  if (phase === 'ready') return <CheckCircle2 className="size-4 shrink-0 text-emerald-600" />
  if (phase === 'failed') return <AlertCircle className="size-4 shrink-0 text-destructive" />
  if (phase === 'processing') return <Loader2 className="size-4 shrink-0 animate-spin text-muted-foreground" />
  return <FileText className="size-4 shrink-0 text-muted-foreground" />
}

function RowStatus({ item }: { item: UploadItem }) {
  if (item.phase === 'uploading') {
    const pct = Math.round(item.progress * 100)
    return (
      <div className="mt-1.5 flex items-center gap-2">
        <div className="h-1 flex-1 overflow-hidden rounded-full bg-muted">
          <div className="h-full rounded-full bg-foreground transition-[width] duration-150" style={{ width: `${pct}%` }} />
        </div>
        <span className="text-xs tabular-nums text-muted-foreground">{pct}%</span>
      </div>
    )
  }
  const label =
    item.phase === 'processing'
      ? 'Processing…'
      : item.phase === 'ready'
        ? 'Done'
        : item.error || 'Upload failed'
  return <p className="mt-0.5 truncate text-xs text-muted-foreground">{label}</p>
}

function RowAction({
  item,
  onView,
  onDismiss,
}: {
  item: UploadItem
  onView: (item: UploadItem) => void
  onDismiss: (id: string) => void
}) {
  if (item.phase === 'ready') {
    return (
      <Button variant="ghost" size="sm" className="h-7 shrink-0 cursor-pointer px-2 text-xs" onClick={() => onView(item)}>
        View
      </Button>
    )
  }
  if (item.phase === 'failed') {
    return (
      <Button
        variant="ghost"
        size="icon"
        className="size-6 shrink-0 text-muted-foreground"
        onClick={() => onDismiss(item.id)}
        aria-label="Dismiss"
      >
        <X className="size-4" />
      </Button>
    )
  }
  return null
}
