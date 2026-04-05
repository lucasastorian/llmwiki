'use client'

import * as React from 'react'
import { Suspense } from 'react'
import { useSearchParams, useRouter } from 'next/navigation'
import { Loader2, Shield, X } from 'lucide-react'
import { createClient } from '@/lib/supabase/client'

function OAuthConsentContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const authorizationId = searchParams.get('authorization_id')

  const [details, setDetails] = React.useState<{
    client_name?: string
    scopes?: string[]
    redirect_uri?: string
  } | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [submitting, setSubmitting] = React.useState(false)

  React.useEffect(() => {
    if (!authorizationId) {
      setError('Missing authorization_id')
      setLoading(false)
      return
    }

    const supabase = createClient()

    supabase.auth.getSession().then(async ({ data: { session } }) => {
      if (!session) {
        // Not logged in — redirect to login, then back here
        const returnUrl = `/oauth/authorize?authorization_id=${authorizationId}`
        router.replace(`/login?returnTo=${encodeURIComponent(returnUrl)}`)
        return
      }

      try {
        const { data, error: fetchError } = await (supabase.auth as any).oauth.getAuthorizationDetails(authorizationId)
        if (fetchError) throw fetchError
        setDetails(data)
      } catch (err: any) {
        setError(err.message || 'Failed to load authorization details')
      } finally {
        setLoading(false)
      }
    })
  }, [authorizationId, router])

  const handleApprove = async () => {
    if (!authorizationId) return
    setSubmitting(true)
    try {
      const supabase = createClient()
      const { data, error: approveError } = await (supabase.auth as any).oauth.approveAuthorization(authorizationId)
      if (approveError) throw approveError
      window.location.href = data.redirect_to
    } catch (err: any) {
      setError(err.message || 'Failed to approve')
      setSubmitting(false)
    }
  }

  const handleDeny = async () => {
    if (!authorizationId) return
    setSubmitting(true)
    try {
      const supabase = createClient()
      const { data, error: denyError } = await (supabase.auth as any).oauth.denyAuthorization(authorizationId)
      if (denyError) throw denyError
      window.location.href = data.redirect_to
    } catch (err: any) {
      setError(err.message || 'Failed to deny')
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <div className="min-h-svh flex items-center justify-center bg-background">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="min-h-svh flex items-center justify-center bg-background p-8">
        <div className="text-center max-w-sm">
          <X className="size-10 text-destructive mx-auto mb-4" />
          <h1 className="text-lg font-semibold mb-2">Authorization Error</h1>
          <p className="text-sm text-muted-foreground">{error}</p>
        </div>
      </div>
    )
  }

  const clientName = details?.client_name || 'An application'

  return (
    <div className="min-h-svh flex items-center justify-center bg-background p-8">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-muted mb-4">
            <Shield className="size-5 text-foreground" />
          </div>
          <h1 className="text-xl font-semibold tracking-tight">Authorize access</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            <span className="font-medium text-foreground">{clientName}</span> wants to
            access your LLM Wiki account.
          </p>
        </div>

        <div className="rounded-lg border border-border p-4 mb-6">
          <p className="text-sm font-medium mb-2">This will allow it to:</p>
          <ul className="space-y-1.5 text-sm text-muted-foreground">
            <li className="flex items-start gap-2">
              <span className="text-green-500 mt-0.5">&#10003;</span>
              Read your documents and wiki pages
            </li>
            <li className="flex items-start gap-2">
              <span className="text-green-500 mt-0.5">&#10003;</span>
              Search across your knowledge bases
            </li>
            <li className="flex items-start gap-2">
              <span className="text-green-500 mt-0.5">&#10003;</span>
              Create and edit wiki pages
            </li>
          </ul>
        </div>

        <div className="flex gap-3">
          <button
            onClick={handleDeny}
            disabled={submitting}
            className="flex-1 rounded-lg border border-input bg-background px-4 py-2.5 text-sm font-medium hover:bg-accent transition-colors cursor-pointer disabled:opacity-50"
          >
            Deny
          </button>
          <button
            onClick={handleApprove}
            disabled={submitting}
            className="flex-1 flex items-center justify-center gap-2 rounded-lg bg-foreground text-background px-4 py-2.5 text-sm font-medium hover:opacity-90 transition-opacity cursor-pointer disabled:opacity-50"
          >
            {submitting && <Loader2 size={14} className="animate-spin" />}
            Approve
          </button>
        </div>

        <p className="mt-4 text-[11px] text-center text-muted-foreground/50">
          You can revoke access at any time from Settings.
        </p>
      </div>
    </div>
  )
}

export default function OAuthConsentPage() {
  return (
    <Suspense>
      <OAuthConsentContent />
    </Suspense>
  )
}
