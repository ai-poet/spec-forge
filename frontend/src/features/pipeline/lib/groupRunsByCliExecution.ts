import type { IterationDetail, NodeRunRecord, SemanticEvent } from '../../../shared/lib/types'
import type { PipelineStepKey } from './pipelineSteps'
import { nodesForStep } from './pipelineSteps'

export type LoopKind = '②a' | '②b' | '③' | '①'

export interface SemanticRunLabel {
  round: number
  loop?: LoopKind
  loopHint?: string
  startedAt: string
  status: 'success' | 'failed' | 'running'
}

export interface CliRunGroup {
  id: string
  label: string
  events: SemanticEvent[]
  isCurrent: boolean
  semantic: SemanticRunLabel
  separatorBefore?: string
  bridgeLoop?: { kind: LoopKind; hint: string }
}

export interface GroupedCliRuns {
  groups: CliRunGroup[]
  totalEvents: number
  roundCount: number
}

const LOOP_EVENT_MAP: Record<string, { kind: LoopKind; hint: string }> = {
  'tester.retry_to_coder': { kind: '②a', hint: '验证失败 → 回到实现节点' },
  'tester.failed_retry': { kind: '②a', hint: '验证失败 → 回到实现节点' },
  'tester.retry_to_self': { kind: '②b', hint: '验证产物不合格 → Tester 自修' },
  'planner_verify.rejected': { kind: '③', hint: '规格复核驳回 → 重新验证' },
  'clarification.answered': { kind: '①', hint: '实现澄清 → Planner 回答' },
}

function runNodesForStep(stepKey: PipelineStepKey): string[] {
  switch (stepKey) {
    case 'planner':
      return ['planner', 'planner_clarification']
    case 'coder':
      return ['coder', 'coder_retry']
    case 'tester':
      return ['tester']
    case 'integrity_check':
      return ['integrity_check']
    case 'planner_verify':
      return ['planner_verify']
    default:
      return nodesForStep(stepKey)
  }
}

function primaryNodeForStep(stepKey: PipelineStepKey): string {
  switch (stepKey) {
    case 'planner':
      return 'planner'
    case 'coder':
      return 'coder'
    case 'tester':
      return 'tester'
    case 'integrity_check':
      return 'integrity_check'
    case 'planner_verify':
      return 'planner_verify'
    default:
      return stepKey
  }
}

function chronological<T extends { created_at: string }>(items: T[]): T[] {
  return [...items].sort((left, right) => left.created_at.localeCompare(right.created_at))
}

function filterStageEvents(events: SemanticEvent[], stepKey: PipelineStepKey): SemanticEvent[] {
  const nodes = new Set(nodesForStep(stepKey))
  return events.filter((event) => nodes.has(event.node))
}

function stageRuns(detail: IterationDetail, stepKey: PipelineStepKey): NodeRunRecord[] {
  const allowed = new Set(runNodesForStep(stepKey))
  return [...detail.runs.filter((run) => allowed.has(run.node))].sort(
    (left, right) => left.started_at.localeCompare(right.started_at),
  )
}

function runStatus(run: NodeRunRecord | undefined, isCurrent: boolean): SemanticRunLabel['status'] {
  if (isCurrent && !run?.finished_at) return 'running'
  if (run?.status === 'failed') return 'failed'
  return 'success'
}

function detectLoopBetween(
  detail: IterationDetail,
  after: string,
  before: string,
): { kind: LoopKind; hint: string } | undefined {
  for (const raw of detail.events) {
    if (raw.created_at <= after || raw.created_at >= before) continue
    const mapped = LOOP_EVENT_MAP[raw.type]
    if (mapped) return mapped
    const payload = typeof raw.payload === 'object' && raw.payload ? raw.payload as { retry_target?: string } : undefined
    if (raw.type === 'tester.retry_to_coder' || payload?.retry_target === 'coder') {
      return LOOP_EVENT_MAP['tester.retry_to_coder']
    }
    if (raw.type === 'tester.retry_to_self' || payload?.retry_target === 'tester') {
      return LOOP_EVENT_MAP['tester.retry_to_self']
    }
  }
  return undefined
}

function assignOrphans(
  orphans: SemanticEvent[],
  runs: NodeRunRecord[],
  buckets: Map<string, SemanticEvent[]>,
): void {
  if (!orphans.length) return

  const sortedRuns = [...runs]
  for (const event of chronological(orphans)) {
    let targetId: string | null = null

    for (const run of sortedRuns) {
      if (event.created_at >= run.started_at) {
        targetId = run.id
      }
    }

    if (!targetId && sortedRuns.length) {
      targetId = sortedRuns[0].id
    }

    if (!targetId) {
      targetId = 'synthetic-stage'
      if (!buckets.has(targetId)) buckets.set(targetId, [])
    }

    buckets.get(targetId)?.push(event)
  }
}

