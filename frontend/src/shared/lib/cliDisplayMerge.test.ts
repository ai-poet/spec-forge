import { describe, expect, it } from 'vitest'
import { mergeCliDisplayEvents } from './cliDisplayMerge'
import type { SemanticEvent } from './types'

function event(partial: Partial<SemanticEvent>): SemanticEvent {
  return {
    id: partial.id ?? '1',
    type: 'cli.display',
    node: 'prd_planner',
    title: 't',
    message: partial.message ?? 'm',
    severity: 'info',
    created_at: partial.created_at ?? '2026-01-01',
    phase: partial.phase,
    item_id: partial.item_id,
    preview: partial.preview,
    raw: partial.raw ?? { id: 'e', type: 'cli.display', payload: {}, created_at: '2026-01-01' },
  }
}

describe('mergeCliDisplayEvents', () => {
  it('merges text deltas with the same item_id', () => {
    const merged = mergeCliDisplayEvents([
      event({ id: '1', phase: 'text', item_id: '0', preview: 'hel', created_at: 'a' }),
      event({ id: '2', phase: 'text', item_id: '0', preview: 'lo', created_at: 'b' }),
    ])
    expect(merged).toHaveLength(1)
    expect(merged[0].preview).toBe('hello')
    expect(merged[0].id).toBe('2')
  })
})
