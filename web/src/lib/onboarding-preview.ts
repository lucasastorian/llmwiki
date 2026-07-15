export function resolveOnboardingPreview(
  nodeEnv: string | undefined,
  previewFlag: string | undefined,
): boolean {
  return nodeEnv === 'development' && previewFlag === 'true'
}

export const ONBOARDING_PREVIEW_ENABLED = resolveOnboardingPreview(
  process.env.NODE_ENV,
  process.env.NEXT_PUBLIC_ONBOARDING_PREVIEW,
)
