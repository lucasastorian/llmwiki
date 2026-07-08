'use client'

import * as React from 'react'
import { toast } from 'sonner'
import { apiFetch } from '@/lib/api'
import { useUserStore } from '@/stores'
import type { DocumentListItem } from '@/lib/types'

type LessonStatus = 'complete' | 'not_started'

// Persists per-lesson completion in the doc's metadata.course (reuses the existing
// PATCH /v1/documents/{id} merge — no course-specific backend). Optimistic; a refetch reconciles.
export function useCourseProgress(
  setDocuments: React.Dispatch<React.SetStateAction<DocumentListItem[]>>,
) {
  const token = useUserStore((s) => s.accessToken)

  const setStatus = React.useCallback(
    async (docId: string, status: LessonStatus) => {
      const completed_at = status === 'complete' ? new Date().toISOString() : null
      setDocuments((prev) =>
        prev.map((d) => {
          if (d.id !== docId) return d
          const meta = (d.metadata ?? {}) as Record<string, unknown>
          return { ...d, metadata: { ...meta, course: { status, completed_at } } }
        }),
      )
      if (!token) return
      try {
        await apiFetch(`/v1/documents/${docId}`, token, {
          method: 'PATCH',
          body: JSON.stringify({ metadata: { course: { status, completed_at } } }),
        })
      } catch {
        // The next documents refetch reverts the optimistic state — say so.
        toast.error("Progress didn't save — check your connection and try again")
      }
    },
    [token, setDocuments],
  )

  const markComplete = React.useCallback((docId: string) => setStatus(docId, 'complete'), [setStatus])
  const markIncomplete = React.useCallback((docId: string) => setStatus(docId, 'not_started'), [setStatus])

  return { markComplete, markIncomplete }
}
