import type { IterationDetail, SemanticEvent } from '../../../shared/lib/types'
import {
  buildMacroFlow,
  buildMicroFlow,
  compressToMilestones,
  inferDefaultRunId,
} from './buildAgentFlow'

function makeEvent(partial: Partial<SemanticEvent> & Pick<SemanticEvent, 'id' | 'type' | 'node' | 'title' | 'message'>): SemanticEvent {
  return {
    severity: 'info',
    created_at: '2026-05-30T10:00:00.000Z',
    raw: { id: partial.id, type: partial.type, payload: {}, created_at: '2026-05-30T10:00:00.000Z' },
    ...partial,
  }
}

function makeDetail(partial: Partial<IterationDetail>): IterationDetail {
  return {
    id: 'iter_test',
    project_id: 'proj_test',
    epic_id: null,
    project_name: 'demo',
    goal: 'test',
    mode: 'dry-run',
    status: 'testing',
    current_node: 'tester',
    stopped_at_node: null,
    retry_counts: {},
    last_error: null,
    created_at: '2026-05-30T09:00:00.000Z',
    updated_at: '2026-05-30T10:00:00.000Z',
    test_command: null,
    graph_next: [],
    documents: [],
    events: [],
    runs: [],
    ui_results: [],
    ...partial,
  }
}

describe('buildMacroFlow', () => {
  it('adds coder retry edge when coder_tester > 0', () => {
    const model = buildMacroFlow(makeDetail({ retry_counts: { coder_tester: 2 } }))
    expect(model.edges.some((edge) => edge.kind === 'retry_coder')).toBe(true)
  })

  it('adds tester self loop when tester_self > 0', () => {
    const model = buildMacroFlow(makeDetail({ retry_counts: { tester_self: 1 } }))
    expect(model.edges.some((edge) => edge.kind === 'retry_self')).toBe(true)
  })
})

describe('compressToMilestones', () => {
  it('merges consecutive progress events', () => {
    const milestones = compressToMilestones([
      makeEvent({ id: '1', type: 'node.started', node: 'tester', title: '启动', message: 'a' }),
      makeEvent({ id: '2', type: 'node.progress', node: 'tester', title: '解析中', message: 'b' }),
      makeEvent({ id: '3', type: 'node.progress', node: 'tester', title: '写报告', message: 'c' }),
      makeEvent({ id: '4', type: 'node.completed', node: 'tester', title: '完成', message: 'd', severity: 'success' }),
    ])
    expect(milestones).toHaveLength(3)
    expect(milestones[1].label).toBe('写报告')
    expect(milestones[1].eventIds).toEqual(['2', '3'])
  })
})

describe('buildMicroFlow', () => {
  it('splits tester rounds into tabs', () => {
    const detail = makeDetail({
      events: [
        { id: 'e1', type: 'node.started', payload: { node: 'tester', title: 'r1', message: 'm' }, created_at: '2026-05-30T10:00:00.000Z' },
        { id: 'e2', type: 'node.started', payload: { node: 'tester', title: 'r2', message: 'm' }, created_at: '2026-05-30T10:05:00.000Z' },
      ],
    })
    const micro = buildMicroFlow(detail, 'tester', { reviewMode: true, stepLive: false })
    expect(micro.runs).toHaveLength(2)
    expect(micro.defaultRunId).toBe(micro.runs[micro.runs.length - 1]?.id ?? null)
  })
})

describe('inferDefaultRunId', () => {
  it('selects last run in review mode', () => {
    const runs = [
      { id: 'a', label: '1', isCurrent: false, milestones: [], edges: [] },
      { id: 'b', label: '2', isCurrent: false, milestones: [], edges: [] },
    ]
    expect(inferDefaultRunId(runs, true, false)).toBe('b')
  })
})
