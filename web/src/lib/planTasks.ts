export type TaskStatus = 'todo' | 'in_progress' | 'done' | 'blocked'

export interface StageProgress {
  title: string
  counts: Record<TaskStatus, number>
  total: number
  done: number
}

export interface PlanSummary {
  stages: StageProgress[]
  total: number
  done: number
}

const FRONTMATTER_RE = /^\s*---[ \t]*\n[\s\S]*?\n---[ \t]*\n/
const STAGE_RE = /^##(?!#)\s+(.+?)\s*$/
const TASK_RE = /^[ \t]*[-*+][ \t]+\[([ xX~!])\](?:[ \t]|$)/

const MARKER_STATUS: Record<string, TaskStatus> = {
  ' ': 'todo',
  x: 'done',
  X: 'done',
  '~': 'in_progress',
  '!': 'blocked',
}

function emptyStage(title: string): StageProgress {
  return {
    title,
    counts: { todo: 0, in_progress: 0, done: 0, blocked: 0 },
    total: 0,
    done: 0,
  }
}

function cleanStageTitle(raw: string): string {
  return raw.replace(/\*\*/g, '').replace(/\[([^\]]+)\]\(([^)]*)\)/g, '$1').trim()
}

// Nested tasks count toward the enclosing stage; the 4-space code-block ambiguity is accepted.
export function parsePlanTasks(markdown: string): PlanSummary {
  const lines = markdown.replace(FRONTMATTER_RE, '').split('\n')
  const stages: StageProgress[] = []
  let current = emptyStage('')
  let inFence = false

  for (const line of lines) {
    if (/^(```|~~~)/.test(line)) {
      inFence = !inFence
      continue
    }
    if (inFence) continue

    const stage = line.match(STAGE_RE)
    if (stage) {
      if (current.total > 0) stages.push(current)
      current = emptyStage(cleanStageTitle(stage[1]))
      continue
    }

    const task = line.match(TASK_RE)
    if (!task) continue
    const status = MARKER_STATUS[task[1]]
    current.counts[status] += 1
    current.total += 1
    if (status === 'done') current.done += 1
  }
  if (current.total > 0) stages.push(current)

  return {
    stages,
    total: stages.reduce((sum, s) => sum + s.total, 0),
    done: stages.reduce((sum, s) => sum + s.done, 0),
  }
}
