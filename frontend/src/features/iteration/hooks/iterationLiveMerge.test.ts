import type { IterationDetail } from '../../../shared/lib/types'
import { LIVE_CLI_MAX_CHARS, mergeLiveCliOutput, mergeLiveEvent } from './iterationLiveMerge'

function makeDetail(partial: Partial<IterationDetail> = {}): IterationDetail {
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
    live_cli: null,
    ...partial,
  }
}

describe('iteration live merge', () => {
  it('appends event-only messages and ignores duplicates', () => {
    const event = {
      id: 'evt_1',
      type: 'node.progress',
      payload: { node: 'coder', title: '运行中', message: 'working' },
      created_at: '2026-05-30T10:00:00.000Z',
    }
    const first = mergeLiveEvent(makeDetail(), event)
    const second = mergeLiveEvent(first, event)

    expect(first?.events).toHaveLength(1)
    expect(second?.events).toHaveLength(1)
  })

  it('merges cli output chunks and trims live buffer', () => {
    const large = 'a'.repeat(LIVE_CLI_MAX_CHARS + 100)
    const detail = mergeLiveCliOutput(makeDetail(), { node: 'coder', stream: 'stdout', chunk: large })

    expect(detail?.live_cli?.stdout.length).toBe(LIVE_CLI_MAX_CHARS)
    expect(detail?.live_cli?.stdout.startsWith('a')).toBe(true)
    const withStderr = mergeLiveCliOutput(detail, { node: 'coder', stream: 'stderr', chunk: 'err' })
    expect(withStderr?.live_cli?.stderr).toBe('err')
  })
})
