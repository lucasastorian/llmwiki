// Highlight writes bump documents.version; this lets the reader skip refetching on its own websocket echo.
const versionsByDocument = new Map<string, Set<number>>()

export function markOwnWrite(documentId: string, version: number): void {
  let versions = versionsByDocument.get(documentId)
  if (!versions) {
    versions = new Set()
    versionsByDocument.set(documentId, versions)
  }
  versions.add(version)
}

export function isOwnWrite(documentId: string, version: number): boolean {
  return versionsByDocument.get(documentId)?.has(version) ?? false
}
