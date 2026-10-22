'use client'

import * as React from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'

interface ConfirmDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description: React.ReactNode
  confirmLabel: string
  busyLabel: string
  busy: boolean
  onConfirm: () => void
  destructive?: boolean
  confirmText?: string
  /** Required: the opening menu has unmounted, so Radix would restore focus to <body>. */
  onCloseAutoFocus: (event: Event) => void
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  busyLabel,
  busy,
  onConfirm,
  destructive = false,
  confirmText,
  onCloseAutoFocus,
}: ConfirmDialogProps) {
  const [typed, setTyped] = React.useState('')
  const confirmBlocked = confirmText != null && typed !== confirmText

  React.useEffect(() => {
    if (!open) setTyped('')
  }, [open])

  const handleOpenChange = (next: boolean) => {
    if (busy && !next) return
    onOpenChange(next)
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent showCloseButton={false} onCloseAutoFocus={onCloseAutoFocus} aria-busy={busy}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        {confirmText != null && (
          <div className="grid gap-1.5">
            <label htmlFor="confirm-dialog-text" className="text-xs text-muted-foreground">
              Type <span className="font-medium text-foreground">{confirmText}</span> to confirm
            </label>
            <Input
              id="confirm-dialog-text"
              disabled={busy}
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !confirmBlocked && !busy) onConfirm()
              }}
              autoFocus
              autoComplete="off"
              spellCheck={false}
            />
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant={destructive ? 'destructive' : 'default'}
            onClick={onConfirm}
            disabled={busy || confirmBlocked}
          >
            {busy ? busyLabel : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
