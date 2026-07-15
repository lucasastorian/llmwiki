import { parse } from 'yaml'
import type { ChoiceQuestion, QuizParseResult, QuizQuestion, QuizSpec, TextQuestion } from './types'

// Mirrors the server-side validator (mcp/tools/quiz_lint.py); the server is the
// gate at write time, this guards against content that predates or bypasses it.
const MIN_OPTIONS = 2
const MAX_OPTIONS = 6
const MAX_QUESTIONS = 20

export function parseQuizYaml(source: string): QuizParseResult {
  let data: unknown
  try {
    data = parse(source)
  } catch (err) {
    return { spec: null, error: err instanceof Error ? err.message : 'invalid YAML' }
  }
  if (!isRecord(data)) return { spec: null, error: 'quiz body must be a YAML mapping' }

  const rawQuestions = data.questions
  if (!Array.isArray(rawQuestions) || rawQuestions.length === 0) {
    return { spec: null, error: '`questions` must be a non-empty list' }
  }
  if (rawQuestions.length > MAX_QUESTIONS) {
    return { spec: null, error: `at most ${MAX_QUESTIONS} questions per block` }
  }

  const questions: QuizQuestion[] = []
  for (let i = 0; i < rawQuestions.length; i++) {
    const result = parseQuestion(rawQuestions[i])
    if (typeof result === 'string') return { spec: null, error: `question ${i + 1}: ${result}` }
    questions.push(result)
  }

  const title = typeof data.title === 'string' && data.title.trim() ? data.title.trim() : null
  const spec: QuizSpec = { title, questions }
  return { spec, error: null }
}

interface SharedFields {
  prompt: string
  hints: string[]
  explanation: string | null
}

function parseQuestion(raw: unknown): QuizQuestion | string {
  if (!isRecord(raw)) return 'must be a mapping with a `prompt`'

  const kind = raw.type ?? 'choice'
  if (kind !== 'choice' && kind !== 'text') return '`type` must be "choice" or "text"'

  const shared = parseSharedFields(raw)
  if (typeof shared === 'string') return shared

  return kind === 'text' ? parseTextQuestion(raw, shared) : parseChoiceQuestion(raw, shared)
}

function parseSharedFields(raw: Record<string, unknown>): SharedFields | string {
  const prompt = raw.prompt
  if (typeof prompt !== 'string' || !prompt.trim()) return '`prompt` must be non-empty text'

  const hints = raw.hints ?? []
  if (!isStringList(hints)) return '`hints` must be a list of non-empty strings'

  const explanation = raw.explanation
  if (explanation !== undefined && explanation !== null && typeof explanation !== 'string') {
    return '`explanation` must be text'
  }

  return {
    prompt: prompt.trim(),
    hints: hints.map((hint) => hint.trim()),
    explanation: typeof explanation === 'string' && explanation.trim() ? explanation.trim() : null,
  }
}

function parseChoiceQuestion(raw: Record<string, unknown>, shared: SharedFields): ChoiceQuestion | string {
  const options = raw.options
  if (!isStringList(options)) return '`options` must be a list of non-empty strings'
  if (options.length < MIN_OPTIONS || options.length > MAX_OPTIONS) {
    return `\`options\` must list ${MIN_OPTIONS}-${MAX_OPTIONS} choices`
  }

  const answer = raw.answer
  if (typeof answer !== 'number' || !Number.isInteger(answer) || answer < 0 || answer >= options.length) {
    return '`answer` must be the 0-based index of the correct option'
  }

  return { kind: 'choice', options: options.map((option) => option.trim()), answer, ...shared }
}

function parseTextQuestion(raw: Record<string, unknown>, shared: SharedFields): TextQuestion | string {
  const rubric = raw.rubric
  if (typeof rubric !== 'string' || !rubric.trim()) return '`rubric` must be non-empty text'
  return { kind: 'text', rubric: rubric.trim(), ...shared }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isStringList(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string' && item.trim() !== '')
}
