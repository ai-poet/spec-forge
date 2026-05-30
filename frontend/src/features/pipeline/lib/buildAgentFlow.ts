import type { EventSeverity, IterationDetail, SemanticEvent } from '../../../shared/lib/types'
import { isAgentActivity, presentEvent } from '../../../shared/lib/presentation'
import { groupAgentActivities } from './groupAgentRuns'
import { PIPELINE_STEPS, pipelineStepState, type PipelineStepKey } from './pipelineSteps'

export type FlowNodeState = 'complete' | 'active' | 'waiting' | 'idle' | 'failed'
export type FlowEdgeKind = 'forward' | 'retry_coder' | 'retry_self' | 'verify_reject' | 'clarify'

export interface FlowNode {
  id: string
  label: string
  state: FlowNodeState
  stepKey?: PipelineStepKey
  severity?: EventSeverity
  eventIds?: string[]
  event?: SemanticEvent
  isLive?: boolean
}

export interface FlowEdge {
  id: string
  from: string
  to: string
  kind: FlowEdgeKind
  label?: string
}

export interface MacroFlowModel {
  nodes: FlowNode[]
  edges: FlowEdge[]
}

export interface MicroRunModel {
  id: string
  label: string
  isCurrent: boolean
  separatorBefore?: string
  milestones: FlowNode[]
  edges: FlowEdge[]
}

export interface MicroFlowModel {
  runs: MicroRunModel[]
  defaultRunId: string | null
  defaultMilestoneId: string | null
}

function stepNodeId(stepKey: PipelineStepKey): string {
  return `step:${stepKey}`
}

function hasRetryEvent(detail: IterationDetail, type: string): boolean {
  return detail.events.some((event) => event.type === type)
}

export function buildMacroFlow(detail: IterationDetail | null): MacroFlowModel {
  if (!detail) {
    return { nodes: [], edges: [] }
  }

  const nodes: FlowNode[] = PIPELINE_STEPS.map((step) => {
    const state = pipelineStepState(step.key, detail) as FlowNodeState
    const failed = state === 'idle' && detail.last_error
      && (step.key === 'tester' || step.key === 'coder' || step.key === 'planner')
    return {
      id: stepNodeId(step.key),
      label: step.label,
      state: failed ? 'failed' : state,
      stepKey: step.key,
    }
  })

  const edges: FlowEdge[] = []
  for (let index = 0; index < PIPELINE_STEPS.length - 1; index += 1) {
    const from = PIPELINE_STEPS[index].key
    const to = PIPELINE_STEPS[index + 1].key
    edges.push({
      id: `forward:${from}->${to}`,
      from: stepNodeId(from),
      to: stepNodeId(to),
      kind: 'forward',
    })
  }

  const retry = detail.retry_counts ?? {}
  if ((retry.coder_planner_clarify ?? 0) > 0 || hasRetryEvent(detail, 'clarification.answered')) {
    edges.push({
      id: 'clarify:coder->planner',
      from: stepNodeId('coder'),
      to: stepNodeId('planner'),
      kind: 'clarify',
      label: '① 澄清',
    })
  }
  if ((retry.coder_tester ?? 0) > 0 || hasRetryEvent(detail, 'tester.retry_to_coder') || hasRetryEvent(detail, 'tester.failed_retry')) {
    edges.push({
      id: 'retry:coder->tester',
      from: stepNodeId('tester'),
      to: stepNodeId('coder'),
      kind: 'retry_coder',
      label: '②a',
    })
  }
  if ((retry.tester_self ?? 0) > 0 || hasRetryEvent(detail, 'tester.retry_to_self')) {
    edges.push({
      id: 'retry:tester->tester',
      from: stepNodeId('tester'),
      to: stepNodeId('tester'),
      kind: 'retry_self',
      label: '②b',
    })
  }
  if ((retry.planner_verify_reject ?? 0) > 0 || hasRetryEvent(detail, 'planner_verify.rejected')) {
    edges.push({
      id: 'retry:planner_verify->tester',
      from: stepNodeId('planner_verify'),
      to: stepNodeId('tester'),
      kind: 'verify_reject',
      label: '③',
    })
  }

  return { nodes, edges }
}

type MilestoneKind = 'started' | 'progress' | 'artifact' | 'fallback' | 'terminal'

function milestoneKind(event: SemanticEvent): MilestoneKind {
  if (event.type === 'node.started') return 'started'
  if (event.type.startsWith('artifact.')) return 'artifact'
  if (event.type.startsWith('tester.review_fallback')) return 'fallback'
  if (event.type === 'node.progress') return 'progress'
  return 'terminal'
}

function terminalLabel(event: SemanticEvent): string {
  if (event.severity === 'error' || event.type === 'node.failed') return '失败'
  if (event.severity === 'success' || event.type === 'node.completed') return '完成'
  if (event.severity === 'warning') return '警告'
  return event.title
}

function mergeProgressLabel(events: SemanticEvent[]): string {
  const latest = events[events.length - 1]
  return latest?.title ?? '进行中'
}

