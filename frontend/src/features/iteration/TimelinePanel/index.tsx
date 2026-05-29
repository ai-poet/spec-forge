import type { IterationDetail, TimelineFilter } from '../../../shared/lib/types'
import { timelineFilterLabel } from '../../../shared/lib/labels'
import { cliPhaseLabel, cliProviderLabel, presentEvent, presentNodeName } from '../../../shared/lib/presentation'
import styles from './TimelinePanel.module.less'

interface Props {
  detail: IterationDetail | null
  filter?: TimelineFilter
  onFilterChange?: (filter: TimelineFilter) => void
}

const EVENT_SEVERITY_CLASS: Record<string, string | undefined> = {
  danger: styles.eventDanger,
  info: styles.eventInfo,
  success: styles.eventSuccess,
  warning: styles.eventWarning,
  error: styles.eventError,
}

function matchesFilter(type: string, filter: TimelineFilter) {
  if (filter === 'all') return true
  if (filter === 'decisions') return type.includes('approved') || type.includes('queued')
  if (filter === 'failures') return type.includes('failed') || type.includes('blocked') || type.includes('max_retries')
  if (filter === 'tests') return type.includes('test') || type.includes('integrity') || type.includes('tester') || type.includes('ui_driver')
  if (filter === 'runs') return type === 'cli.display' || type.includes('planner') || type.includes('coder') || type.includes('tester')
  return true
}

export function TimelinePanel({ detail, filter = 'all', onFilterChange }: Props) {
  const events = detail?.events.filter((event) => matchesFilter(event.type, filter)).map(presentEvent) ?? []
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
      <div className={styles.timeline}>
        {events.map((event) => (
          <div key={event.id} className={`item ${styles.eventItem} ${EVENT_SEVERITY_CLASS[event.severity] ?? ''}`}>
            <div className="item-head">
              <strong>{event.title}</strong>
              <span className={`status-dot ${event.severity}`}>
                {event.type === 'cli.display' ? `${cliProviderLabel(event.provider)} · ${cliPhaseLabel(event.phase)}` : presentNodeName(event.node)}
              </span>
            </div>
            <div className="muted">{event.message}</div>
            {event.command ? <code className="inline-code">{event.command}</code> : null}
            {event.paths?.length ? <div className={styles.eventHint}>{event.paths.join(', ')}</div> : null}
            {event.action_hint ? <div className={styles.eventHint}>{event.action_hint}</div> : null}
            <details className={styles.eventDetails}>
              <summary>查看详情</summary>
              <pre className={styles.eventJson}>{JSON.stringify(event.raw.payload, null, 2)}</pre>
            </details>
          </div>
        ))}
        {!events.length ? <div className="empty">暂无事件</div> : null}
      </div>
    </section>
  )
}
