import { describe, expect, it } from 'vitest'
import { needsCuaInstall, needsPlaywrightInstall, showCuaInstallGuide, showPlaywrightInstallGuide } from './uiInstallHint'

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

describe('needsCuaInstall', () => {
  it('detects CuaDriver daemon errors', () => {
    expect(needsCuaInstall('CuaDriver daemon unavailable')).toBe(true)
  })

  it('detects permission errors', () => {
    expect(needsCuaInstall('CuaDriver permissions missing: Accessibility')).toBe(true)
  })
})

describe('install guides', () => {
  it('shows playwright guide for selector web warnings', () => {
    const results = [
      {
        status: 'warning' as const,
        error: 'Playwright is not installed (pip install specforge[ui])',
        kind: 'web' as const,
      },
    ]
    expect(showPlaywrightInstallGuide(results)).toBe(true)
    expect(showCuaInstallGuide(results)).toBe(false)
  })

  it('shows cua guide for native warnings', () => {
    const results = [
      {
        status: 'warning' as const,
        error: 'CuaDriver unavailable for native UI',
        kind: 'native' as const,
        driver: 'cua' as const,
      },
    ]
    expect(showCuaInstallGuide(results)).toBe(true)
  })

  it('detects single-session busy message', () => {
    expect(needsCuaInstall('CuaDriver busy: only one UI session allowed (held by iter-1)')).toBe(true)
  })
})