export function compressToMilestones(events: SemanticEvent[]): FlowNode[] {
  if (!events.length) return []

  const sorted = [...events].sort((left, right) => left.created_at.localeCompare(right.created_at))
  const milestones: FlowNode[] = []
  let progressBuffer: SemanticEvent[] = []
  let milestoneIndex = 0

  function flushProgress() {
    if (!progressBuffer.length) return
    milestoneIndex += 1
    const ids = progressBuffer.map((event) => event.id)
    const latest = progressBuffer[progressBuffer.length - 1]
    milestones.push({
      id: `milestone:progress:${milestoneIndex}`,
      label: mergeProgressLabel(progressBuffer),
      state: latest.severity === 'error' ? 'failed' : latest.severity === 'success' ? 'complete' : 'active',
      severity: latest.severity,
      eventIds: ids,
      event: latest,
    })
    progressBuffer = []
  }

  for (const event of sorted) {
    const kind = milestoneKind(event)
    if (kind === 'progress') {
      progressBuffer.push(event)
      continue
    }
    flushProgress()

    milestoneIndex += 1
    if (kind === 'started') {
      milestones.push({
        id: `milestone:started:${milestoneIndex}`,
        label: '已启动',
        state: 'complete',
        severity: event.severity,
        eventIds: [event.id],
        event,
      })
      continue
    }
    if (kind === 'artifact') {
      milestones.push({
        id: `milestone:artifact:${milestoneIndex}`,
        label: event.document ? `产物：${event.document}` : '产物已生成',
        state: event.severity === 'error' ? 'failed' : 'complete',
        severity: event.severity,
        eventIds: [event.id],
        event,
      })
      continue
    }
    if (kind === 'fallback') {
      milestones.push({
        id: `milestone:fallback:${milestoneIndex}`,
        label: '审查兜底',
        state: event.severity === 'error' ? 'failed' : event.severity === 'success' ? 'complete' : 'active',
        severity: event.severity,
        eventIds: [event.id],
        event,
      })
      continue
    }
    milestones.push({
      id: `milestone:terminal:${milestoneIndex}`,
      label: terminalLabel(event),
      state: event.severity === 'error' ? 'failed' : 'complete',
      severity: event.severity,
      eventIds: [event.id],
      event,
    })
  }
  flushProgress()
  return milestones
}

function milestoneEdges(milestones: FlowNode[]): FlowEdge[] {
  const edges: FlowEdge[] = []
  for (let index = 0; index < milestones.length - 1; index += 1) {
    edges.push({
      id: `micro:${milestones[index].id}->${milestones[index + 1].id}`,
      from: milestones[index].id,
      to: milestones[index + 1].id,
      kind: 'forward',
    })
  }
  return edges
}

export function inferDefaultRunId(runs: MicroRunModel[], reviewMode: boolean, stepLive: boolean): string | null {
  if (!runs.length) return null
  if (stepLive && !reviewMode) {
    const current = runs.find((run) => run.isCurrent)
    if (current) return current.id
  }
  return runs[runs.length - 1]?.id ?? null
}

export function inferDefaultMilestoneId(run: MicroRunModel | null, stepLive: boolean): string | null {
  if (!run?.milestones.length) return null
  if (stepLive && run.isCurrent) {
    const live = [...run.milestones].reverse().find((node) => node.state === 'active')
    if (live) return live.id
  }
  return run.milestones[run.milestones.length - 1]?.id ?? null
}

export function buildMicroFlow(
  detail: IterationDetail | null,
  stepKey: PipelineStepKey,
  options: { reviewMode: boolean; stepLive: boolean },
): MicroFlowModel {
  if (!detail) {
    return { runs: [], defaultRunId: null, defaultMilestoneId: null }
  }

  const activities = (detail.events.filter(isAgentActivity).filter((event) => event.type !== 'cli.display').map(presentEvent))
  const hasVerifyReject = Boolean((detail.retry_counts?.planner_verify_reject ?? 0) > 0)
  const grouped = groupAgentActivities(activities, stepKey, {
    reviewMode: options.reviewMode,
    stepLive: options.stepLive,
    hasVerifyReject,
  })

  const chronologicalRuns = [...grouped.groups].reverse()
  const runs: MicroRunModel[] = chronologicalRuns.map((group) => {
    const milestones = compressToMilestones(group.events)
    if (group.isCurrent && options.stepLive && !options.reviewMode && milestones.length) {
      const last = milestones[milestones.length - 1]
      if (last.state !== 'failed' && last.state !== 'complete') {
        last.isLive = true
        last.state = 'active'
      }
    }
    return {
      id: group.id,
      label: group.label,
      isCurrent: group.isCurrent,
      separatorBefore: group.separatorBefore,
      milestones,
      edges: milestoneEdges(milestones),
    }
  })

  const defaultRunId = inferDefaultRunId(runs, options.reviewMode, options.stepLive)
  const defaultRun = runs.find((run) => run.id === defaultRunId) ?? runs[runs.length - 1] ?? null
  const defaultMilestoneId = inferDefaultMilestoneId(defaultRun, options.stepLive && !options.reviewMode)

  return { runs, defaultRunId, defaultMilestoneId }
}

export function findMilestone(
  micro: MicroFlowModel,
  runId: string | null,
  milestoneId: string | null,
): FlowNode | null {
  const run = micro.runs.find((item) => item.id === runId) ?? micro.runs[micro.runs.length - 1]
  if (!run) return null
  return run.milestones.find((item) => item.id === milestoneId) ?? run.milestones[run.milestones.length - 1] ?? null
}
