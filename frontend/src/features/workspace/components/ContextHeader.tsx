import type { EpicSummary, IterationSummary, ProjectSummary } from '../../../shared/lib/types'
import { epicStatusLabel, iterationStatusLabel } from '../../../shared/lib/labels'

interface Props {
  project: ProjectSummary | null
  epics: EpicSummary[]
  selectedEpicId: string | null
  onSelectEpic: (id: string | null) => void
  iterations: IterationSummary[]
  selectedIterationId: string | null
  onSelectIteration: (id: string | null) => void
  onCreateEpic: () => void
  onCreateIteration: () => void
}

export function ContextHeader({
  project,
  epics,
  selectedEpicId,
  onSelectEpic,
  iterations,
  selectedIterationId,
  onSelectIteration,
  onCreateEpic,
  onCreateIteration,
}: Props) {
  const selectedEpic = epics.find((epic) => epic.id === selectedEpicId) ?? null
  const selectedIteration = iterations.find((item) => item.id === selectedIterationId) ?? null

  return (
    <header className="context-header">
      <div className="context-header-main">
        <p className="eyebrow">{project?.name ?? '项目'}</p>
        <div className="context-selectors">
          <label className="context-select">
            <span>大需求</span>
            <select
              className="compact-select"
              value={selectedEpicId ?? ''}
              onChange={(event) => onSelectEpic(event.target.value || null)}
            >
              <option value="">选择大需求…</option>
              {epics.map((epic) => (
                <option key={epic.id} value={epic.id}>
                  {epic.title} ({epicStatusLabel[epic.status]})
                </option>
              ))}
            </select>
          </label>
          <label className="context-select">
            <span>流水线</span>
            <select
              className="compact-select"
              value={selectedIterationId ?? ''}
              onChange={(event) => onSelectIteration(event.target.value || null)}
              disabled={!selectedEpicId}
            >
              <option value="">选择流水线…</option>
              {iterations.map((item) => (
                <option key={item.id} value={item.id}>
                  {iterationStatusLabel[item.status]} · {item.goal.slice(0, 40)}
                  {item.goal.length > 40 ? '…' : ''}
                </option>
              ))}
            </select>
          </label>
        </div>
        {selectedEpic ? (
          <p className="muted context-description">{selectedEpic.description || '暂无描述'}</p>
        ) : (
          <p className="muted context-description">{project?.description || '请选择一个 Epic 查看详情'}</p>
        )}
      </div>
      <div className="context-header-actions">
        <button className="btn" onClick={onCreateEpic} disabled={!project}>
          新建大需求
        </button>
        <button className="btn" onClick={onCreateIteration} disabled={!selectedEpicId}>
          新建流水线
        </button>
        {selectedIteration ? (
          <span className={`status-dot ${selectedIteration.status === 'delivered' ? 'delivered' : selectedIteration.status.includes('blocked') ? 'blocked' : 'active'}`}>
            {iterationStatusLabel[selectedIteration.status]}
          </span>
        ) : null}
      </div>
    </header>
  )
}
