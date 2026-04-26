import type { Metadata } from 'next'
import { terms } from '@/content/terms'
import { PolicyPage } from '@/components/PolicyPage'

export const metadata: Metadata = {
  title: 'Terms of Service | LLM Wiki',
  description: 'Terms of Service for LLM Wiki.',
}

export default function TermsPage() {
  return <PolicyPage content={terms} />
}
