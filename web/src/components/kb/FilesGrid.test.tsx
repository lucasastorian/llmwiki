import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DocumentListItem } from '@/lib/types'
import { FilesGrid } from './FilesGrid'

vi.mock('@/components/editor/NoteEditor', () => ({ NoteEditor: () => null }))
vi.mock('@/components/editor/NoteToolbar', () => ({ NoteFormattingButtons: () => null }))
vi.mock('@/components/kb/DocViewers', () => ({
  PdfDocViewer: () => null, ImageViewer: () => null, HtmlDocViewer: () => null, ContentViewer: () => null,
  UnsupportedViewer: () => <div>viewer</div>, ProcessingViewer: () => null, FailedViewer: () => null,
}))

function doc(id: string, title: string, path = '/'): DocumentListItem {
  return {
    id, title, filename: `${title}.bin`, path, file_type: 'bin', status: 'ready',
    archived: false, metadata: {}, updated_at: '2026-01-01T00:00:00Z', document_number: 1,
  } as unknown as DocumentListItem
}

function renderGrid(selectedIds: ReadonlySet<string> = new Set()) {
  const onSelectDocument = vi.fn()
  const onDocOpen = vi.fn()
  const onShownFolderChange = vi.fn()
  render(
    <FilesGrid
      documents={[doc('b', 'Beta'), doc('a', 'Alpha'), doc('g', 'Gamma', '/Folder/')]}
      onDeleteDocument={vi.fn()}
      onRenameDocument={vi.fn()}
      onUpload={vi.fn()}
      onCreateNote={vi.fn()}
      onCreateFolder={vi.fn()}
      onDocOpen={onDocOpen}
      selectedIds={selectedIds}
      onSelectDocument={onSelectDocument}
      onShownFolderChange={onShownFolderChange}
    />,
  )
  return { onSelectDocument, onDocOpen, onShownFolderChange }
}

function card(title: string): HTMLElement {
  return screen.getByText(title).closest('[aria-selected]') as HTMLElement
}

afterEach(cleanup)

describe('FilesGrid selection', () => {
  it('toggles on cmd/ctrl-click and ranges on shift-click, in visible order', () => {
    const { onSelectDocument, onDocOpen } = renderGrid()
    fireEvent.click(card('Alpha'), { metaKey: true })
    fireEvent.click(card('Beta'), { ctrlKey: true })
    fireEvent.click(card('Beta'), { shiftKey: true })

    expect(onSelectDocument.mock.calls).toEqual([
      ['a', 'toggle', ['a', 'b']],
      ['b', 'toggle', ['a', 'b']],
      ['b', 'range', ['a', 'b']],
    ])
    expect(onDocOpen).not.toHaveBeenCalled()
  })

  it('opens the document on a plain click', () => {
    const { onSelectDocument, onDocOpen } = renderGrid()
    fireEvent.click(card('Alpha'))
    expect(onDocOpen).toHaveBeenCalledOnce()
    expect(onSelectDocument).not.toHaveBeenCalled()
  })

  it('exposes the selected state on the card', () => {
    renderGrid(new Set(['a']))
    expect(card('Alpha').getAttribute('aria-selected')).toBe('true')
    expect(card('Beta').getAttribute('aria-selected')).toBe('false')
  })

  it('reports a folder change so a selection can never span folders', () => {
    const { onShownFolderChange } = renderGrid(new Set(['a']))
    onShownFolderChange.mockClear()

    fireEvent.click(screen.getByText('Folder'))

    expect(onShownFolderChange).toHaveBeenCalledOnce()
    expect(screen.getByText('Gamma')).toBeTruthy()
  })
})
