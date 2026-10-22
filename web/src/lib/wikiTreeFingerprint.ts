import type { DocumentListItem } from '@/lib/types'

/** Key over only the fields that shape the wiki tree, so version/status churn doesn't refetch index.json. */
export function wikiTreeFingerprint(wikiDocs: DocumentListItem[]): string {
  return wikiDocs.map((d) => [d.id, d.path, d.filename, d.title, d.document_number, d.sort_order].join(':')).join('|')
}
