import type { IterationDetail } from '../../../shared/lib/types'
import type { PipelineStepKey } from '../../pipeline/lib/pipelineSteps'
import { nodesForStep } from '../../pipeline/lib/pipelineSteps'
import { isAgentActivity, presentEvent, presentNodeName } from '../../../shared/lib/presentation'

interface Props {
  detail: IterationDetail | null
  stepKey?: PipelineStepKey | null
}

export function AgentActivityPanel({ detail, stepKey = null }: Props) {
  const nodes = stepKey ? new Set(nodesForStep(stepKey)) : null
  const activities = (detail?.events.filter(isAgentActivity).map(presentEvent) ?? []).filter((event) => {
    if (!nodes) return true
    return nodes.has(event.node)
  })
  const visible = (stepKey ? activities : activities.slice(-12)).slice().reverse()

  return (
    <section className="panel stack">
      <div className="section-row">
        <h2 className="section-title">{stepKey ? '本阶段 Agent 执行' : 'Agent 运行状态'}</h2>
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
        {!visible.length ? <div className="empty">本阶段 Agent 运行后，这里会显示中文步骤说明与产物状态。</div> : null}
      </div>
    </section>
  )
}
