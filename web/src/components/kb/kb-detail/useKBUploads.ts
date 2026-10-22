import * as React from 'react'
import { toast } from 'sonner'
import { apiFetch } from '@/lib/api'
import { refreshAccessToken } from '@/lib/auth-token'
import { useUploadStore, useUserStore } from '@/stores'
import type { DocumentListItem } from '@/lib/types'
import { getAccessTokenOrToast } from './helpers'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
const isLocal = process.env.NEXT_PUBLIC_MODE === 'local'
const UPLOAD_ACCEPT = '.md,.txt,.pdf,.pptx,.ppt,.docx,.doc,.png,.jpg,.jpeg,.webp,.gif,.svg,.xlsx,.csv,.html,.htm'
const BINARY_UPLOAD_TYPES = new Set(['pdf', 'pptx', 'ppt', 'docx', 'doc', 'png', 'jpg', 'jpeg', 'webp', 'gif', 'xlsx', 'csv', 'html', 'htm'])
const TUS_RETRY_DELAYS = [0, 1000, 3000, 5000]

type Params = {
  kbId: string
  kbSlug: string
  userId: string | undefined
  documents: DocumentListItem[]
  setDocuments: React.Dispatch<React.SetStateAction<DocumentListItem[]>>
  sourceDocCount: number
  openFilesView: () => void
}

export interface KBUploads {
  handleUploadClick: (targetPath?: string) => void
  uploadFiles: (files: File[], targetPath?: string) => void
}

