import type { QuizQuestion } from './types'

// Include the block, position, and full answer shape so repeated prompts remain
// distinct both within a block and across separate blocks on the same page.
// The choice identity predates text questions — never reorder it, or stored
// completion keys stop matching.
export function questionKey(blockSource: string, question: QuizQuestion, index: number): string {
  const identity =
    question.kind === 'text'
      ? [blockSource.trim(), index, question.prompt.trim(), 'text', question.rubric.trim()]
      : [
          blockSource.trim(),
          index,
          question.prompt.trim(),
          question.options.map((option) => option.trim()),
          question.answer,
        ]
  return stableHash(JSON.stringify(identity))
}

function stableHash(text: string): string {
  let hash = 5381
  for (let i = 0; i < text.length; i++) {
    hash = ((hash << 5) + hash + text.charCodeAt(i)) | 0
  }
  return (hash >>> 0).toString(36)
}
