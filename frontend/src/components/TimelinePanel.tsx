import type { IterationDetail, TimelineFilter } from '../types'
import { eventLabel, timelineFilterLabel } from '../labels'

interface Props {
  detail: IterationDetail | null
  filter?: TimelineFilter
  onFilterChange?: (filter: TimelineFilter) => void
}

function matchesFilter(type: string, filter: TimelineFilter) {
  if (filter === 'all') return true
  if (filter === 'decisions') return type.includes('approved') || type.includes('queued')
  if (filter === 'failures') return type.includes('failed') || type.includes('blocked') || type.includes('max_retries')
  if (filter === 'tests') return type.includes('test') || type.includes('integrity') || type.includes('tester') || type.includes('ui_driver')
  if (filter === 'runs') return type.includes('planner') || type.includes('coder') || type.includes('tester')
  return true
}

export function TimelinePanel({ detail, filter = 'all', onFilterChange }: Props) {
  const events = detail?.events.filter((event) => matchesFilter(event.type, filter)) ?? []
  return (
    <section className="panel stack">
      <div className="section-row">
        <h2 className="section-title">事件流</h2>
        {onFilterChange ? (
          <select className="compact-select" value={filter} onChange={(event) => onFilterChange(event.target.value as TimelineFilter)}>
            <option value="all">{timelineFilterLabel.all}</option>
            <option value="decisions">{timelineFilterLabel.decisions}</option>
            <option value="failures">{timelineFilterLabel.failures}</option>
            <option value="tests">{timelineFilterLabel.tests}</option>
            <option value="runs">{timelineFilterLabel.runs}</option>
          </select>
        ) : null}
      </div>
      <div className="timeline">
        {events.map((event) => (
          <div key={event.id} className={`item event-item ${event.type.includes('failed') || event.type.includes('blocked') ? 'danger' : event.type.includes('warning') ? 'warning' : ''}`}>
            <strong>{eventLabel(event.type)}</strong>
            <div className="muted event-json">{JSON.stringify(event.payload)}</div>
          </div>
        ))}
        {!events.length ? <div className="empty">暂无事件</div> : null}
      </div>
    </section>
  )
}
