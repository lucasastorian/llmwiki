import { describe, expect, it } from 'vitest'
import { isOwnWrite, markOwnWrite } from './ownWrites'

describe('ownWrites', () => {
  it('recognizes a marked document version', () => {
    markOwnWrite('doc-a', 7)
    expect(isOwnWrite('doc-a', 7)).toBe(true)
  })

  it('does not match other versions or documents', () => {
    markOwnWrite('doc-b', 3)
    expect(isOwnWrite('doc-b', 4)).toBe(false)
    expect(isOwnWrite('doc-unknown', 3)).toBe(false)
  })
})
