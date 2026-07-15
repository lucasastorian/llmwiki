interface QuizQuestionBase {
  prompt: string
  hints: string[]
  explanation: string | null
}

export interface ChoiceQuestion extends QuizQuestionBase {
  kind: 'choice'
  options: string[]
  answer: number
}

export interface TextQuestion extends QuizQuestionBase {
  kind: 'text'
  rubric: string
}

export type QuizQuestion = ChoiceQuestion | TextQuestion

export interface QuizSpec {
  title: string | null
  questions: QuizQuestion[]
}

export type QuizParseResult = { spec: QuizSpec; error: null } | { spec: null; error: string }

export type QuizVerdict = 'correct' | 'partial' | 'incorrect'

export interface QuizGradeResult {
  verdict: QuizVerdict
  feedback: string
}
