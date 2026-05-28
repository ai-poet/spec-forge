import type { IterationSummary } from '../types'
import { iterationStatusLabel } from '../labels'

interface Props {
  iterations: IterationSummary[]
  selectedIterationId: string | null
  onSelectIteration: (id: string) => void
}

export function IterationList({ iterations, selectedIterationId, onSelectIteration }: Props) {
  return (
    <section className="panel stack">
      <div className="section-row">
        <h2 className="section-title">流水线</h2>
        <span className="pill">{iterations.length}</span>
      </div>
      <div className="list iteration-list">
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
        {!iterations.length ? <div className="empty">当前项目还没有流水线</div> : null}
      </div>
    </section>
  )
}
