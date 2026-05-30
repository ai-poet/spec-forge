import { useEffect, useMemo, useRef, useState } from 'react'
import type { IterationDetail, SemanticEvent } from '../../../shared/lib/types'
import type { PipelineStepKey } from '../../pipeline/lib/pipelineSteps'
import { nodesForStep } from '../../pipeline/lib/pipelineSteps'
import { isStepLive, latestNodeProgress } from '../../pipeline/lib/pipelineLive'
import { cliPhaseLabel, cliProviderLabel, presentEvent, presentNodeName } from '../../../shared/lib/presentation'
import { RunningIndicator } from '../../../shared/ui/RunningIndicator'
import styles from './RunLogPanel.module.less'

interface Props {
  detail: IterationDetail | null
  stepKey?: PipelineStepKey | null
}

const CLI_ACTIVE_STATUSES = new Set(['planning', 'coding', 'testing', 'retrying'])

function isCliActive(detail: IterationDetail | null, stepKey: PipelineStepKey | null): boolean {
  if (stepKey) return isStepLive(detail, stepKey)
  if (!detail || !detail.current_node) return false
  if (!CLI_ACTIVE_STATUSES.has(detail.status)) return false
  return true
}

function formatStructuredValue(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) {
    return value.map((item) => formatStructuredValue(item)).filter(Boolean).join('\n')
  }
  if (typeof value === 'object') {
    return Object.entries(value)
      .map(([key, item]) => {
        const formatted = formatStructuredValue(item)
        return formatted ? `${key}: ${formatted}` : key
      })
      .join('\n')
  }
  return String(value)
}

function formatCliText(value: string | undefined): string {
  const text = value?.trim() ?? ''
  if (!text) return ''
  if (!text.startsWith('{') && !text.startsWith('[')) return text
  try {
    return formatStructuredValue(JSON.parse(text))
  } catch {
    return '结构化输出已收到，正在整理展示。'
  }
}

function cliLogMessage(event: SemanticEvent): string {
  if (event.command) return event.command
  return formatCliText(event.message)
}

const PHASE_CLASS: Record<string, string | undefined> = {
  command: styles.phaseCommand,
  file_change: styles.phaseFileChange,
  mcp: styles.phaseMcp,
  tool: styles.phaseTool,
  todo: styles.phaseTodo,
}

function rowClassName(event: ReturnType<typeof presentEvent>, animatedIds: Set<string>): string {
  const phaseClass = PHASE_CLASS[event.phase ?? 'text']
  const severityClass =
    event.severity === 'error' ? styles.severityError : event.severity === 'warning' ? styles.severityWarning : ''
  return [styles.row, phaseClass, severityClass, animatedIds.has(event.id) ? styles.isNew : '']
    .filter(Boolean)
    .join(' ')
}

export function RunLogPanel({ detail, stepKey = null }: Props) {
  const initializedRef = useRef(false)
  const previousEventIdsRef = useRef<Set<string>>(new Set())
  const timersRef = useRef<Map<string, number>>(new Map())
  const scrollRef = useRef<HTMLDivElement>(null)
  const [animatedEventIds, setAnimatedEventIds] = useState<Set<string>>(new Set())
  const nodes = stepKey ? new Set(nodesForStep(stepKey)) : null
  const cliActive = isCliActive(detail, stepKey)
  const progress = latestNodeProgress(detail, stepKey)
  const cliDisplays = useMemo(
    () => (detail?.events ?? [])
      .filter((event) => event.type === 'cli.display')
      .map(presentEvent)
      .filter((event) => !nodes || nodes.has(event.node))
      .slice(-30)
      .reverse(),
    [detail?.events, stepKey],
  )
  const cliDisplayKey = cliDisplays.map((event) => event.id).join('|')
  const pendingNode = detail?.current_node ?? 'agent'

  useEffect(() => {
    const nextIds = new Set(cliDisplays.map((event) => event.id))
    if (!initializedRef.current) {
      initializedRef.current = true
      previousEventIdsRef.current = nextIds
      return
    }

    const newIds = cliDisplays.map((event) => event.id).filter((id) => !previousEventIdsRef.current.has(id))
    previousEventIdsRef.current = nextIds
    if (!newIds.length) return

    setAnimatedEventIds((prev) => {
      const next = new Set(prev)
      newIds.forEach((id) => next.add(id))
      return next
    })
    newIds.forEach((id) => {
      const previousTimer = timersRef.current.get(id)
      if (previousTimer) window.clearTimeout(previousTimer)
      const timer = window.setTimeout(() => {
        setAnimatedEventIds((prev) => {
          if (!prev.has(id)) return prev
          const next = new Set(prev)
          next.delete(id)
          return next
        })
        timersRef.current.delete(id)
      }, 1100)
      timersRef.current.set(id, timer)
    })
  }, [cliDisplayKey])

  useEffect(() => {
    if (!cliActive || !scrollRef.current) return
    scrollRef.current.scrollTop = 0
  }, [cliActive, cliDisplayKey])

  useEffect(() => () => {
    timersRef.current.forEach((timer) => window.clearTimeout(timer))
    timersRef.current.clear()
  }, [])

  return (
    <section className={`panel ${styles.root}`}>
      <div className="section-row">
        <h2 className="section-title">{stepKey ? '本阶段 CLI 日志' : '运行日志'}</h2>
        {cliActive ? <RunningIndicator size="sm" mode="dot" label="实时输出" /> : null}
      </div>
      {cliActive ? (
        <div className={styles.liveBanner}>
          <RunningIndicator mode="both" label={progress?.title ?? `${presentNodeName(pendingNode)} 正在运行…`} />
          {progress?.message ? <span>{progress.message}</span> : null}
        </div>
      ) : null}
      <div className={styles.scrollArea} ref={scrollRef}>
        {cliDisplays.length ? (
          <div className={styles.stream} aria-label="CLI 操作流">
            {cliDisplays.map((event) => {
              const message = cliLogMessage(event)
              const preview = formatCliText(event.preview)
              return (
                <article key={event.id} className={rowClassName(event, animatedEventIds)}>
                  <div className={styles.meta}>
                    <span>{cliProviderLabel(event.provider)}</span>
                    <span>{cliPhaseLabel(event.phase)}</span>
                    <span>{presentNodeName(event.node)}</span>
                  </div>
                  <div className={styles.body}>
                    <strong>{event.title}</strong>
                    {message ? <p>{message}</p> : null}
                    {event.tool ? <span className={styles.detail}>工具: {event.tool}</span> : null}
                    {event.paths?.length ? (
                      <div className={styles.paths}>
                        {event.paths.map((path) => <span key={path}>{path}</span>)}
                      </div>
                    ) : null}
                    {preview && preview !== message ? <pre className={styles.preview}>{preview}</pre> : null}
                  </div>
                </article>
              )
            })}
          </div>
        ) : (
          <div className="empty">
            {cliActive ? (
              <RunningIndicator label={`${presentNodeName(pendingNode)} 正在运行，等待格式化 CLI 事件…`} />
            ) : stepKey ? '本阶段暂无格式化 CLI 日志' : '暂无格式化 CLI 日志'}
          </div>
        )}
      </div>
    </section>
  )
}
