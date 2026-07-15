import { describe, expect, it } from 'vitest'
import { parseQuizYaml } from './parseQuiz'

const VALID = `title: Checkpoint
questions:
  - prompt: What is $P(A)$?
    options: ["$1/4$", "$3/8$"]
    answer: 1
    hints:
      - think
    explanation: because
`

const VALID_TEXT = `questions:
  - type: text
    prompt: Explain the base-rate fallacy.
    rubric: Correct if the answer invokes the prior.
    explanation: Bayes.
`

describe('parseQuizYaml', () => {
  it('parses a valid block with trimmed fields and defaults', () => {
    const result = parseQuizYaml(VALID)
    expect(result.error).toBeNull()
    expect(result.spec?.title).toBe('Checkpoint')
    expect(result.spec?.questions).toHaveLength(1)
    const question = result.spec!.questions[0]
    expect(question.kind).toBe('choice')
    if (question.kind !== 'choice') throw new Error('expected choice question')
    expect(question.prompt).toBe('What is $P(A)$?')
    expect(question.options).toEqual(['$1/4$', '$3/8$'])
    expect(question.answer).toBe(1)
    expect(question.hints).toEqual(['think'])
    expect(question.explanation).toBe('because')
  })

  it('parses a text question with its rubric', () => {
    const result = parseQuizYaml(VALID_TEXT)
    expect(result.error).toBeNull()
    const question = result.spec!.questions[0]
    expect(question.kind).toBe('text')
    if (question.kind !== 'text') throw new Error('expected text question')
    expect(question.rubric).toBe('Correct if the answer invokes the prior.')
    expect(question.explanation).toBe('Bayes.')
  })

  it('rejects a text question without a rubric', () => {
    const result = parseQuizYaml('questions:\n  - type: text\n    prompt: Explain X.\n')
    expect(result.error).toBe('question 1: `rubric` must be non-empty text')
  })

  it('rejects an unknown question type', () => {
    const result = parseQuizYaml('questions:\n  - type: essay\n    prompt: Q?\n')
    expect(result.error).toBe('question 1: `type` must be "choice" or "text"')
  })

  it('defaults title, hints, and explanation when absent', () => {
    const result = parseQuizYaml('questions:\n  - prompt: Q?\n    options: [a, b]\n    answer: 0\n')
    expect(result.spec?.title).toBeNull()
    expect(result.spec?.questions[0].hints).toEqual([])
    expect(result.spec?.questions[0].explanation).toBeNull()
  })

  it('rejects invalid YAML', () => {
    expect(parseQuizYaml('{ unbalanced').spec).toBeNull()
  })

  it('rejects a non-mapping body', () => {
    expect(parseQuizYaml('- a\n- b\n').error).toBe('quiz body must be a YAML mapping')
  })

  it('rejects a missing or empty questions list', () => {
    expect(parseQuizYaml('title: Empty\n').error).toBe('`questions` must be a non-empty list')
    expect(parseQuizYaml('questions: []\n').error).toBe('`questions` must be a non-empty list')
  })

  it('rejects an out-of-range answer with the question number', () => {
    const result = parseQuizYaml('questions:\n  - prompt: Q?\n    options: [a, b]\n    answer: 2\n')
    expect(result.error).toBe('question 1: `answer` must be the 0-based index of the correct option')
  })

  it('rejects a non-integer answer', () => {
    const result = parseQuizYaml('questions:\n  - prompt: Q?\n    options: [a, b]\n    answer: 0.5\n')
    expect(result.spec).toBeNull()
  })

  it('rejects option counts outside 2-6', () => {
    expect(parseQuizYaml('questions:\n  - prompt: Q?\n    options: [only]\n    answer: 0\n').spec).toBeNull()
    const seven = Array.from({ length: 7 }, (_, i) => `o${i}`).join(', ')
    expect(parseQuizYaml(`questions:\n  - prompt: Q?\n    options: [${seven}]\n    answer: 0\n`).spec).toBeNull()
  })

  it('rejects empty prompts and empty options', () => {
    expect(parseQuizYaml('questions:\n  - prompt: ""\n    options: [a, b]\n    answer: 0\n').spec).toBeNull()
    expect(parseQuizYaml('questions:\n  - prompt: Q?\n    options: [a, ""]\n    answer: 0\n').spec).toBeNull()
  })
})
