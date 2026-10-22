'use client'

import * as React from 'react'
import { useRouter } from 'next/navigation'
import { Check, ChevronDown, Plus, Pencil, Trash2, Library, GraduationCap, BookOpen } from 'lucide-react'
import { toast } from 'sonner'
import { Popover, PopoverTrigger, PopoverContent } from '@/components/ui/popover'
import { Command, CommandInput, CommandList, CommandItem, CommandEmpty, CommandGroup, CommandSeparator } from '@/components/ui/command'
import { ConfirmDialog } from '@/components/dialogs/ConfirmDialog'
import { NameDialog } from '@/components/dialogs/NameDialog'
import { useKBStore } from '@/stores'

const isLocal = process.env.NEXT_PUBLIC_MODE === 'local'

export function WikiSelector({ kbName, kbId }: { kbName: string; kbId: string }) {
  const router = useRouter()
  const knowledgeBases = useKBStore((s) => s.knowledgeBases)
  const createKB = useKBStore((s) => s.createKB)
  const renameKB = useKBStore((s) => s.renameKB)
  const deleteKB = useKBStore((s) => s.deleteKB)
  const setKBKind = useKBStore((s) => s.setKBKind)
  const isCourse = knowledgeBases.find((kb) => kb.id === kbId)?.kind === 'course'
  const [open, setOpen] = React.useState(false)
  const [search, setSearch] = React.useState('')
  const [createDialogOpen, setCreateDialogOpen] = React.useState(false)
  const [renameDialogOpen, setRenameDialogOpen] = React.useState(false)
  const [convertDialogOpen, setConvertDialogOpen] = React.useState(false)
  const [deleteDialogOpen, setDeleteDialogOpen] = React.useState(false)
  const [newName, setNewName] = React.useState('')
  const [renameName, setRenameName] = React.useState('')
  const [creating, setCreating] = React.useState(false)
  const [renaming, setRenaming] = React.useState(false)
  const [converting, setConverting] = React.useState(false)
  const [deleting, setDeleting] = React.useState(false)
  const triggerRef = React.useRef<HTMLButtonElement>(null)

  // The popover unmounts before the dialog opens, so Radix would restore focus to <body>.
  const restoreFocusToTrigger = React.useCallback((event: Event) => {
    event.preventDefault()
    triggerRef.current?.focus()
  }, [])

  const handleCreate = async () => {
    if (!newName.trim()) return
    setCreating(true)
    try {
      const kb = await createKB(newName.trim())
      setCreateDialogOpen(false)
      setNewName('')
      router.push(`/wikis/${kb.slug}`)
    } catch {
      toast.error('Failed to create wiki')
    } finally {
      setCreating(false)
    }
  }

  const handleRename = async () => {
    if (!renameName.trim() || renameName.trim() === kbName) return
    setRenaming(true)
    try {
      await renameKB(kbId, renameName.trim())
      setRenameDialogOpen(false)
      const updated = useKBStore.getState().knowledgeBases.find((kb) => kb.id === kbId)
      if (updated) router.replace(`/wikis/${updated.slug}`)
    } catch {
      toast.error('Failed to rename wiki')
    } finally {
      setRenaming(false)
    }
  }

  const handleConvert = async () => {
    setConverting(true)
    try {
      await setKBKind(kbId, isCourse ? 'wiki' : 'course')
      setConvertDialogOpen(false)
    } catch {
      toast.error(isCourse ? 'Failed to convert to wiki' : 'Failed to convert to course')
    } finally {
      setConverting(false)
    }
  }

  const handleDelete = async () => {
    setDeleting(true)
    try {
      await deleteKB(kbId)
      setDeleteDialogOpen(false)
      router.push('/wikis')
    } catch {
      toast.error('Failed to delete wiki')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <>
      <Popover open={open} onOpenChange={(v) => { setOpen(v); if (!v) setSearch('') }}>
        <PopoverTrigger asChild>
          <button
            ref={triggerRef}
            role="combobox"
            aria-expanded={open}
            aria-label="Switch wiki"
            className="flex items-center gap-1.5 w-full px-2 py-1.5 text-sm font-semibold text-foreground hover:bg-sidebar-accent rounded-md transition-colors cursor-pointer"
          >
            <span className="truncate flex-1 text-left">{kbName}</span>
            <ChevronDown className="size-3.5 text-muted-foreground/40 shrink-0" />
          </button>
        </PopoverTrigger>
        <PopoverContent className="w-[var(--radix-popover-trigger-width)] p-0" align="start">
          <Command>
            <CommandInput placeholder="Search wikis..." aria-label="Search wikis" value={search} onValueChange={setSearch} />
            <CommandList className="max-h-[min(60vh,26rem)]">
              <CommandEmpty>No wikis found.</CommandEmpty>
              <CommandGroup heading="Wikis">
                {knowledgeBases.map((kb) => (
                  <CommandItem
                    key={kb.id}
                    value={kb.name}
                    onSelect={() => {
                      setOpen(false)
                      router.push(`/wikis/${kb.slug}`)
                    }}
                  >
                    <span className="truncate flex-1">{kb.name}</span>
                    {kb.id === kbId && <Check className="size-3.5 shrink-0 text-muted-foreground" />}
                  </CommandItem>
                ))}
              </CommandGroup>
              {!search.trim() && (
                <>
                  <CommandSeparator />
                  <CommandGroup heading="Actions">
                    <CommandItem
                      onSelect={() => {
                        setOpen(false)
                        router.push('/wikis')
                      }}
                    >
                      <Library className="size-3.5 mr-2" />
                      View all wikis
                    </CommandItem>
                    <CommandItem
                      onSelect={() => {
                        setOpen(false)
                        setRenameName(kbName)
                        setRenameDialogOpen(true)
                      }}
                    >
                      <Pencil className="size-3.5 mr-2" />
                      Rename
                    </CommandItem>
                    <CommandItem
                      onSelect={() => {
                        setOpen(false)
                        setConvertDialogOpen(true)
                      }}
                    >
                      {isCourse
                        ? <BookOpen className="size-3.5 mr-2" />
                        : <GraduationCap className="size-3.5 mr-2" />}
                      {isCourse ? 'Convert to wiki' : 'Convert to course'}
                    </CommandItem>
                    {!isLocal && (
                      <>
                        <CommandItem
                          onSelect={() => {
                            setOpen(false)
                            setDeleteDialogOpen(true)
                          }}
                          className="text-destructive"
                        >
                          <Trash2 className="size-3.5 mr-2" />
                          Delete
                        </CommandItem>
                        <CommandSeparator />
                        <CommandItem
                          onSelect={() => {
                            setOpen(false)
                            setCreateDialogOpen(true)
                          }}
                        >
                          <Plus className="size-3.5 mr-2" />
                          Create wiki
                        </CommandItem>
                      </>
                    )}
                  </CommandGroup>
                </>
              )}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>

      {!isLocal && (
        <NameDialog
          open={createDialogOpen}
          onOpenChange={setCreateDialogOpen}
          title="Create wiki"
          value={newName}
          onValueChange={setNewName}
          placeholder="My Research"
          submitLabel="Create"
          busyLabel="Creating..."
          busy={creating}
          onSubmit={handleCreate}
          onCloseAutoFocus={restoreFocusToTrigger}
        />
      )}

      <NameDialog
        open={renameDialogOpen}
        onOpenChange={setRenameDialogOpen}
        title="Rename wiki"
        value={renameName}
        onValueChange={setRenameName}
        submitLabel="Rename"
        busyLabel="Renaming..."
        busy={renaming}
        submitDisabled={renameName.trim() === kbName}
        onSubmit={handleRename}
        onCloseAutoFocus={restoreFocusToTrigger}
      />

      <ConfirmDialog
        open={convertDialogOpen}
        onOpenChange={setConvertDialogOpen}
        title={isCourse ? 'Convert to wiki' : 'Convert to course'}
        description={isCourse
          ? `"${kbName}" returns to a free-form wiki. Lesson progress is kept and restored if you convert back.`
          : `"${kbName}" presents its pages as ordered lessons with progress tracking and resume. You can convert back at any time.`}
        confirmLabel="Convert"
        busyLabel="Converting..."
        busy={converting}
        onConfirm={handleConvert}
        onCloseAutoFocus={restoreFocusToTrigger}
      />

      {!isLocal && (
        <ConfirmDialog
          open={deleteDialogOpen}
          onOpenChange={setDeleteDialogOpen}
          title="Delete wiki"
          description={<>This permanently deletes <strong>{kbName}</strong> and all its sources and wiki pages. This cannot be undone.</>}
          confirmLabel="Delete"
          busyLabel="Deleting..."
          busy={deleting}
          onConfirm={handleDelete}
          destructive
          confirmText={kbName}
          onCloseAutoFocus={restoreFocusToTrigger}
        />
      )}
    </>
  )
}