/** File uploads into the KB: text files import as notes, binaries go through TUS (or the local endpoint). */
export function useKBUploads({ kbId, kbSlug, userId, documents, setDocuments, sourceDocCount, openFilesView }: Params): KBUploads {
  const addUpload = useUploadStore((s) => s.addUpload)
  const setUploadProgress = useUploadStore((s) => s.setProgress)
  const markUploadProcessing = useUploadStore((s) => s.markProcessing)
  const markUploadFailed = useUploadStore((s) => s.markFailed)
  const reconcileUploads = useUploadStore((s) => s.reconcileDocuments)
  const processingUploads = useUploadStore(
    (s) => s.items.filter((i) => i.kbId === kbId && i.phase === 'processing').length,
  )

  const tusUploadFile = React.useCallback(async (file: File, targetPath: string = '/'): Promise<void> => {
    const t = getAccessTokenOrToast()
    if (!t) return Promise.reject(new Error('Not authenticated'))
    const uploadToken = await refreshAccessToken(t).catch(() => null) ?? t
    const uploadId = crypto.randomUUID()
    addUpload({ id: uploadId, filename: file.name, kbId, kbSlug, path: targetPath })
    const { Upload } = await import('tus-js-client')
    return new Promise((resolve, reject) => {
      const upload = new Upload(file, {
        endpoint: `${API_URL}/v1/uploads`,
        retryDelays: TUS_RETRY_DELAYS,
        metadata: { filename: file.name, knowledge_base_id: kbId, path: targetPath },
        headers: { Authorization: `Bearer ${uploadToken}` },
        onBeforeRequest: (request) => {
          // Supabase can rotate the token between TUS chunks, so read it at send time.
          const latestToken = useUserStore.getState().accessToken ?? uploadToken
          request.setHeader('Authorization', `Bearer ${latestToken}`)
        },
        onProgress: (sent, total) => setUploadProgress(uploadId, total > 0 ? sent / total : 0),
        onError: (error) => { markUploadFailed(uploadId); reject(error) },
        onSuccess: () => { markUploadProcessing(uploadId); resolve() },
      })
      upload.start()
    })
  }, [kbId, kbSlug, addUpload, setUploadProgress, markUploadProcessing, markUploadFailed])

  const localUploadFile = React.useCallback(async (file: File, targetPath: string): Promise<void> => {
    const uploadId = crypto.randomUUID()
    addUpload({ id: uploadId, filename: file.name, kbId, kbSlug, path: targetPath })
    const formData = new FormData()
    formData.append('file', file)
    formData.append('path', targetPath)
    try {
      const res = await fetch(`${API_URL}/v1/upload`, { method: 'POST', body: formData })
      if (!res.ok) throw new Error(`Upload failed: ${res.status}`)
      const data = await res.json()
      setDocuments((prev) => [data, ...prev])
      markUploadProcessing(uploadId)
    } catch { markUploadFailed(uploadId) }
  }, [kbId, kbSlug, addUpload, setDocuments, markUploadProcessing, markUploadFailed])

  const importTextFile = React.useCallback(async (file: File, token: string, targetPath: string): Promise<void> => {
    const content = await file.text()
    const title = file.name.replace(/\.(md|txt)$/i, '')
    try {
      const data = await apiFetch<DocumentListItem>(`/v1/knowledge-bases/${kbId}/documents/note`, token, {
        method: 'POST',
        body: JSON.stringify({ filename: file.name, title, content, path: targetPath }),
      })
      setDocuments((prev) => [data, ...prev])
    } catch { toast.error(`Failed to import ${file.name}`) }
  }, [kbId, setDocuments])

  const uploadOneFile = React.useCallback(async (file: File, token: string, targetPath: string): Promise<void> => {
    const ext = file.name.split('.').pop()?.toLowerCase()
    if (ext === 'md' || ext === 'txt') return importTextFile(file, token, targetPath)
    if (!ext || !BINARY_UPLOAD_TYPES.has(ext)) {
      toast.info(unsupportedFileMessage(ext))
      return
    }
    if (isLocal) return localUploadFile(file, targetPath)
    return tusUploadFile(file, targetPath)
  }, [importTextFile, localUploadFile, tusUploadFile])

  const uploadFiles = React.useCallback((files: File[], targetPath: string = '/') => {
    const t = getAccessTokenOrToast()
    if (!t || !userId) return
    const accepted = dropDuplicateUploads(files, documents, targetPath)
    if (!accepted) return
    Promise.all(accepted.map((file) => uploadOneFile(file, t, targetPath))).then(() => {
      const textFiles = accepted.filter((f) => /\.(md|txt)$/i.test(f.name))
      if (textFiles.length > 0) toast.success(`Imported ${textFiles.length} file${textFiles.length > 1 ? 's' : ''}`)
      if (sourceDocCount === 0) openFilesView()
    })
  }, [userId, documents, uploadOneFile, sourceDocCount, openFilesView])

  const uploadPathRef = React.useRef('/')
  const handleUploadClick = (targetPath: string = '/'): void => {
    uploadPathRef.current = targetPath
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = UPLOAD_ACCEPT
    input.multiple = true
    input.onchange = () => { if (input.files) uploadFiles(Array.from(input.files), uploadPathRef.current) }
    input.click()
  }

  React.useEffect(() => {
    reconcileUploads(kbId, documents)
  }, [kbId, documents, processingUploads, reconcileUploads])

  return { handleUploadClick, uploadFiles }
}

/** Toasts names that already exist at the target path; returns the rest, or null when every file was a duplicate. */
function dropDuplicateUploads(files: File[], documents: DocumentListItem[], targetPath: string): File[] | null {
  const existingNames = new Set(
    documents
      .filter((d) => d.path === targetPath && !d.archived)
      .map((d) => d.filename.toLowerCase()),
  )
  const duplicates = files.filter((f) => existingNames.has(f.name.toLowerCase()))
  if (duplicates.length === 0) return files
  toast.error(`Already exists: ${duplicates.map((f) => f.name).join(', ')}`)
  if (duplicates.length === files.length) return null
  return files.filter((f) => !existingNames.has(f.name.toLowerCase()))
}

function unsupportedFileMessage(ext: string | undefined): string {
  if (ext === 'xls') return 'Legacy .xls files aren\'t supported. Save as .xlsx and upload again.'
  return `${ext ? `.${ext}` : 'Extensionless'} files not yet supported`
}
