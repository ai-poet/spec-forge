import type { EpicSummary, LiveConnectionStatus, ProjectSummary } from '../types'

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
        <p className="eyebrow">{project?.name ?? 'Project'}</p>
        <h1>{epic?.title ?? '请选择或创建大需求'}</h1>
        <p className="muted">{epic?.description || project?.description || '每个大需求可以包含多个自动回环 iteration。'}</p>
        {epic?.acceptance_criteria ? <pre className="criteria-preview">{epic.acceptance_criteria}</pre> : null}
      </div>
      <div className="header-metrics">
        <div className="status-card">
          <strong>{progress}%</strong>
          <span>progress</span>
        </div>
        <div className="status-card">
          <strong>{epic?.blocked_count ?? 0}</strong>
          <span>blocked</span>
        </div>
        <div className="status-card">
          <strong>{connectionStatus}</strong>
          <span>{lastMessageAt ? new Date(lastMessageAt).toLocaleTimeString() : 'live feed'}</span>
        </div>
      </div>
    </header>
  )
}
