import { presentEvent, presentNodeName } from '../../../shared/lib/presentation'
import type { IterationDetail } from '../../../shared/lib/types'
import { nodesForStep, type PipelineStepKey } from './pipelineSteps'

export const PIPELINE_RUNNING_STATUSES = new Set([
  'queued',
  'planning',
  'coding',
  'retrying',
  'testing',
])

const IGNORED_PROGRESS_TITLES = new Set(['已收到错误输出', 'CLI 诊断输出'])

export function isPipelineRunning(detail: IterationDetail | null): boolean {
  return Boolean(detail && PIPELINE_RUNNING_STATUSES.has(detail.status))
}

export function isRunningStatus(status: string | null | undefined): boolean {
  return Boolean(status && PIPELINE_RUNNING_STATUSES.has(status))
}

export function isStepLive(detail: IterationDetail | null, stepKey: PipelineStepKey | null): boolean {
  if (!detail || !stepKey || !isPipelineRunning(detail)) return false
  const node = detail.current_node
  if (!node) return false
  return nodesForStep(stepKey).includes(node)
}

export function latestNodeProgress(detail: IterationDetail | null, stepKey?: PipelineStepKey | null) {
  if (!detail) return null
  const nodes = stepKey ? new Set(nodesForStep(stepKey)) : null
  for (let index = detail.events.length - 1; index >= 0; index -= 1) {
    const event = detail.events[index]
    if (event.type !== 'node.progress' && event.type !== 'node.started') continue
    const presented = presentEvent(event)
    if (nodes && !nodes.has(presented.node)) continue
    if (event.type === 'node.progress' && IGNORED_PROGRESS_TITLES.has(presented.title)) continue
    return presented
  }
  return null
}

export function isUiDriverRunning(detail: IterationDetail | null): boolean {
  if (!detail) return false
  const uiEvents = detail.events.filter((event) => event.type.startsWith('ui_driver.'))
  if (!uiEvents.length) return false
  return uiEvents[uiEvents.length - 1].type === 'ui_driver.started'
}

export function formatElapsed(iso: string | null): string | null {
  if (!iso) return null
  const elapsedMs = Date.now() - new Date(iso).getTime()
  if (elapsedMs < 0) return null
  const seconds = Math.floor(elapsedMs / 1000)
  if (seconds < 60) return `${seconds} 秒`
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds % 60
  return remainder ? `${minutes} 分 ${remainder} 秒` : `${minutes} 分`
}

export function runningNodeLabel(detail: IterationDetail | null): string | null {
  if (!detail?.current_node) return null
  return presentNodeName(detail.current_node)
}

export function hasVerifyRejectRetry(detail: IterationDetail | null): boolean {
  return Boolean(detail && (detail.retry_counts?.planner_verify_reject ?? 0) > 0)
}

export function isVerifyRejectRetest(detail: IterationDetail | null): boolean {
  return Boolean(
    detail
    && hasVerifyRejectRetry(detail)
    && detail.current_node === 'tester'
    && (detail.status === 'testing' || detail.status === 'retrying'),
  )
}

export function isPlannerVerifyRejectRetry(detail: IterationDetail | null): boolean {
  if (!detail || detail.status !== 'retrying') return false
  return detail.events.some((event) => event.type === 'planner_verify.rejected')
}

export function latestRetryTarget(detail: IterationDetail | null): 'coder' | 'tester' | null {
  if (!detail) return null
  for (let index = detail.events.length - 1; index >= 0; index -= 1) {
    const event = detail.events[index]
    if (event.type === 'tester.retry_to_coder') return 'coder'
    if (event.type === 'tester.retry_to_self') return 'tester'
    if (event.type === 'tester.failed_retry') return 'coder'
    const payload = event.payload as { retry_target?: string } | undefined
    if (payload?.retry_target === 'tester') return 'tester'
    if (payload?.retry_target === 'coder') return 'coder'
  }
  return null
}
