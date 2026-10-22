import { describe, expect, it } from 'vitest'
import { buildViewUrl } from './helpers'

describe('buildViewUrl', () => {
  it('maps each view to its route', () => {
    expect(buildViewUrl('kb', 'wiki')).toBe('/wikis/kb')
    expect(buildViewUrl('kb', 'graph')).toBe('/wikis/kb/graph')
    expect(buildViewUrl('kb', 'files')).toBe('/wikis/kb/files')
  })

  it('appends a trimmed, encoded files path', () => {
    expect(buildViewUrl('kb', 'files', { filesPath: '/' })).toBe('/wikis/kb/files')
    expect(buildViewUrl('kb', 'files', { filesPath: '/My Notes/2026/' })).toBe('/wikis/kb/files/My%20Notes/2026')
  })

  it('appends search params', () => {
    expect(buildViewUrl('kb', 'wiki', { searchParams: { p: '3' } })).toBe('/wikis/kb?p=3')
    expect(buildViewUrl('kb', 'files', { searchParams: { doc: '7' } })).toBe('/wikis/kb/files?doc=7')
  })
})
