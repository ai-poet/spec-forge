import type { MouseEvent } from 'react'
import type { EpicSummary, IterationSummary } from '../../../shared/lib/types'
import { iterationStatusLabel } from '../../../shared/lib/labels'
import { iterationForEpic, pipelineStatusForEpic } from '../lib/epicPipeline'
import sidebar from '../../../shared/ui/sidebar.module.less'
import styles from './EpicPipelineSidebar.module.less'

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
    <aside className={`${sidebar.sidebar} ${sidebar.layout} ${styles.root}`}>
      <div className={`${sidebar.top} ${styles.top}`}>
        <button type="button" className="btn btn-ghost" onClick={onCreatePipeline}>
          + 新建流水线
        </button>

        <section>
          <h2 className={sidebar.sectionTitle}>流水线</h2>
          <div className={sidebar.projectList}>
            {epics.map((epic) => {
              const iteration = iterationForEpic(iterations, epic.id)
              const pipelineStatus = pipelineStatusForEpic(epic, iteration)
              const kind = statusKind(pipelineStatus)
              return (
                <div key={epic.id} className={`${sidebar.rowWrap} ${selectedEpicId === epic.id ? sidebar.active : ''}`}>
                  <button
                    type="button"
                    className={`${sidebar.row} ${selectedEpicId === epic.id ? sidebar.active : ''}`}
                    onClick={() => onSelectPipeline(epic.id)}
                  >
                    <div className={sidebar.rowHead}>
                      <strong className={styles.pipelineTitle}>{epic.title}</strong>
                      <span className={`${sidebar.status} ${sidebar[kind]}`}>
                        {iteration ? iterationStatusLabel[pipelineStatus as IterationSummary['status']] : '未启动'}
                      </span>
                    </div>
                    {epic.description ? <span className={sidebar.rowMeta}>{epic.description.split('\n')[0]}</span> : null}
                  </button>
                  <button
                    type="button"
                    className={sidebar.rowDelete}
                    aria-label={`删除 ${epic.title}`}
                    onClick={(event) => handleDelete(event, epic)}
                  >
                    ×
                  </button>
                </div>
              )
            })}
            {!epics.length ? <div className={`empty ${sidebar.empty}`}>暂无流水线，点击上方新建</div> : null}
          </div>
        </section>
      </div>
    </aside>
  )
}
