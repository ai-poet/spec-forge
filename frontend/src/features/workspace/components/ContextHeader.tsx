import type { IterationSummary, ProjectSummary } from '../../../shared/lib/types'
import { iterationStatusLabel } from '../../../shared/lib/labels'

interface Props {
  project: ProjectSummary | null
  selectedIteration: IterationSummary | null
  onCreatePipeline: () => void
  onOpenSettings: () => void
}

export function ContextHeader({ project, selectedIteration, onCreatePipeline, onOpenSettings }: Props) {
  return (
    <header className="context-header">
      <div className="context-header-row">
        <span className="context-project-name">{project?.name ?? '项目'}</span>
        {selectedIteration ? (
          <>
            <span className="context-sep">·</span>
            <span className={`status-pill ${selectedIteration.status === 'delivered' ? 'delivered' : selectedIteration.status.includes('blocked') ? 'blocked' : 'active'}`}>
              {iterationStatusLabel[selectedIteration.status]}
            </span>
          </>
        ) : null}
      </div>
      <div className="context-header-actions">
        <button type="button" className="btn btn-ghost btn-sm" onClick={onCreatePipeline} disabled={!project}>
          新建流水线
        </button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onOpenSettings} disabled={!project} title="目录绑定、配置与移除">
          项目设置
        </button>
      </div>
    </header>
  )
}
