import type { EnvironmentCheckItem, EnvironmentCheckStatus } from '../../../shared/lib/types'

const STATUS_WEIGHT: Record<EnvironmentCheckStatus, number> = {
  error: 0,
  warning: 1,
  ok: 2,
}

export function sortEnvironmentChecks(checks: EnvironmentCheckItem[]): EnvironmentCheckItem[] {
  return [...checks].sort((left, right) => {
    const status = STATUS_WEIGHT[left.status] - STATUS_WEIGHT[right.status]
    return status || left.label.localeCompare(right.label)
  })
}

export function summarizeEnvironmentChecks(checks: EnvironmentCheckItem[]): string {
  const errors = checks.filter((check) => check.status === 'error').length
  const warnings = checks.filter((check) => check.status === 'warning').length
  if (errors) return `${errors} 项需要处理`
  if (warnings) return `${warnings} 项需要留意`
  return checks.length ? '全部通过' : '等待检测'
}
