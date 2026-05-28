import type { IterationDetail } from '../types'
import { isAgentActivity, presentEvent, presentNodeName } from '../presentation'

interface Props {
  detail: IterationDetail | null
}

export function AgentActivityPanel({ detail }: Props) {
  const activities = detail?.events.filter(isAgentActivity).map(presentEvent) ?? []
  const visible = activities.slice(-8).reverse()

  return (
    <section className="panel stack">
      <div className="section-row">
        <h2 className="section-title">Agent 运行状态</h2>
        <span className="pill">{activities.length} 条</span>
      </div>
      <div className="activity-list">
        {visible.map((event) => (
          <article key={event.id} className={`activity-item ${event.severity}`}>
            <div>
              <strong>{event.title}</strong>
              <p>{event.message}</p>
              {event.action_hint ? <small>{event.action_hint}</small> : null}
            </div>
            <span className={`status-dot ${event.severity}`}>{presentNodeName(event.node)}</span>
          </article>
        ))}
        {!visible.length ? <div className="empty">Agent 运行后，这里会显示中文步骤和产物状态。</div> : null}
      </div>
    </section>
  )
}
