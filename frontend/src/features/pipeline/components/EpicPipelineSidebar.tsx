import type { MouseEvent } from 'react'
import type { EpicSummary, IterationSummary } from '../../../shared/lib/types'
import { epicStatusLabel, iterationStatusLabel } from '../../../shared/lib/labels'

interface Props {
  epics: EpicSummary[]
  selectedEpicId: string | null
  onSelectEpic: (id: string | null) => void
  onDeleteEpic: (id: string) => void
  iterations: IterationSummary[]
  selectedIterationId: string | null
  onSelectIteration: (id: string | null) => void
  onDeleteIteration: (id: string) => void
  onCreatePipeline: () => void
}

function iterationStatusKind(status: IterationSummary['status']) {
  if (status === 'delivered') return 'delivered'
  if (['blocked', 'blocked_user', 'failed', 'stopped'].includes(status)) return 'attention'
  return 'running'
}

export function EpicPipelineSidebar({
  epics,
  selectedEpicId,
  onSelectEpic,
  onDeleteEpic,
  iterations,
  selectedIterationId,
  onSelectIteration,
  onDeleteIteration,
  onCreatePipeline,
}: Props) {
  const selectedEpic = epics.find((epic) => epic.id === selectedEpicId) ?? null

  function handleDeleteEpic(event: MouseEvent, epic: EpicSummary) {
    event.stopPropagation()
    const confirmed = window.confirm(
      `确定删除大需求「${epic.title}」？\n\n其下 ${epic.iteration_count} 条流水线也会从 SpecForge 移除，本地产物不会被删除。`,
    )
    if (!confirmed) return
    onDeleteEpic(epic.id)
  }

  function handleDeleteIteration(event: MouseEvent, item: IterationSummary) {
    event.stopPropagation()
    const title = item.goal.split('\n')[0] || '流水线'
    const confirmed = window.confirm(
      `确定删除流水线「${title}」？\n\n只会从 SpecForge 移除记录，本地 .specforge 产物不会被删除。`,
    )
    if (!confirmed) return
    onDeleteIteration(item.id)
  }

  return (
    <aside className="sidebar epic-pipeline-sidebar sidebar-layout">
      <div className="sidebar-top">
        <button type="button" className="btn btn-ghost sidebar-new-btn" onClick={onCreatePipeline}>
          + 新建流水线
        </button>

        <section className="sidebar-projects">
          <h2 className="sidebar-section-title">大需求</h2>
          <div className="sidebar-project-list">
            {epics.map((epic) => (
              <div key={epic.id} className={`sidebar-row-wrap ${selectedEpicId === epic.id ? 'active' : ''}`}>
                <button
                  type="button"
                  className={`sidebar-row ${selectedEpicId === epic.id ? 'active' : ''}`}
                  onClick={() => onSelectEpic(epic.id)}
                >
                  <div className="sidebar-row-head">
                    <strong>{epic.title}</strong>
                    <span className={`sidebar-status ${epic.status === 'delivered' ? 'delivered' : epic.status === 'blocked' ? 'attention' : 'idle'}`}>
                      {epicStatusLabel[epic.status]}
                    </span>
                  </div>
                  <span className="sidebar-row-meta">
                    {epic.delivered_count}/{epic.iteration_count} 已交付
                  </span>
                </button>
                <button
                  type="button"
                  className="sidebar-row-delete"
                  aria-label={`删除大需求 ${epic.title}`}
                  onClick={(event) => handleDeleteEpic(event, epic)}
                >
                  ×
                </button>
              </div>
            ))}
            {!epics.length ? <div className="empty sidebar-empty">暂无大需求</div> : null}
          </div>
        </section>

        {selectedEpic ? (
          <section className="sidebar-projects">
            <h2 className="sidebar-section-title">流水线</h2>
            <div className="sidebar-project-list">
              {iterations.map((item) => (
                <div key={item.id} className={`sidebar-row-wrap ${selectedIterationId === item.id ? 'active' : ''}`}>
                  <button
                    type="button"
                    className={`sidebar-row ${selectedIterationId === item.id ? 'active' : ''}`}
                    onClick={() => onSelectIteration(item.id)}
                  >
                    <div className="sidebar-row-head">
                      <strong className="pipeline-row-title">{item.goal.split('\n')[0] || '流水线'}</strong>
                      <span className={`sidebar-status ${iterationStatusKind(item.status)}`}>
                        {iterationStatusLabel[item.status]}
                      </span>
                    </div>
                    {item.goal.includes('\n') ? <span className="sidebar-row-meta">{item.goal.split('\n').slice(1).join(' ').trim()}</span> : null}
                  </button>
                  <button
                    type="button"
                    className="sidebar-row-delete"
                    aria-label="删除流水线"
                    onClick={(event) => handleDeleteIteration(event, item)}
                  >
                    ×
                  </button>
                </div>
              ))}
              {!iterations.length ? (
                <div className="empty sidebar-empty">暂无流水线，点击上方新建</div>
              ) : null}
            </div>
          </section>
        ) : null}
      </div>
    </aside>
  )
}
