// Highlights are decorations only and never touch document content.

import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'
import { Extension } from '@tiptap/core'
import type { DecorationRange } from './types'

export const HIGHLIGHT_CLASS = 'llmwiki-hl'
export const HIGHLIGHT_ATTR = 'data-hl-id'
export const COMMENT_CLASS = 'llmwiki-hl-comment'

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
          // DecorationSet requires document order.
          const sorted = [...meta.setDecorations]
            .filter((r) => r.from < r.to)
            .sort((a, b) => (a.from - b.from) || (a.to - b.to))
          const decorations = sorted.flatMap((r) => {
            const attrs: Record<string, string> = {
              class: HIGHLIGHT_CLASS,
              [HIGHLIGHT_ATTR]: r.id,
            }
            const comment = r.comment?.trim()
            if (comment) {
              attrs['data-llmwiki-comment'] = '1'
              attrs['data-llmwiki-comment-text'] = comment
              attrs.title = comment
            }
            const inline = Decoration.inline(r.from, r.to, attrs)
            if (!comment) return [inline]

            const widget = Decoration.widget(
              r.to,
              () => {
                const el = document.createElement('span')
                el.className = COMMENT_CLASS
                el.textContent = '💬'
                el.title = comment
                el.setAttribute(HIGHLIGHT_ATTR, r.id)
                el.setAttribute('data-llmwiki-comment-text', comment)
                return el
              },
              { side: 1, key: `${r.id}:comment` },
            )
            return [inline, widget]
          })
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

export const HighlightDecorations = Extension.create({
  name: 'highlightDecorations',
  addProseMirrorPlugins() {
    return [highlightDecorationPlugin()]
  },
})
