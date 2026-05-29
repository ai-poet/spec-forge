import type { IterationSummary } from '../../../shared/lib/types'
import { iterationStatusLabel } from '../../../shared/lib/labels'
import styles from './IterationList.module.less'

interface Props {
  iterations: IterationSummary[]
  selectedIterationId: string | null
  onSelectIteration: (id: string) => void
  compact?: boolean
}

export function IterationList({ iterations, selectedIterationId, onSelectIteration, compact = false }: Props) {
  if (!iterations.length) return null

  return (
    <section className={compact ? `${styles.compactList} stack` : 'panel stack'}>
      <div className="section-row">
        <h2 className="section-title">已有流水线</h2>
        <span className="pill">{iterations.length}</span>
      </div>
      <div className={`list ${styles.list} ${compact ? 'compact' : ''}`}>
        {iterations.map((item) => (
          <button
            key={item.id}
            className={`item ${selectedIterationId === item.id ? 'active' : ''}`}
            onClick={() => onSelectIteration(item.id)}
          >
            <div className="item-head">
              <strong>{iterationStatusLabel[item.status]}</strong>
              <span className="muted">{item.mode}</span>
            </div>
            {item.last_error ? <div className="error-text clamp">{item.last_error}</div> : null}
            <div className="muted clamp">{item.goal}</div>
          </button>
        ))}
      </div>
    </section>
  )
}
