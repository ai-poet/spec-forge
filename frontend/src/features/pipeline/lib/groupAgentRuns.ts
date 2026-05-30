import type { SemanticEvent } from '../../../shared/lib/types'
import type { PipelineStepKey } from './pipelineSteps'
import { nodesForStep } from './pipelineSteps'

export interface AgentRunGroup {
  id: string
  label: string
  events: SemanticEvent[]
  isCurrent: boolean
  separatorBefore?: string
}

export interface GroupedActivities {
  groups: AgentRunGroup[]
  totalEvents: number
  currentRoundEvents: number
  roundCount: number
}

function chronological(events: SemanticEvent[]): SemanticEvent[] {
  return [...events].sort((left, right) => left.created_at.localeCompare(right.created_at))
}

function isRunBoundary(event: SemanticEvent, stepNodes: Set<string>): boolean {
  return event.type === 'node.started' && stepNodes.has(event.node)
}

function runKey(event: SemanticEvent, index: number): string {
  return event.run_id ?? `implicit-${index}`
}

export function groupAgentActivities(
  events: SemanticEvent[],
  stepKey: PipelineStepKey | null,
  options: { reviewMode: boolean; stepLive: boolean; hasVerifyReject?: boolean },
): GroupedActivities {
  if (!events.length) {
    return { groups: [], totalEvents: 0, currentRoundEvents: 0, roundCount: 0 }
  }

  const stepNodes = stepKey ? new Set(nodesForStep(stepKey)) : null
  const sorted = chronological(events)
  const runs: AgentRunGroup[] = []
  let bucket: SemanticEvent[] = []
  let bucketKey = ''
  let runIndex = 0

  function flush() {
    if (!bucket.length) return
    runIndex += 1
    runs.push({
      id: bucketKey || `run-${runIndex}`,
      label: `第 ${runIndex} 轮`,
      events: [...bucket],
      isCurrent: false,
    })
    bucket = []
    bucketKey = ''
  }

  for (const event of sorted) {
    const boundary = stepNodes ? isRunBoundary(event, stepNodes) : event.type === 'node.started'
    const nextKey = runKey(event, runIndex + 1)

    if (boundary && bucket.length) {
      flush()
    }
    if (event.run_id && bucket.length && bucketKey && event.run_id !== bucketKey) {
      flush()
    }
    if (!bucket.length) {
      bucketKey = nextKey
    }
    bucket.push(event)
  }
  flush()

  if (runs.length) {
    runs[runs.length - 1].isCurrent = options.stepLive && !options.reviewMode
  }

  for (let index = 1; index < runs.length; index += 1) {
    if (options.hasVerifyReject) {
      runs[index].separatorBefore = '规格复核驳回 → 重新验证'
    }
  }

  runs.forEach((group, index) => {
    const round = index + 1
    group.label = group.isCurrent ? `第 ${round} 轮（当前）` : `第 ${round} 轮`
  })

  const current = runs.find((group) => group.isCurrent) ?? runs[runs.length - 1]
  return {
    groups: [...runs].reverse(),
    totalEvents: events.length,
    currentRoundEvents: current?.events.length ?? 0,
    roundCount: runs.length,
  }
}

export function defaultExpandedRunIds(
  groups: AgentRunGroup[],
  reviewMode: boolean,
): Set<string> {
  const expanded = new Set<string>()
  if (!groups.length) return expanded
  if (reviewMode) return expanded
  const current = groups.find((group) => group.isCurrent)
  if (current) {
    expanded.add(current.id)
    return expanded
  }
  if (groups.length === 1) expanded.add(groups[0].id)
  return expanded
}
