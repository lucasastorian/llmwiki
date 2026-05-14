// ProseMirror plugin that owns a DecorationSet of inline highlight
// decorations. Highlights are stored in the documents.highlights JSONB column
// (sole source of truth) and applied as decorations on render — they never
// touch the document content.
//
// Update flow: callers dispatch a single transaction with meta
// `{ setDecorations: DecorationRange[] }`. The plugin builds a fresh
// DecorationSet from those ranges. On any other transaction we map the set
// through `tr.mapping` so decorations follow text edits (relevant in future
// edit mode; harmless in read-only).

import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'
import { Extension } from '@tiptap/core'
import type { DecorationRange } from './types'

export const HIGHLIGHT_CLASS = 'llmwiki-hl'
export const HIGHLIGHT_ATTR = 'data-hl-id'

interface HighlightMeta {
  setDecorations?: DecorationRange[]
  clear?: boolean
}

export const highlightPluginKey = new PluginKey<DecorationSet>('llmwikiHighlights')

export function highlightDecorationPlugin(): Plugin<DecorationSet> {
  return new Plugin<DecorationSet>({
    key: highlightPluginKey,
    state: {
      init: () => DecorationSet.empty,
      apply(tr, old) {
        const meta = tr.getMeta(highlightPluginKey) as HighlightMeta | undefined
        if (meta?.clear) {
          return DecorationSet.empty
        }
        if (meta?.setDecorations) {
          // ProseMirror's DecorationSet requires decorations in document
          // order. Sort defensively in case the caller didn't.
          const sorted = [...meta.setDecorations]
            .filter((r) => r.from < r.to)
            .sort((a, b) => (a.from - b.from) || (a.to - b.to))
          const decorations = sorted.map((r) =>
            Decoration.inline(r.from, r.to, {
              class: HIGHLIGHT_CLASS,
              [HIGHLIGHT_ATTR]: r.id,
            }),
          )
          return DecorationSet.create(tr.doc, decorations)
        }
        return old.map(tr.mapping, tr.doc)
      },
    },
    props: {
      decorations(state) {
        return highlightPluginKey.getState(state) ?? null
      },
    },
  })
}

/** TipTap Extension wrapper so the plugin can be registered alongside other
 *  extensions in a `useEditor({ extensions: [...] })` array. */
export const HighlightDecorations = Extension.create({
  name: 'highlightDecorations',
  addProseMirrorPlugins() {
    return [highlightDecorationPlugin()]
  },
})
