// Session-wide union of correctly answered question keys per document, so
// multiple quiz blocks on one page never clobber each other's PATCH payloads.
const completedByDoc = new Map<string, Set<string>>()
const saveQueueByDoc = new Map<string, Promise<void>>()

export function seedCompleted(documentId: string, keys: string[]): Set<string> {
  const existing = completedByDoc.get(documentId)
  if (existing) {
    keys.forEach((key) => existing.add(key))
    return existing
  }
  const created = new Set(keys)
  completedByDoc.set(documentId, created)
  return created
}

export function recordCompleted(documentId: string, key: string): string[] {
  const set = seedCompleted(documentId, [key])
  set.add(key)
  return Array.from(set)
}

export function queueCompletedSave(
  documentId: string,
  save: (keys: string[]) => Promise<unknown>,
): Promise<void> {
  const previous = saveQueueByDoc.get(documentId) ?? Promise.resolve()
  const queued = previous
    .catch(() => undefined)
    .then(() => save(Array.from(seedCompleted(documentId, []))))
    .then(() => undefined)
  saveQueueByDoc.set(documentId, queued)
  const cleanup = () => {
    if (saveQueueByDoc.get(documentId) === queued) saveQueueByDoc.delete(documentId)
  }
  void queued.then(cleanup, cleanup)
  return queued
}
