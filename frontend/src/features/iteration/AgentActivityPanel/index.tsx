import type { IterationDetail } from '../../../shared/lib/types'
import type { PipelineStepKey } from '../../pipeline/lib/pipelineSteps'
import { nodesForStep } from '../../pipeline/lib/pipelineSteps'
import { isStepLive, latestNodeProgress } from '../../pipeline/lib/pipelineLive'
import { isAgentActivity, presentEvent, presentNodeName } from '../../../shared/lib/presentation'
import { RunningIndicator } from '../../../shared/ui/RunningIndicator'
import { defaultExpandedRunIds, groupAgentActivities } from '../../pipeline/lib/groupAgentRuns'
import { useEffect, useMemo, useState } from 'react'
import styles from './AgentActivityPanel.module.less'

interface Props {
  detail: IterationDetail | null
  stepKey?: PipelineStepKey | null
  reviewMode?: boolean
}

const SEVERITY_CLASS: Record<string, string | undefined> = {
  success: styles.itemSuccess,
  warning: styles.itemWarning,
  error: styles.itemError,
}

export function AgentActivityPanel({ detail, stepKey = null, reviewMode = false }: Props) {
  const nodes = stepKey ? new Set(nodesForStep(stepKey)) : null
  const activities = useMemo(
    () => (detail?.events.filter(isAgentActivity).filter((event) => event.type !== 'cli.display').map(presentEvent) ?? []).filter((event) => {
      if (!nodes) return true
      return nodes.has(event.node)
    }),
    [detail?.events, stepKey],
  )
  const stepLive = !reviewMode && isStepLive(detail, stepKey)
  const progress = latestNodeProgress(detail, stepKey)
  const hasVerifyReject = Boolean((detail?.retry_counts?.planner_verify_reject ?? 0) > 0)
  const grouped = useMemo(
    () => groupAgentActivities(activities, stepKey, { reviewMode, stepLive, hasVerifyReject }),
    [activities, stepKey, reviewMode, stepLive, hasVerifyReject],
  )
  const groupKey = grouped.groups.map((group) => group.id).join('|')
  const [expanded, setExpanded] = useState<Set<string>>(() => defaultExpandedRunIds(grouped.groups, reviewMode))

  useEffect(() => {
    setExpanded(defaultExpandedRunIds(grouped.groups, reviewMode))
  }, [groupKey, reviewMode])

  const countLabel = grouped.roundCount > 1
    ? `当前轮 ${grouped.currentRoundEvents} 条 · 共 ${grouped.roundCount} 轮`
    : `${grouped.totalEvents} 条`

  function toggleGroup(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function renderEvent(event: ReturnType<typeof presentEvent>, highlight: boolean) {
    return (
      <article key={event.id} className={`${styles.item} ${SEVERITY_CLASS[event.severity] ?? ''} ${highlight ? styles.itemLive : ''}`}>
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
    )
  }

  return (
    <section className="panel stack">
      <div className="section-row">
        <h2 className="section-title">{stepKey ? '本阶段 Agent 执行' : 'Agent 运行状态'}</h2>
        <div className={styles.headerMeta}>
          {stepLive ? <RunningIndicator size="sm" mode="dot" label="执行中" /> : null}
          <span className="pill">{countLabel}</span>
        </div>
      </div>
      {stepLive ? (
        <div className={styles.liveBanner}>
          <RunningIndicator mode="both" label={progress?.title ?? `${presentNodeName(detail?.current_node ?? 'agent')} 正在运行…`} />
          {progress?.message ? <p>{progress.message}</p> : null}
        </div>
      ) : null}
      <div className={styles.list}>
        {grouped.groups.length > 1 ? (
          grouped.groups.map((group) => {
            const isOpen = expanded.has(group.id)
            const visibleEvents = [...group.events].reverse()
            const latestId = visibleEvents[0]?.id
            return (
              <div key={group.id} className={styles.runBlock}>
                {group.separatorBefore ? (
                  <div className={styles.runSeparator}>{group.separatorBefore}</div>
                ) : null}
                <button type="button" className={styles.runToggle} onClick={() => toggleGroup(group.id)}>
                  <span>{group.label}</span>
                  <span className="muted">{group.events.length} 条 {isOpen ? '▾' : '▸'}</span>
                </button>
                {isOpen ? (
                  <div className={styles.runEvents}>
                    {visibleEvents.map((event) => renderEvent(event, stepLive && event.id === latestId))}
                  </div>
                ) : null}
              </div>
            )
          })
        ) : grouped.groups[0] ? (
          [...grouped.groups[0].events].reverse().map((event, index, list) => renderEvent(event, stepLive && index === 0))
        ) : null}
        {!grouped.totalEvents ? (
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
