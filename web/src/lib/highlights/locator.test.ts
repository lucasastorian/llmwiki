import { describe, expect, it } from 'vitest'

import fixture from '../../../../tests/fixtures/parity/highlight_locator.json'
import { locateTextAnchor, normalizeAnchorText, type LocateResult } from './locator'

interface Documented {
  name: string
  knownDiscrepancy?: string
}

interface NormalizeCase extends Documented {
  input: string
  expected: string
  tsExpected?: string
}

interface LocateCase extends Documented {
  plaintext: string
  textContent: string
  prefix?: string
  suffix?: string
  expected: LocateResult | null
  tsExpected?: LocateResult | null
}

const normalizeCases: NormalizeCase[] = fixture.normalizeAnchorText
const locateCases: LocateCase[] = fixture.locateTextAnchor

describe('normalizeAnchorText parity with the server', () => {
  it.each(normalizeCases)('$name', (c) => {
    expect(normalizeAnchorText(c.input)).toBe(c.tsExpected ?? c.expected)
  })
})

describe('locateTextAnchor parity with the server', () => {
  it.each(locateCases)('$name', (c) => {
    const located = locateTextAnchor(c.plaintext, {
      textContent: c.textContent,
      prefix: c.prefix,
      suffix: c.suffix,
    })
    expect(located).toEqual(c.tsExpected ?? c.expected)
  })
})

describe('documented locator discrepancies', () => {
  it('documents every TS-only expectation as a discrepancy', () => {
    const overridden = [...normalizeCases, ...locateCases].filter((c) => c.tsExpected !== undefined)
    for (const c of overridden) {
      expect(c.knownDiscrepancy).toBeTruthy()
      expect(c.tsExpected).not.toEqual(c.expected)
    }
  })
})
