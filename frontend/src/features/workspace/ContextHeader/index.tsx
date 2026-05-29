import type { EpicSummary, IterationSummary, ProjectSummary } from '../../../shared/lib/types'
import { iterationStatusLabel } from '../../../shared/lib/labels'
import styles from './ContextHeader.module.less'

interface Props {
  project: ProjectSummary | null
  selectedEpic: EpicSummary | null
  selectedIteration: IterationSummary | null
  onCreatePipeline: () => void
  onOpenSettings: () => void
}

function statusPillClass(status: string): string {
  if (status === 'delivered') return styles.delivered
  if (status.includes('blocked')) return styles.blocked
  return styles.active
}

export function ContextHeader({ project, selectedEpic, selectedIteration, onCreatePipeline, onOpenSettings }: Props) {
  return (
    <header className={styles.header}>
      <div className={styles.row}>
        <span className={styles.projectName}>{project?.name ?? '项目'}</span>
        {selectedEpic ? (
          <>
            <span className={styles.sep}>·</span>
            <span className={styles.projectName}>{selectedEpic.title}</span>
          </>
        ) : null}
        {selectedIteration ? (
          <>
            <span className={styles.sep}>·</span>
            <span className={`${styles.statusPill} ${statusPillClass(selectedIteration.status)}`}>
              {iterationStatusLabel[selectedIteration.status]}
            </span>
          </>
        ) : null}
      </div>
      <div className={styles.actions}>
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
