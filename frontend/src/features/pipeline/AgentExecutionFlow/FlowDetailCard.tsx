import type { FlowNode } from '../lib/buildAgentFlow'
import { presentNodeName } from '../../../shared/lib/presentation'
import styles from './AgentExecutionFlow.module.less'

interface Props {
  milestone: FlowNode | null
}

export function FlowDetailCard({ milestone }: Props) {
  if (!milestone?.event && !milestone?.events?.length) {
    return (
      <div className={styles.detailEmpty}>
        点击上方里程碑节点查看详情。
      </div>
    )
  }

  const event = milestone.event ?? milestone.events?.[milestone.events.length - 1]
  if (!event) {
    return (
      <div className={styles.detailEmpty}>
        点击上方里程碑节点查看详情。
      </div>
    )
  }

  return (
    <article className={`${styles.detailCard} ${styles[`detail${capitalize(event.severity)}`] ?? ''}`}>
      <div className={styles.detailHeader}>
        <strong>{milestone.label || event.title}</strong>
        <span className={`status-dot ${event.severity}`}>{presentNodeName(event.node)}</span>
      </div>
      <p>{event.message}</p>
      {milestone.events && milestone.events.length > 1 ? (
        <ul className={styles.detailList}>
          {milestone.events.map((item) => (
            <li key={item.id}>
              {item.document ?? item.title}
              {item.message ? ` — ${item.message}` : ''}
            </li>
          ))}
        </ul>
      ) : null}
      {event.command ? <code className="inline-code">{event.command}</code> : null}
      {event.paths?.length ? <small>{event.paths.join(', ')}</small> : null}
      {event.action_hint ? <small>{event.action_hint}</small> : null}
      <time className={styles.detailTime}>{new Date(event.created_at).toLocaleString()}</time>
    </article>
  )
}

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1)
}
