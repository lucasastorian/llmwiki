export interface KnowledgeBase {
  id: string
  user_id: string
  name: string
  slug: string
  description: string | null
  source_count: number
  wiki_page_count: number
  created_at: string
  updated_at: string
  kind?: 'wiki' | 'course'
  lesson_count?: number
  lessons_completed?: number
}

export interface Document {
  id: string
  knowledge_base_id: string
  user_id: string
  filename: string
  title: string | null
  path: string
  file_type: string
  file_size: number
  status: string
  page_count: number | null
  content: string | null
  tags: string[]
  date: string | null
  metadata: Record<string, unknown> | null
  error_message: string | null
  url: string | null
  version: number
  document_number: number | null
  sort_order: number | null
  archived: boolean
  created_at: string
  updated_at: string
}

export type DocumentListItem = Omit<Document, 'content'>

export type KnowledgeBaseEventType =
  | 'tracking.started'
  | 'wiki.created'
  | 'page.created'
  | 'page.updated'
  | 'page.archived'
  | 'page.restored'
  | 'page.deleted'
  | 'source.added'
  | 'source.updated'
  | 'source.deleted'

export type KnowledgeBaseEventChange =
  | 'content'
  | 'title'
  | 'path'
  | 'tags'
  | 'date'
  | 'properties'

export interface KnowledgeBaseEvent {
  id: string
  event_type: KnowledgeBaseEventType
  subject_kind: 'wiki' | 'wiki_page' | 'source'
  document_id: string | null
  document_number: number | null
  document_version: number | null
  subject_title: string
  subject_path: string | null
  metadata: {
    changes?: KnowledgeBaseEventChange[]
    file_type?: string
    file_size?: number
    [key: string]: unknown
  }
  occurred_at: string
}

export interface KnowledgeBaseEventsPage {
  items: KnowledgeBaseEvent[]
  next_cursor: string | null
}

export type PropertyType = 'text' | 'number' | 'date' | 'checkbox' | 'select' | 'url'

export interface TypedProperty {
  type: PropertyType
  value: string | number | boolean | null
  options?: string[]
}

export type PropertyMap = Record<string, TypedProperty>

export interface WikiNode {
  title: string
  path?: string
  docNumber?: number | null
  children?: WikiNode[]
  // Course mode only — derived from the lesson doc's metadata.course.status + tree order.
  status?: 'complete' | 'in_progress' | 'not_started'
  locked?: boolean
}
