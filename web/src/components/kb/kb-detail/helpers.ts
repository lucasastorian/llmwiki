import { toast } from 'sonner'
import { useUserStore } from '@/stores'
import type { DocumentListItem } from '@/lib/types'
import type { ViewMode } from '@/components/kb/viewMode'
import { wikiRelativePath } from '@/lib/wikiTree'


export type ViewNavigationOptions = { filesPath?: string; searchParams?: Record<string, string> }

export type NavigateToView = (view: ViewMode, opts?: ViewNavigationOptions) => void

export function findWikiDocByPath(wikiDocs: DocumentListItem[], path: string): DocumentListItem | undefined {
  return wikiDocs.find((d) => wikiRelativePath(d) === path)
}

export function getAccessTokenOrToast(): string | null {
  const token = useUserStore.getState().accessToken
  if (!token) { toast.error('Not authenticated'); return null }
  return token
}

export function currentSearchParam(key: string): string | null {
  return new URL(window.location.href).searchParams.get(key)
}

export function replaceSearchParam(key: string, value: string | null): void {
  const url = new URL(window.location.href)
  if (value != null) url.searchParams.set(key, value)
  else url.searchParams.delete(key)
  window.history.replaceState(window.history.state, '', url.pathname + url.search)
}

export function buildViewUrl(kbSlug: string, view: ViewMode, opts?: ViewNavigationOptions): string {
  let url = `/wikis/${kbSlug}`
  if (view === 'files') {
    const path = opts?.filesPath ?? '/'
    const clean = path === '/' ? '' : path.replace(/^\//, '').replace(/\/$/, '')
    url += clean ? `/files/${encodeURI(clean)}` : '/files'
  } else if (view === 'graph') {
    url += '/graph'
  }
  if (opts?.searchParams) {
    url += '?' + new URLSearchParams(opts.searchParams).toString()
  }
  return url
}
