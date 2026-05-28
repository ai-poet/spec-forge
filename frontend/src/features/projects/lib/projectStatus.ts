import type { ProjectSummary } from '../../../shared/lib/types'

export type ProjectStatusKind = 'idle' | 'running' | 'delivered' | 'attention'

export function deriveProjectStatus(project: ProjectSummary): { kind: ProjectStatusKind; label: string; detail: string | null } {
  const { iteration_count, active_count, delivered_count } = project

  if (iteration_count === 0) {
    return { kind: 'idle', label: '空闲', detail: null }
  }

  if (active_count > 0) {
    return {
      kind: 'running',
      label: '运行中',
      detail: `${active_count}/${iteration_count} 流水线进行中`,
    }
  }

  if (delivered_count === iteration_count) {
    return {
      kind: 'delivered',
      label: '已交付',
      detail: `${delivered_count} 条流水线已完成`,
    }
  }

  const attentionCount = iteration_count - delivered_count
  return {
    kind: 'attention',
    label: '需关注',
    detail: `${attentionCount}/${iteration_count} 条未交付`,
  }
}
