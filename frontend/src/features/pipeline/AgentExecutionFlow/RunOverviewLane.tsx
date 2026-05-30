import { useState } from 'react'
import type { MicroRunModel } from '../lib/buildAgentFlow'
import styles from './AgentExecutionFlow.module.less'

interface Props {
  runs: MicroRunModel[]
  activeRunId: string | null
  onSelectRun: (runId: string) => void
}

export function RunOverviewLane({ runs, activeRunId, onSelectRun }: Props) {
  const [open, setOpen] = useState(false)
  if (runs.length <= 3) return null

  return (
    <div className={styles.overviewLane}>
      <button type="button" className={styles.overviewToggle} onClick={() => setOpen((value) => !value)}>
        轮次总览（{runs.length} 次执行） {open ? '▾' : '▸'}
      </button>
      {open ? (
        <div className={styles.overviewList}>
          {runs.map((run) => {
            const labels = run.milestones.map((milestone) => milestone.label).join(' → ')
            return (
              <button
                key={run.id}
                type="button"
                className={`${styles.overviewRow} ${run.id === activeRunId ? styles.overviewRowActive : ''}`}
                onClick={() => onSelectRun(run.id)}
              >
                <strong>{run.label}</strong>
                <span className="muted">{labels || '暂无里程碑'}</span>
              </button>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}
