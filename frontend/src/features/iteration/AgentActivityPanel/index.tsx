import type { IterationDetail } from '../../../shared/lib/types'
import type { PipelineStepKey } from '../../pipeline/lib/pipelineSteps'
import { nodesForStep } from '../../pipeline/lib/pipelineSteps'
import { isStepLive, latestNodeProgress } from '../../pipeline/lib/pipelineLive'
import { isAgentActivity, presentEvent, presentNodeName } from '../../../shared/lib/presentation'
import { RunningIndicator } from '../../../shared/ui/RunningIndicator'
import styles from './AgentActivityPanel.module.less'

interface Props {
  detail: IterationDetail | null
  stepKey?: PipelineStepKey | null
}

const SEVERITY_CLASS: Record<string, string | undefined> = {
  success: styles.itemSuccess,
  warning: styles.itemWarning,
  error: styles.itemError,
}

export function AgentActivityPanel({ detail, stepKey = null }: Props) {
  const nodes = stepKey ? new Set(nodesForStep(stepKey)) : null
  const activities = (detail?.events.filter(isAgentActivity).filter((event) => event.type !== 'cli.display').map(presentEvent) ?? []).filter((event) => {
    if (!nodes) return true
    return nodes.has(event.node)
  })
  const visible = (stepKey ? activities : activities.slice(-12)).slice().reverse()
  const stepLive = isStepLive(detail, stepKey)
  const progress = latestNodeProgress(detail, stepKey)
  const latestId = visible[0]?.id

  return (
    <section className="panel stack">
      <div className="section-row">
        <h2 className="section-title">{stepKey ? '本阶段 Agent 执行' : 'Agent 运行状态'}</h2>
        <div className={styles.headerMeta}>
          {stepLive ? <RunningIndicator size="sm" mode="dot" label="执行中" /> : null}
          <span className="pill">{activities.length} 条</span>
        </div>
      </div>
      {stepLive ? (
        <div className={styles.liveBanner}>
          <RunningIndicator mode="both" label={progress?.title ?? `${presentNodeName(detail?.current_node ?? 'agent')} 正在运行…`} />
          {progress?.message ? <p>{progress.message}</p> : null}
        </div>
      ) : null}
      <div className={styles.list}>
        {visible.map((event) => (
          <article key={event.id} className={`${styles.item} ${SEVERITY_CLASS[event.severity] ?? ''} ${event.id === latestId && stepLive ? styles.itemLive : ''}`}>
            <div>
              <div className={styles.titleRow}>
                <strong>{event.title}</strong>
              </div>
              <p>{event.message}</p>
              {event.command ? <code className="inline-code">{event.command}</code> : null}
              {event.paths?.length ? <small>{event.paths.join(', ')}</small> : null}
              {event.action_hint ? <small>{event.action_hint}</small> : null}
            </div>
            <span className={`status-dot ${event.severity}`}>{presentNodeName(event.node)}</span>
          </article>
        ))}
        {!visible.length ? (
          <div className="empty">
            {stepLive
              ? `${presentNodeName(detail?.current_node ?? 'agent')} 已启动，等待 Agent 活动事件…`
              : '本阶段 Agent 运行后，这里会显示中文步骤说明与产物状态。'}
          </div>
        ) : null}
      </div>
    </section>
  )
}
