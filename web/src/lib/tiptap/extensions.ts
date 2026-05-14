// Shared TipTap extension setup. Use the same configuration in NoteEditor
// and MarkdownClipViewer so the parsed-doc shape (and therefore the
// canonical-plaintext walker output) is identical.

import { mergeAttributes } from '@tiptap/core'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'
import Typography from '@tiptap/extension-typography'
import Link from '@tiptap/extension-link'
import Image from '@tiptap/extension-image'
import { Table, TableRow, TableHeader, TableCell } from '@tiptap/extension-table'
import { Markdown } from 'tiptap-markdown'

import { HighlightDecorations } from '@/lib/highlights/decorationPlugin'

export interface MarkdownExtensionOptions {
  /** Optional placeholder shown when the doc is empty (editor mode only). */
  placeholder?: string
  /** Optional resolver for image src — receives the stored relative src,
   *  returns the URL to display. Used in 2D for relative image refs. */
  imageSrcResolver?: (src: string) => string
}

export function createMarkdownExtensions(options?: MarkdownExtensionOptions) {
  const ImageExt = options?.imageSrcResolver
    ? Image.extend({
        renderHTML({ HTMLAttributes }) {
          const original = (HTMLAttributes.src as string | undefined) ?? ''
          const resolved = original ? options.imageSrcResolver!(original) : original
          // Preserve the original relative src in `data-src` so the storage
          // round-trip stays clean — only the rendered DOM gets the resolved
          // (possibly signed) URL. mergeAttributes properly merges class/style.
          return [
            'img',
            mergeAttributes(HTMLAttributes, { src: resolved, 'data-src': original }),
          ]
        },
      })
    : Image

  return [
    StarterKit.configure({
      heading: { levels: [1, 2, 3] },
      link: false,
    }),
    Placeholder.configure({ placeholder: options?.placeholder ?? '' }),
    Typography,
    Link.configure({ autolink: true, openOnClick: false }),
    ImageExt.configure({ inline: false, allowBase64: true }),
    Table.configure({ resizable: false }),
    TableRow,
    TableHeader,
    TableCell,
    Markdown.configure({
      html: false,
      transformCopiedText: true,
      transformPastedText: true,
    }),
    HighlightDecorations,
  ]
}
