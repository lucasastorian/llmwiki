import { describe, expect, it } from 'vitest'
import { queueCompletedSave, recordCompleted } from './quizProgress'

describe('quiz progress persistence', () => {
  it('serializes saves and sends the latest union after an in-flight write', async () => {
    const documentId = 'queue-test-document'
    const snapshots: string[][] = []
    let releaseFirst!: () => void
    let markFirstStarted!: () => void
    const firstPending = new Promise<void>((resolve) => {
      releaseFirst = resolve
    })
    const firstStarted = new Promise<void>((resolve) => {
      markFirstStarted = resolve
    })

    recordCompleted(documentId, 'a')
    const first = queueCompletedSave(documentId, async (keys) => {
      snapshots.push(keys)
      markFirstStarted()
      await firstPending
    })

    await firstStarted
    recordCompleted(documentId, 'b')
    const second = queueCompletedSave(documentId, async (keys) => {
      snapshots.push(keys)
    })

    expect(snapshots).toEqual([['a']])
    releaseFirst()
    await Promise.all([first, second])
    expect(snapshots).toEqual([['a'], ['a', 'b']])
  })
})
