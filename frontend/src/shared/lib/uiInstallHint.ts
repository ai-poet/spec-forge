export const UI_PLAYWRIGHT_INSTALL_HINT =
  'cd backend && source .venv/bin/activate && pip install -e ".[ui]" && playwright install chromium'

export function needsPlaywrightInstall(error: string | null | undefined): boolean {
  if (!error) return false
  const lower = error.toLowerCase()
  return (
    lower.includes('playwright is not installed') ||
    lower.includes('playwright browsers not installed') ||
    lower.includes('pip install')
  )
}
