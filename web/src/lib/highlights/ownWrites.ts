// Every highlight write bumps documents.version, which echoes back over the
// websocket; remembering our own writes lets the reader skip the pointless
// content refetch that echo would otherwise trigger.
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
