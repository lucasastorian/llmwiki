import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, apiFetch } from '@/lib/api'
import { parseQuizYaml } from '@/lib/quiz/parseQuiz'
import { questionKey } from '@/lib/quiz/questionKey'
import { QuizBlock } from './QuizBlock'

vi.mock('@/stores', () => ({
  useUserStore: (selector: (state: { accessToken: string }) => unknown) =>
    selector({ accessToken: 'test-token' }),
}))

vi.mock('@/lib/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/api')>()
  return { ...original, apiFetch: vi.fn() }
})

const apiFetchMock = vi.mocked(apiFetch)
const source = `questions:
  - type: text
    prompt: Why does the base rate matter?
    rubric: Correct if the answer connects rarity to false positives.
    explanation: A low prior can make false positives outnumber true positives.
`

describe('QuizBlock free-form questions', () => {
  beforeEach(() => {
    apiFetchMock.mockReset()
  })

  it('renders a quiet completed state instead of an empty disabled answer', () => {
    const parsed = parseQuizYaml(source)
    if (!parsed.spec) throw new Error(parsed.error)
    const key = questionKey(source, parsed.spec.questions[0], 0)
    const documentsRef = {
      current: [{ id: 'doc-1', metadata: { quiz: [key] } }],
    }

    render(
      <QuizBlock
        source={source}
        documentId="doc-1"
        documentsRef={documentsRef as never}
      />,
    )

    expect(screen.queryByRole('textbox', { name: 'Your answer' })).toBeNull()
    expect(screen.getByText('Completed')).toBeTruthy()
    expect(screen.getByText('Explanation')).toBeTruthy()
  })

  it('announces a daily grading limit with the server message', async () => {
    apiFetchMock.mockRejectedValueOnce(
      new ApiError(
        429,
        'Daily grading limit reached. You can check up to 100 answers in any 24-hour period.',
      ),
    )

    render(
      <QuizBlock
        source={source}
        documentId="doc-2"
        documentsRef={{ current: [] } as never}
      />,
    )

    fireEvent.change(screen.getByRole('textbox', { name: 'Your answer' }), {
      target: { value: 'Because the disease is rare.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Check answer' }))

    expect(
      await screen.findByText(
        'Daily grading limit reached. You can check up to 100 answers in any 24-hour period.',
      ),
    ).toBeTruthy()
    expect(screen.getByRole('status')).toBeTruthy()
  })
})
