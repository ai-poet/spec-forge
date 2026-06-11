import { describe, expect, it } from 'vitest'
import type { IterationDetail, IterationSummary } from '../../../shared/lib/types'
import { artifactOptions, comparisonCandidates, defaultArtifactName, diffLineStats } from './artifactCompare'

function iteration(id: string, updatedAt: string): IterationSummary {
  return {
    id,
    project_id: 'project_1',
    epic_id: null,
    project_name: 'demo',
    goal: `goal ${id}`,
    mode: 'real-cli',
    status: 'delivered',
    current_node: null,
    stopped_at_node: null,
    retry_counts: {},
    last_error: null,
    created_at: updatedAt,
    updated_at: updatedAt,
  }
}

function detail(documents: Array<{ name: string; checksum: string }>): IterationDetail {
  return {
    ...iteration('iter_current', '2026-06-10T00:00:00Z'),
    test_command: null,
    graph_next: [],
    documents: documents.map((doc) => ({
      name: doc.name,
      checksum: doc.checksum,
      path: `/tmp/${doc.name}`,
      created_at: '2026-06-10T00:00:00Z',
      updated_at: '2026-06-10T00:00:00Z',
    })),
    events: [],
    runs: [],
    ui_results: [],
  }
}

describe('artifact compare helpers', () => {
  it('sorts comparison candidates by update time and excludes current', () => {
    const items = [
      iteration('iter_a', '2026-06-09T00:00:00Z'),
      iteration('iter_current', '2026-06-11T00:00:00Z'),
      iteration('iter_b', '2026-06-10T00:00:00Z'),
    ]

    expect(comparisonCandidates(items, 'iter_current').map((item) => item.id)).toEqual(['iter_b', 'iter_a'])
  })

  it('orders important artifacts and marks presence', () => {
    const current = detail([
      { name: 'verify_report', checksum: 'a' },
      { name: 'prd', checksum: 'same' },
    ])
    const target = detail([
      { name: 'verify_report', checksum: 'b' },
      { name: 'prd', checksum: 'same' },
      { name: 'delivery_advice', checksum: 'target' },
    ])

    const options = artifactOptions(current, target)

    expect(options.slice(0, 4).map((item) => item.name)).toEqual(['log_summary', 'verify_report', 'delivery_advice', 'ui_report'])
    expect(options.find((item) => item.name === 'verify_report')?.presence).toBe('different')
    expect(options.find((item) => item.name === 'prd')?.presence).toBe('same')
    expect(options.find((item) => item.name === 'delivery_advice')?.presence).toBe('target_only')
    expect(defaultArtifactName(current, target)).toBe('verify_report')
  })

  it('counts line differences without external dependencies', () => {
    expect(diffLineStats('a\nb\nc', 'a\nx\nc\nd')).toEqual({
      current_lines: 3,
      target_lines: 4,
      changed: 1,
      added: 1,
      removed: 0,
      equal: false,
    })
  })
})
