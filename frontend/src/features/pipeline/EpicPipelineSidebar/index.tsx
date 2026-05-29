import type { MouseEvent } from 'react'
import type { EpicSummary, IterationSummary } from '../../../shared/lib/types'
import { iterationStatusLabel } from '../../../shared/lib/labels'
import { iterationForEpic, pipelineStatusForEpic } from '../lib/epicPipeline'

interface Props {
  epics: EpicSummary[]
  selectedEpicId: string | null
  iterations: IterationSummary[]
  onSelectPipeline: (epicId: string) => void
  onDeletePipeline: (epicId: string) => void
  onCreatePipeline: () => void
}

function statusKind(status: string) {
  if (status === 'delivered') return 'delivered'
  if (['blocked', 'blocked_user', 'failed', 'stopped'].includes(status)) return 'attention'
  if (status === 'created') return 'idle'
  return 'running'
}

export function EpicPipelineSidebar({
  epics,
  selectedEpicId,
  iterations,
  onSelectPipeline,
  onDeletePipeline,
  onCreatePipeline,
}: Props) {
  function handleDelete(event: MouseEvent, epic: EpicSummary) {
    event.stopPropagation()
    const confirmed = window.confirm(
      `确定删除「${epic.title}」？\n\n大需求与对应流水线会从 SpecForge 移除，本地产物不会被删除。`,
    )
    if (!confirmed) return
    onDeletePipeline(epic.id)
  }

  return (
    <aside className="sidebar epic-pipeline-sidebar sidebar-layout">
      <div className="sidebar-top">
        <button type="button" className="btn btn-ghost sidebar-new-btn" onClick={onCreatePipeline}>
          + 新建流水线
        </button>

        <section className="sidebar-projects">
          <h2 className="sidebar-section-title">流水线</h2>
          <div className="sidebar-project-list">
            {epics.map((epic) => {
              const iteration = iterationForEpic(iterations, epic.id)
              const pipelineStatus = pipelineStatusForEpic(epic, iteration)
              return (
                <div key={epic.id} className={`sidebar-row-wrap ${selectedEpicId === epic.id ? 'active' : ''}`}>
                  <button
                    type="button"
                    className={`sidebar-row ${selectedEpicId === epic.id ? 'active' : ''}`}
                    onClick={() => onSelectPipeline(epic.id)}
                  >
                    <div className="sidebar-row-head">
                      <strong className="pipeline-row-title">{epic.title}</strong>
                      <span className={`sidebar-status ${statusKind(pipelineStatus)}`}>
                        {iteration ? iterationStatusLabel[pipelineStatus as IterationSummary['status']] : '未启动'}
                      </span>
                    </div>
                    {epic.description ? <span className="sidebar-row-meta">{epic.description.split('\n')[0]}</span> : null}
                  </button>
                  <button
                    type="button"
                    className="sidebar-row-delete"
                    aria-label={`删除 ${epic.title}`}
                    onClick={(event) => handleDelete(event, epic)}
                  >
                    ×
                  </button>
                </div>
              )
            })}
            {!epics.length ? <div className="empty sidebar-empty">暂无流水线，点击上方新建</div> : null}
          </div>
        </section>
      </div>
    </aside>
  )
}
