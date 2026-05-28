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
  const selectedIteration = iterations.find((item) => item.id === selectedIterationId) ?? null

  return (
    <header className="context-header">
      <div className="context-header-row">
        <span className="context-project-name">{project?.name ?? '项目'}</span>
        <span className="context-sep">·</span>
        <select
          className="compact-select context-select-inline"
          value={selectedEpicId ?? ''}
          onChange={(event) => onSelectEpic(event.target.value || null)}
        >
          <option value="">大需求</option>
          {epics.map((epic) => (
            <option key={epic.id} value={epic.id}>
              {epic.title} ({epicStatusLabel[epic.status]})
            </option>
          ))}
        </select>
        <span className="context-sep">·</span>
        <select
          className="compact-select context-select-inline"
          value={selectedIterationId ?? ''}
          onChange={(event) => onSelectIteration(event.target.value || null)}
          disabled={!selectedEpicId}
        >
          <option value="">流水线</option>
          {iterations.map((item) => (
            <option key={item.id} value={item.id}>
              {iterationStatusLabel[item.status]}
            </option>
          ))}
        </select>
      </div>
      <div className="context-header-actions">
        <button type="button" className="btn btn-ghost btn-sm" onClick={onCreateEpic} disabled={!project}>
          新建大需求
        </button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onCreateIteration} disabled={!selectedEpicId}>
          新建流水线
        </button>
        {selectedIteration ? (
          <span className={`status-pill ${selectedIteration.status === 'delivered' ? 'delivered' : selectedIteration.status.includes('blocked') ? 'blocked' : 'active'}`}>
            {iterationStatusLabel[selectedIteration.status]}
          </span>
        ) : null}
      </div>
    </header>
  )
}
