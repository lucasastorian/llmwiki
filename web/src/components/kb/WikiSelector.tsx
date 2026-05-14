'use client'

import * as React from 'react'
import { useRouter } from 'next/navigation'
import { ChevronsUpDown, Plus, Pencil, Trash2 } from 'lucide-react'
import { Popover, PopoverTrigger, PopoverContent } from '@/components/ui/popover'
import { Command, CommandInput, CommandList, CommandItem, CommandEmpty, CommandGroup, CommandSeparator } from '@/components/ui/command'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { useKBStore } from '@/stores'

export function WikiSelector({ kbName, kbId }: { kbName: string; kbId: string }) {
  const router = useRouter()
  const knowledgeBases = useKBStore((s) => s.knowledgeBases)
  const createKB = useKBStore((s) => s.createKB)
  const renameKB = useKBStore((s) => s.renameKB)
  const deleteKB = useKBStore((s) => s.deleteKB)
  const [open, setOpen] = React.useState(false)
  const [search, setSearch] = React.useState('')
  const [createDialogOpen, setCreateDialogOpen] = React.useState(false)
  const [renameDialogOpen, setRenameDialogOpen] = React.useState(false)
  const [deleteDialogOpen, setDeleteDialogOpen] = React.useState(false)
  const [newName, setNewName] = React.useState('')
  const [renameName, setRenameName] = React.useState('')
  const [creating, setCreating] = React.useState(false)
  const [renaming, setRenaming] = React.useState(false)
  const [deleting, setDeleting] = React.useState(false)

  const handleCreate = async () => {
    if (!newName.trim()) return
    setCreating(true)
    try {
      const kb = await createKB(newName.trim())
      setCreateDialogOpen(false)
      setNewName('')
      router.push(`/wikis/${kb.slug}`)
    } catch {
      // error handled by store
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
      // error handled by store
    } finally {
      setRenaming(false)
    }
  }

  const handleDelete = async () => {
    setDeleting(true)
    try {
      await deleteKB(kbId)
      setDeleteDialogOpen(false)
      router.push('/wikis')
    } catch {
      // error handled by store
    } finally {
      setDeleting(false)
    }
  }

  return (
    <>
      <Popover open={open} onOpenChange={(v) => { setOpen(v); if (!v) setSearch('') }}>
        <PopoverTrigger asChild>
          <button
            role="combobox"
            aria-expanded={open}
            aria-label="Switch wiki"
            className="flex items-center gap-1.5 w-full px-2 py-1.5 text-sm font-medium text-foreground hover:bg-accent rounded-md transition-colors cursor-pointer"
          >
            <span className="truncate flex-1 text-left">{kbName}</span>
            <ChevronsUpDown className="size-3 text-muted-foreground/50 shrink-0" />
          </button>
        </PopoverTrigger>
        <PopoverContent className="w-52 p-0" align="start">
          <Command>
            <CommandInput placeholder="Search wikis..." aria-label="Search wikis" value={search} onValueChange={setSearch} />
            <CommandList>
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
                    {kb.name}
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
                      Create Wiki
                    </CommandItem>
                  </CommandGroup>
                </>
              )}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>

      <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create wiki</DialogTitle>
          </DialogHeader>
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
            placeholder="My Research"
            className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm"
            autoFocus
          />
          <DialogFooter>
            <button
              onClick={handleCreate}
              disabled={creating || !newName.trim()}
              className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50 cursor-pointer"
            >
              {creating ? 'Creating...' : 'Create'}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={renameDialogOpen} onOpenChange={setRenameDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rename wiki</DialogTitle>
          </DialogHeader>
          <input
            value={renameName}
            onChange={(e) => setRenameName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleRename()}
            className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm"
            autoFocus
          />
          <DialogFooter>
            <button
              onClick={handleRename}
              disabled={renaming || !renameName.trim() || renameName.trim() === kbName}
              className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50 cursor-pointer"
            >
              {renaming ? 'Renaming...' : 'Rename'}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete wiki</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            This will permanently delete <strong>{kbName}</strong> and all its documents. This cannot be undone.
          </p>
          <DialogFooter>
            <button
              onClick={() => setDeleteDialogOpen(false)}
              className="rounded-lg border border-input px-4 py-2 text-sm font-medium hover:bg-accent cursor-pointer"
            >
              Cancel
            </button>
            <button
              onClick={handleDelete}
              disabled={deleting}
              className="rounded-lg bg-destructive px-4 py-2 text-sm font-medium text-destructive-foreground hover:opacity-90 disabled:opacity-50 cursor-pointer"
            >
              {deleting ? 'Deleting...' : 'Delete'}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
