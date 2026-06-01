import type { IterationDetail, SemanticEvent } from '../../../shared/lib/types'
import { groupRunsByCliExecution } from './groupRunsByCliExecution'
import { buildMicroFlow, compressToMilestones } from './buildAgentFlow'

function makeEvent(partial: Partial<SemanticEvent> & Pick<SemanticEvent, 'id' | 'type' | 'node' | 'title' | 'message'>): SemanticEvent {
  return {
    severity: 'info',
    created_at: '2026-05-30T10:00:00.000Z',
    raw: { id: partial.id, type: partial.type, payload: {}, created_at: partial.created_at ?? '2026-05-30T10:00:00.000Z' },
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
    current_node: 'code_tester',
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

describe('groupRunsByCliExecution', () => {
  it('merges orphan node.started with run_id events into one round', () => {
    const detail = makeDetail({
      runs: [{
        id: 'run-1',
        node: 'code_tester',
        status: 'success',
        command: 'code_tester',
        stdout: '',
        stderr: '',
        exit_code: 0,
        started_at: '2026-05-30T10:00:01.000Z',
        finished_at: '2026-05-30T10:00:30.000Z',
      }],
    })
    const events = [
      makeEvent({ id: '1', type: 'node.started', node: 'code_tester', title: '启动', message: 'a', created_at: '2026-05-30T10:00:00.500Z' }),
      makeEvent({ id: '2', type: 'node.progress', node: 'code_tester', title: '解析', message: 'b', run_id: 'run-1', created_at: '2026-05-30T10:00:02.000Z' }),
      makeEvent({ id: '3', type: 'node.completed', node: 'code_tester', title: '完成', message: 'c', run_id: 'run-1', severity: 'success', created_at: '2026-05-30T10:00:25.000Z' }),
    ]
    const grouped = groupRunsByCliExecution(detail, 'code_tester', events, { reviewMode: false, stepLive: false })
    expect(grouped.roundCount).toBe(1)
    expect(grouped.groups[0].events).toHaveLength(3)
  })

  it('labels second round with loop when retry event between runs', () => {
    const detail = makeDetail({
      runs: [
        {
          id: 'run-1',
          node: 'code_tester',
          status: 'failed',
          command: 'code_tester',
          stdout: '',
          stderr: '',
          exit_code: 1,
          started_at: '2026-05-30T10:00:00.000Z',
          finished_at: '2026-05-30T10:00:10.000Z',
        },
        {
          id: 'run-2',
          node: 'code_tester',
          status: 'success',
          command: 'code_tester',
          stdout: '',
          stderr: '',
          exit_code: 0,
          started_at: '2026-05-30T10:05:00.000Z',
          finished_at: '2026-05-30T10:05:30.000Z',
        },
      ],
      events: [
        { id: 'retry', type: 'tester.retry_to_self', payload: { retry_target: 'code_tester' }, created_at: '2026-05-30T10:04:00.000Z' },
      ],
    })
    const events = [
      makeEvent({ id: '1', type: 'node.started', node: 'code_tester', title: 'r1', message: 'm', run_id: 'run-1', created_at: '2026-05-30T10:00:01.000Z' }),
      makeEvent({ id: '2', type: 'node.started', node: 'code_tester', title: 'r2', message: 'm', run_id: 'run-2', created_at: '2026-05-30T10:05:01.000Z' }),
    ]
    const grouped = groupRunsByCliExecution(detail, 'code_tester', events, { reviewMode: true, stepLive: false })
    expect(grouped.roundCount).toBe(2)
    expect(grouped.groups[1].bridgeLoop?.kind).toBe('②b')
  })
})

describe('compressToMilestones artifacts', () => {
  it('merges consecutive artifact events', () => {
    const milestones = compressToMilestones([
      makeEvent({ id: '1', type: 'node.started', node: 'code_tester', title: '启动', message: 'a' }),
      makeEvent({ id: '2', type: 'artifact.created', node: 'code_tester', title: 'a1', message: 'm', document: 'verify_report' }),
      makeEvent({ id: '3', type: 'artifact.created', node: 'code_tester', title: 'a2', message: 'm', document: 'ui_report' }),
      makeEvent({ id: '4', type: 'artifact.created', node: 'code_tester', title: 'a3', message: 'm', document: 'tests/adversarial/x.ts' }),
      makeEvent({ id: '5', type: 'node.completed', node: 'code_tester', title: '完成', message: 'd', severity: 'success' }),
    ])
    expect(milestones).toHaveLength(3)
    expect(milestones[1].label).toBe('产物写入（3 项）')
    expect(milestones[1].events).toHaveLength(3)
  })
})

describe('buildMicroFlow with runs', () => {
  it('produces one round per cli run', () => {
    const detail = makeDetail({
      runs: [
        {
          id: 'run-1',
          node: 'code_tester',
          status: 'success',
          command: 'code_tester',
          stdout: '',
          stderr: '',
          exit_code: 0,
          started_at: '2026-05-30T10:00:00.000Z',
          finished_at: '2026-05-30T10:00:30.000Z',
        },
        {
          id: 'run-2',
          node: 'code_tester',
          status: 'success',
          command: 'code_tester',
          stdout: '',
          stderr: '',
          exit_code: 0,
          started_at: '2026-05-30T10:05:00.000Z',
          finished_at: '2026-05-30T10:05:30.000Z',
        },
      ],
      events: [
        { id: 'e1', type: 'node.started', payload: { node: 'code_tester', title: 's', message: 'm' }, created_at: '2026-05-30T10:00:00.500Z' },
        { id: 'e2', type: 'node.progress', payload: { node: 'code_tester', title: 'p', message: 'm', run_id: 'run-1' }, created_at: '2026-05-30T10:00:05.000Z' },
        { id: 'e3', type: 'node.started', payload: { node: 'code_tester', title: 's2', message: 'm' }, created_at: '2026-05-30T10:05:00.500Z' },
        { id: 'e4', type: 'node.progress', payload: { node: 'code_tester', title: 'p2', message: 'm', run_id: 'run-2' }, created_at: '2026-05-30T10:05:05.000Z' },
      ],
    })
    const micro = buildMicroFlow(detail, 'code_tester', { reviewMode: true, stepLive: false })
    expect(micro.runs).toHaveLength(2)
    expect(micro.defaultRunId).toBe('run-2')
  })
})
