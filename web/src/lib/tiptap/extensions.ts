// Every TipTap surface must share this config so canonical plaintext is identical.

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
  placeholder?: string
  imageSrcResolver?: (src: string) => string
  /** Render-only attributes, so signed URLs and dimensions never reach the Markdown. */
  imageAttrsResolver?: (src: string) => Record<string, unknown>
}

export function createMarkdownExtensions(options?: MarkdownExtensionOptions) {
  const ImageExt = options?.imageSrcResolver || options?.imageAttrsResolver
    ? Image.extend({
        renderHTML({ HTMLAttributes }) {
          const original = (HTMLAttributes.src as string | undefined) ?? ''
          const resolved = original && options.imageSrcResolver
            ? options.imageSrcResolver(original)
            : original
          const extraAttrs = original && options.imageAttrsResolver
            ? options.imageAttrsResolver(original)
            : {}
          // data-src keeps the stored relative src; only the rendered DOM gets the signed URL.
          return [
            'img',
            mergeAttributes(HTMLAttributes, extraAttrs, { src: resolved, 'data-src': original }),
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
