import { describe, expect, it } from 'vitest'
import { needsPlaywrightInstall } from './uiInstallHint'

describe('needsPlaywrightInstall', () => {
  it('detects missing package message', () => {
    expect(needsPlaywrightInstall('Playwright is not installed (pip install)')).toBe(true)
  })

  it('detects missing browsers message', () => {
    expect(needsPlaywrightInstall('Playwright browsers not installed (run: playwright install chromium)')).toBe(true)
  })

  it('returns false for unrelated errors', () => {
    expect(needsPlaywrightInstall('assert_text failed')).toBe(false)
    expect(needsPlaywrightInstall(undefined)).toBe(false)
  })
})
