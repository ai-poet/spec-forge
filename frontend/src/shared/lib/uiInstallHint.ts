export const UI_PLAYWRIGHT_INSTALL_HINT =
  'cd backend && source .venv/bin/activate && pip install -e ".[ui]" && playwright install chromium'

export const UI_CUA_INSTALL_HINT =
  'python computer-use/backend/install_cua_driver.py'

export function needsPlaywrightInstall(error: string | null | undefined): boolean {
  if (!error) return false
  const lower = error.toLowerCase()
  return (
    lower.includes('playwright is not installed') ||
    lower.includes('playwright browsers not installed') ||
    (lower.includes('pip install') && lower.includes('playwright'))
  )
}

export function needsCuaInstall(error: string | null | undefined): boolean {
  if (!error) return false
  const lower = error.toLowerCase()
  return (
    lower.includes('cuadriver') ||
    lower.includes('cua-driver') ||
    lower.includes('cua driver') ||
    lower.includes('permissions missing') ||
    lower.includes('accessibility') ||
    lower.includes('native ui') ||
    lower.includes('install_cua_driver') ||
    lower.includes('single-session') ||
    lower.includes('only one ui session')
  )
}

export function showPlaywrightInstallGuide(results: Array<{ status: string; error?: string | null }>): boolean {
  return results.some((result) => result.status === 'warning' && needsPlaywrightInstall(result.error))
}

export function showCuaInstallGuide(results: Array<{ status: string; error?: string | null; kind?: string; driver?: string | null }>): boolean {
  return results.some(
    (result) =>
      result.status === 'warning' &&
      needsCuaInstall(result.error) &&
      !needsPlaywrightInstall(result.error),
  )
}
