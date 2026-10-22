import { describe, expect, it } from 'vitest'

import fixture from '../../../../tests/fixtures/parity/quiz_parse.json'
import { parseQuizYaml } from './parseQuiz'

describe('parseQuizYaml parity with the server quiz lint', () => {
  it.each(fixture.cases)('$name', (c) => {
    const result = parseQuizYaml(c.yaml)
    expect(result.spec).toEqual(c.ts.spec)
    if (c.ts.error !== undefined) expect(result.error).toBe(c.ts.error)
    if (c.ts.spec === null) expect(result.error).toEqual(expect.any(String))
  })

  it.each(fixture.cases.filter((c) => c.pythonValid))('$name: accepted by the server, so accepted here', (c) => {
    expect(c.ts.spec).not.toBeNull()
  })

  it.each(fixture.cases.filter((c) => !c.pythonValid && c.ts.spec !== null))(
    '$name: accepted here despite the server, for a documented reason',
    (c) => {
      expect(c.tsLenient).toBeTruthy()
    },
  )
})
