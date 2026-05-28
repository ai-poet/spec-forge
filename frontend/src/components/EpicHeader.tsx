import type { EpicSummary, LiveConnectionStatus, ProjectSummary } from '../types'
import { connectionLabel } from '../labels'

interface Props {
  project: ProjectSummary | null
  epic: EpicSummary | null
  connectionStatus: LiveConnectionStatus
  lastMessageAt: string | null
}

export function EpicHeader({ project, epic, connectionStatus, lastMessageAt }: Props) {
  const progress = epic?.iteration_count ? Math.round((epic.delivered_count / epic.iteration_count) * 100) : 0

  return (
    <header className="workspace-header epic-header">
      <div className="stack compact-stack">
        <p className="eyebrow">{project?.name ?? '项目'}</p>
        <h1>{epic?.title ?? '请选择或创建大需求'}</h1>
        <p className="muted">{epic?.description || project?.description || '每个大需求可以包含多个自动回环迭代。'}</p>
        {epic?.acceptance_criteria ? <pre className="criteria-preview">{epic.acceptance_criteria}</pre> : null}
      </div>
      <div className="header-metrics">
        <div className="status-card">
          <strong>{progress}%</strong>
          <span>完成进度</span>
        </div>
        <div className="status-card">
          <strong>{epic?.blocked_count ?? 0}</strong>
          <span>阻断数</span>
        </div>
        <div className="status-card">
          <strong>{connectionLabel[connectionStatus]}</strong>
          <span>{lastMessageAt ? new Date(lastMessageAt).toLocaleTimeString() : '等待实时事件'}</span>
        </div>
      </div>
    </header>
  )
}
