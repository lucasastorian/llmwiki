import { describe, expect, it } from 'vitest'
import { locateTextAnchor, normalizeAnchorText } from './locator'

describe('normalizeAnchorText', () => {
  it('collapses whitespace and strips zero-width characters', () => {
    expect(normalizeAnchorText('  hello​   world\n\t!')).toBe('hello world !')
    expect(normalizeAnchorText('a b')).toBe('a b')
  })
})

describe('locateTextAnchor', () => {
  const page = 'The transformer architecture uses attention.\nAttention is all you need, famously.'

  it('finds a unique match and returns original-text offsets', () => {
    const result = locateTextAnchor(page, { textContent: 'transformer architecture' })
    expect(result).not.toBeNull()
    expect(page.slice(result!.textStart, result!.textEnd)).toBe('transformer architecture')
  })

  it('matches across whitespace differences', () => {
    const result = locateTextAnchor(page, { textContent: 'attention. Attention is' })
    expect(result).not.toBeNull()
    expect(result!.textContent).toBe('attention.\nAttention is')
  })

  it('disambiguates repeated text via prefix/suffix context', () => {
    const repeated = 'alpha beta gamma. delta beta epsilon.'
    const result = locateTextAnchor(repeated, {
      textContent: 'beta',
      prefix: 'delta ',
      suffix: ' epsilon',
    })
    expect(result).not.toBeNull()
    expect(result!.textStart).toBe(repeated.indexOf('beta', repeated.indexOf('delta')))
  })

  it('refuses short ambiguous matches without scoring context', () => {
    const repeated = 'aa x aa y aa'
    expect(locateTextAnchor(repeated, { textContent: 'aa' })).toBeNull()
  })

  it('returns null when the text is absent', () => {
    expect(locateTextAnchor(page, { textContent: 'nonexistent passage' })).toBeNull()
  })
})
