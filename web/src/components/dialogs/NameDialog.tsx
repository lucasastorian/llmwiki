'use client'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'

interface NameDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  value: string
  onValueChange: (value: string) => void
  submitLabel: string
  busyLabel: string
  busy: boolean
  onSubmit: () => void
  placeholder?: string
  submitDisabled?: boolean
  /** Required: the opening menu has unmounted, so Radix would restore focus to <body>. */
  onCloseAutoFocus: (event: Event) => void
}

export function NameDialog({
  open,
  onOpenChange,
  title,
  value,
  onValueChange,
  submitLabel,
  busyLabel,
  busy,
  onSubmit,
  placeholder,
  submitDisabled = false,
  onCloseAutoFocus,
}: NameDialogProps) {
  const blocked = busy || submitDisabled || !value.trim()

  const handleOpenChange = (next: boolean) => {
    if (busy && !next) return
    onOpenChange(next)
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent showCloseButton={false} aria-describedby={undefined} onCloseAutoFocus={onCloseAutoFocus} aria-busy={busy}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <Input
          aria-label={title}
          disabled={busy}
          value={value}
          onChange={(event) => onValueChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !blocked) onSubmit()
          }}
          placeholder={placeholder}
          autoFocus
        />
        <DialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={onSubmit} disabled={blocked}>
            {busy ? busyLabel : submitLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
