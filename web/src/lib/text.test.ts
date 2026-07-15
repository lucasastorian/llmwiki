import { describe, expect, it } from 'vitest'
import { decodeUnicodeEscapes } from './text'

describe('decodeUnicodeEscapes', () => {
  it('decodes literal Unicode escapes in display text', () => {
    expect(decodeUnicodeEscapes('Lesson 2 \\u2014 Revenue Quality')).toBe('Lesson 2 — Revenue Quality')
  })

  it('decodes surrogate pairs', () => {
    expect(decodeUnicodeEscapes('Launch \\uD83D\\uDE80')).toBe('Launch 🚀')
  })

  it('leaves malformed and ordinary text unchanged', () => {
    expect(decodeUnicodeEscapes('A \\u20G4 B — C')).toBe('A \\u20G4 B — C')
  })
})
