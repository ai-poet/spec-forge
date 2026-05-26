import type { IterationDetail } from '../types'

interface Props {
  detail: IterationDetail | null
}

export function TimelinePanel({ detail }: Props) {
  return (
    <section className="panel stack">
      <h2 className="section-title">事件流</h2>
      <div className="timeline">
        {detail?.events.map((event) => (
          <div key={event.id} className="item">
            <strong>{event.type}</strong>
            <div className="muted event-json">{JSON.stringify(event.payload)}</div>
          </div>
        ))}
        {!detail?.events.length ? <div className="empty">暂无事件</div> : null}
      </div>
    </section>
  )
}
