import { describe, expect, it } from 'vitest'
import { questionKey } from './questionKey'
import type { ChoiceQuestion, TextQuestion } from './types'

const SOURCE = 'title: Checkpoint\nquestions: [...]'
const QUESTION: ChoiceQuestion = {
  kind: 'choice',
  prompt: 'What is $P(A)$?',
  options: ['$1/4$', '$3/8$'],
  answer: 1,
  hints: [],
  explanation: null,
}
const TEXT_QUESTION: TextQuestion = {
  kind: 'text',
  prompt: 'Explain the base-rate fallacy.',
  rubric: 'Correct if the answer invokes the prior.',
  hints: [],
  explanation: null,
}

describe('questionKey', () => {
  it('is stable for the same block and question', () => {
    expect(questionKey(SOURCE, QUESTION, 0)).toBe(questionKey(SOURCE, QUESTION, 0))
    expect(questionKey(SOURCE, TEXT_QUESTION, 0)).toBe(questionKey(SOURCE, TEXT_QUESTION, 0))
  })

  it('distinguishes repeated prompts by question position and answer shape', () => {
    expect(questionKey(SOURCE, QUESTION, 0)).not.toBe(questionKey(SOURCE, QUESTION, 1))
    expect(questionKey(SOURCE, QUESTION, 0)).not.toBe(
      questionKey(SOURCE, { ...QUESTION, options: ['yes', 'no'], answer: 0 }, 0),
    )
  })

  it('distinguishes text questions by rubric', () => {
    expect(questionKey(SOURCE, TEXT_QUESTION, 0)).not.toBe(
      questionKey(SOURCE, { ...TEXT_QUESTION, rubric: 'Correct if the answer names Bayes.' }, 0),
    )
  })

  it('distinguishes the same question in different blocks', () => {
    expect(questionKey(SOURCE, QUESTION, 0)).not.toBe(
      questionKey(`${SOURCE}\n# second block`, QUESTION, 0),
    )
  })
})
