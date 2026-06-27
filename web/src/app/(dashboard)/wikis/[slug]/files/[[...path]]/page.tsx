'use client'

import { useParams } from 'next/navigation'
import { KBDetailRoutePage } from '@/components/kb/KBDetailRoutePage'

function parseFilesPath(pathSegments?: string[]): string {
  if (!pathSegments || pathSegments.length === 0) return '/'
  return '/' + pathSegments.map(decodeURIComponent).join('/') + '/'
}

export default function FilesPage() {
  const params = useParams<{ path?: string[] }>()
  return (
    <KBDetailRoutePage
      viewMode="files"
      routeFilesPath={parseFilesPath(params.path)}
    />
  )
}