function formatRunLabel(semantic: SemanticRunLabel, isCurrent: boolean): string {
  const base = semantic.loop
    ? `第 ${semantic.round} 轮 · ${semantic.loop}${semantic.loopHint ? ` ${semantic.loopHint.split(' → ')[0]}` : ''}`
    : `第 ${semantic.round} 轮`
  return isCurrent ? `${base}（当前）` : base
}

export function groupRunsByCliExecution(
  detail: IterationDetail,
  stepKey: PipelineStepKey,
  events: SemanticEvent[],
  options: { reviewMode: boolean; stepLive: boolean },
): GroupedCliRuns {
  const filtered = filterStageEvents(events, stepKey)
  const runs = stageRuns(detail, stepKey)
  const allEvents = chronological(filtered)

  if (!allEvents.length && !runs.length) {
    return { groups: [], totalEvents: 0, roundCount: 0 }
  }

  const buckets = new Map<string, SemanticEvent[]>()
  const runById = new Map(runs.map((run) => [run.id, run]))
  const orphans: SemanticEvent[] = []

  for (const run of runs) {
    buckets.set(run.id, [])
  }

  for (const event of allEvents) {
    if (event.run_id && buckets.has(event.run_id)) {
      buckets.get(event.run_id)!.push(event)
      continue
    }
    orphans.push(event)
  }

  assignOrphans(orphans, runs, buckets)

  if (!runs.length) {
    buckets.set('synthetic-stage', allEvents)
  }

  const groupEntries = runs.length
    ? runs.map((run) => ({ id: run.id, run, events: chronological(buckets.get(run.id) ?? []) }))
    : [{ id: 'synthetic-stage', run: undefined, events: chronological(buckets.get('synthetic-stage') ?? allEvents) }]

  const nonEmpty = groupEntries.filter((entry) => entry.events.length > 0 || entry.run)
  const entries = nonEmpty.length ? nonEmpty : groupEntries

  const groups: CliRunGroup[] = entries.map((entry, index) => {
    const round = index + 1
    const isCurrent = options.stepLive && !options.reviewMode && index === entries.length - 1
    const startedAt = entry.run?.started_at ?? entry.events[0]?.created_at ?? detail.updated_at
    const semantic: SemanticRunLabel = {
      round,
      startedAt,
      status: runStatus(entry.run, isCurrent),
    }

    let bridgeLoop: { kind: LoopKind; hint: string } | undefined
    if (index > 0) {
      const prev = entries[index - 1]
      const prevEnd = prev.events[prev.events.length - 1]?.created_at ?? prev.run?.finished_at ?? prev.run?.started_at ?? startedAt
      bridgeLoop = detectLoopBetween(detail, prevEnd, startedAt)
      if (bridgeLoop) {
        semantic.loop = bridgeLoop.kind
        semantic.loopHint = bridgeLoop.hint
      }
    }

    return {
      id: entry.id,
      label: formatRunLabel(semantic, isCurrent),
      events: entry.events,
      isCurrent,
      semantic,
      bridgeLoop,
      separatorBefore: bridgeLoop ? `${bridgeLoop.kind} ${bridgeLoop.hint}` : undefined,
    }
  })

  return {
    groups,
    totalEvents: allEvents.length,
    roundCount: groups.length,
  }
}

export function stepRetrySummary(detail: IterationDetail | null, stepKey: PipelineStepKey): string {
  if (!detail) return ''
  const retry = detail.retry_counts ?? {}
  const parts: string[] = []
  if (stepKey === 'coder') {
    if (retry.coder_planner_clarify) parts.push(`①×${retry.coder_planner_clarify}`)
    if (retry.coder_tester) parts.push(`②a×${retry.coder_tester}`)
  }
  if (stepKey === 'tester') {
    if (retry.coder_tester) parts.push(`②a×${retry.coder_tester}`)
    if (retry.tester_self) parts.push(`②b×${retry.tester_self}`)
    if (retry.planner_verify_reject) parts.push(`③×${retry.planner_verify_reject}`)
  }
  if (stepKey === 'planner' && retry.coder_planner_clarify) {
    parts.push(`①×${retry.coder_planner_clarify}`)
  }
  return parts.join(' ')
}
