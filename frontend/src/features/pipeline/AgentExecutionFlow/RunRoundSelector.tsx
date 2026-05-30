import type { MicroRunModel } from '../lib/buildAgentFlow'
import styles from './AgentExecutionFlow.module.less'

const TAB_THRESHOLD = 5

interface Props {
  runs: MicroRunModel[]
  activeRunId: string | null
  onSelectRun: (runId: string) => void
}

export function RunRoundSelector({ runs, activeRunId, onSelectRun }: Props) {
  if (runs.length <= 1) return null

  const activeIndex = Math.max(0, runs.findIndex((run) => run.id === activeRunId))
  const activeRun = runs[activeIndex] ?? runs[runs.length - 1]

  function selectIndex(index: number) {
    const run = runs[index]
    if (run) onSelectRun(run.id)
  }

  if (runs.length <= TAB_THRESHOLD) {
    return (
      <div className={styles.runTabs} role="tablist">
        {runs.map((run) => (
          <button
            key={run.id}
            type="button"
            role="tab"
            aria-selected={activeRun?.id === run.id}
            className={`${styles.runTab} ${activeRun?.id === run.id ? styles.runTabActive : ''}`}
            onClick={() => onSelectRun(run.id)}
          >
            {run.label}
          </button>
        ))}
      </div>
    )
  }

  return (
    <div className={styles.runStepper}>
      <button type="button" className="btn btn-ghost btn-sm" disabled={activeIndex <= 0} onClick={() => selectIndex(activeIndex - 1)}>
        上一轮
      </button>
      <label className={styles.runSelectLabel}>
        <span className="muted">轮次</span>
        <select
          className={styles.runSelect}
          value={activeRun?.id ?? ''}
          onChange={(event) => onSelectRun(event.target.value)}
        >
          {runs.map((run, index) => (
            <option key={run.id} value={run.id}>
              {index + 1}/{runs.length} · {run.label.replace('（当前）', '')}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        disabled={activeIndex >= runs.length - 1}
        onClick={() => selectIndex(activeIndex + 1)}
      >
        下一轮
      </button>
    </div>
  )
}
