import { describe, expect, it } from 'vitest'
import type { EnvironmentCheckItem } from '../../../shared/lib/types'
import { sortEnvironmentChecks, summarizeEnvironmentChecks } from './environmentChecks'

function check(partial: Partial<EnvironmentCheckItem> & Pick<EnvironmentCheckItem, 'id' | 'label' | 'status'>): EnvironmentCheckItem {
  return {
    message: partial.message ?? 'm',
    detail: partial.detail ?? null,
    hint: partial.hint ?? null,
    ...partial,
  }
}

describe('sortEnvironmentChecks', () => {
  it('orders errors, warnings, then ok checks', () => {
    const sorted = sortEnvironmentChecks([
      check({ id: 'ok', label: 'Ok', status: 'ok' }),
      check({ id: 'warning', label: 'Warning', status: 'warning' }),
      check({ id: 'error', label: 'Error', status: 'error' }),
    ])
    expect(sorted.map((item) => item.id)).toEqual(['error', 'warning', 'ok'])
  })
})

describe('summarizeEnvironmentChecks', () => {
  it('prefers error count over warnings', () => {
    expect(summarizeEnvironmentChecks([
      check({ id: 'a', label: 'A', status: 'warning' }),
      check({ id: 'b', label: 'B', status: 'error' }),
    ])).toBe('1 项需要处理')
  })

  it('summarizes warnings and passing checks', () => {
    expect(summarizeEnvironmentChecks([check({ id: 'a', label: 'A', status: 'warning' })])).toBe('1 项需要留意')
    expect(summarizeEnvironmentChecks([check({ id: 'b', label: 'B', status: 'ok' })])).toBe('全部通过')
    expect(summarizeEnvironmentChecks([])).toBe('等待检测')
  })
})
