import { describe, expect, it } from 'vitest'
import { resolveOnboardingPreview } from './onboarding-preview'

describe('onboarding preview gate', () => {
  it('allows the preview only in development with an explicit flag', () => {
    expect(resolveOnboardingPreview('development', 'true')).toBe(true)
    expect(resolveOnboardingPreview('development', 'false')).toBe(false)
    expect(resolveOnboardingPreview('production', 'true')).toBe(false)
    expect(resolveOnboardingPreview('test', 'true')).toBe(false)
  })
})
