import type { EpicSummary, IterationDetail, IterationSummary, ProjectSummary } from '../../../shared/lib/types'
import { iterationStatusLabel } from '../../../shared/lib/labels'
import { isRunningStatus } from '../../pipeline/lib/pipelineLive'
import { RunningIndicator } from '../../../shared/ui/RunningIndicator'
import styles from './ContextHeader.module.less'

interface Props {
  project: ProjectSummary | null
  selectedEpic: EpicSummary | null
  selectedIteration: IterationSummary | null
  liveDetail?: IterationDetail | null
  isLoading?: boolean
  onCreatePipeline: () => void
  onOpenSettings: () => void
}

function statusPillClass(status: string): string {
  if (status === 'delivered') return styles.delivered
  if (status.includes('blocked')) return styles.blocked
  if (['planning', 'coding', 'testing', 'retrying', 'queued'].includes(status)) return styles.running
  if (['awaiting_requirements_input', 'awaiting_verify_approval'].includes(status)) {
    return styles.active
  }
  return styles.active
}

export function ContextHeader({
  project,
  selectedEpic,
  selectedIteration,
  liveDetail,
  isLoading,
  onCreatePipeline,
  onOpenSettings,
}: Props) {
  const status = liveDetail?.status ?? selectedIteration?.status
  const running = isRunningStatus(status)

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
        {isLoading ? (
          <>
            <span className={styles.sep}>·</span>
            <RunningIndicator size="sm" mode="spinner" label="加载中" />
          </>
        ) : status ? (
          <>
            <span className={styles.sep}>·</span>
            <span className={`${styles.statusPill} ${statusPillClass(status)}`}>
              {running ? <span className={styles.statusDot} aria-hidden="true" /> : null}
              {iterationStatusLabel[status]}
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
