import type { IterationDetail } from '../types'

interface Props {
  detail: IterationDetail | null
}

export function RunLogPanel({ detail }: Props) {
  return (
    <section className="panel stack">
      <h2 className="section-title">运行日志</h2>
      <div className="timeline">
        {detail?.runs.map((run) => (
          <div key={run.id} className="item">
            <div className="item-head">
              <strong>{run.node}</strong>
              <span className={run.status === 'success' ? 'ok-text' : 'error-text'}>{run.status}</span>
            </div>
            <div className="muted">{run.command}</div>
            <pre className="code log">{run.stdout || run.stderr || 'No output'}</pre>
          </div>
        ))}
        {!detail?.runs.length ? <div className="empty">暂无日志</div> : null}
      </div>
    </section>
  )
}
