import type { EpicSummary, IterationSummary } from '../../../shared/lib/types'

export function iterationForEpic(iterations: IterationSummary[], epicId: string): IterationSummary | null {
  return iterations.find((item) => item.epic_id === epicId) ?? null
}

export function pipelineStatusForEpic(epic: EpicSummary, iteration: IterationSummary | null) {
  if (iteration) return iteration.status
  return epic.status === 'delivered' ? 'delivered' : 'created'
}
