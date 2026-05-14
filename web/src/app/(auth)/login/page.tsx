import type { Metadata } from 'next'
import { LoginForm } from './LoginForm'

export const metadata: Metadata = {
  title: 'Sign In | LLM Wiki',
  description: 'Sign in to LLM Wiki to manage your knowledge bases and wikis.',
  openGraph: {
    title: 'Sign In | LLM Wiki',
    description: 'Sign in to LLM Wiki to manage your knowledge bases and wikis.',
  },
}

export default function LoginPage() {
  return <LoginForm />
}
