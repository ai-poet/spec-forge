import { useEffect, useMemo, useRef, useState } from 'react'
import { getRunContextPackage, getRunLogs, getRunPromptBundle, getRunWorkerRef } from '../../../shared/lib/api'
import type { ContextPackagePayload, IterationDetail, NodeRunRecord, PromptBundlePayload, RunLogPage, SemanticEvent, WorkerRefPayload } from '../../../shared/lib/types'
import type { PipelineStepKey } from '../../pipeline/lib/pipelineSteps'
import { nodesForStep } from '../../pipeline/lib/pipelineSteps'
import { isStepLive, latestNodeProgress } from '../../pipeline/lib/pipelineLive'
import { defaultExpandedRunIds, groupAgentActivities } from '../../pipeline/lib/groupAgentRuns'
import { mergeCliDisplayEvents } from '../../../shared/lib/cliDisplayMerge'
import { cliPhaseLabel, cliProviderLabel, presentEvent, presentNodeName } from '../../../shared/lib/presentation'
import { buildToolCardView } from '../../../shared/lib/toolPresentation'
import { RunningIndicator } from '../../../shared/ui/RunningIndicator'
import styles from './RunLogPanel.module.less'

interface Props {
  detail: IterationDetail | null
  stepKey?: PipelineStepKey | null
  reviewMode?: boolean
}

const CLI_ACTIVE_STATUSES = new Set(['planning', 'coding', 'testing', 'retrying'])

function isCliActive(detail: IterationDetail | null, stepKey: PipelineStepKey | null, reviewMode: boolean): boolean {
  if (reviewMode) return false
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
    return 'Agent 产物已收到，正在整理展示。'
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
  hook: styles.phaseHook,
}

function rowClassName(event: ReturnType<typeof presentEvent>, animatedIds: Set<string>): string {
  const phaseClass = PHASE_CLASS[event.phase ?? 'text']
  const severityClass =
    event.severity === 'error' ? styles.severityError : event.severity === 'warning' ? styles.severityWarning : ''
  return [styles.row, phaseClass, severityClass, animatedIds.has(event.id) ? styles.isNew : '']
    .filter(Boolean)
    .join(' ')
}

function ToolCardBody({ event }: { event: SemanticEvent }) {
  const card = buildToolCardView(event)
  if (!card) return null
  return (
    <div className={styles.toolCard}>
      <span className={styles.toolKind}>{card.headline}</span>
      {card.command ? <pre className={styles.toolCommand}>{card.command}</pre> : null}
      {card.paths.length ? (
        <div className={styles.paths}>
          {card.paths.map((path) => (
            <span key={path}>{path}</span>
          ))}
        </div>
      ) : null}
      {card.todos.length ? (
        <ul className={styles.todoList}>
          {card.todos.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : null}
      {card.detail && card.detail !== card.command ? <pre className={styles.preview}>{formatCliText(card.detail)}</pre> : null}
    </div>
  )
}

function RawCliFold({ detail, cliActive }: { detail: IterationDetail | null; cliActive: boolean }) {
  const [open, setOpen] = useState(false)
  const live = detail?.live_cli
  const hasStdout = Boolean(live?.stdout?.trim())
  const hasStderr = Boolean(live?.stderr?.trim())
  if (!hasStdout && !hasStderr && !cliActive) return null

  return (
    <details className={styles.rawFold} open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>查看原始 CLI 输出{cliActive ? '（实时）' : ''}</summary>
      {hasStdout ? (
        <pre className={styles.rawBlock} aria-label="stdout">
          {live?.stdout}
        </pre>
      ) : null}
      {hasStderr ? (
        <pre className={`${styles.rawBlock} ${styles.rawStderr}`} aria-label="stderr">
          {live?.stderr}
        </pre>
      ) : null}
      {cliActive && !hasStdout && !hasStderr ? <p className="muted">等待原始流…</p> : null}
    </details>
  )
}

function providerLabel(provider: string | null | undefined) {
  if (provider === 'claude') return 'Claude Code'
  if (provider === 'codex') return 'Codex'
  return 'CLI'
}

function runDuration(run: NodeRunRecord) {
  if (typeof run.duration_ms === 'number') return `${Math.max(0, Math.round(run.duration_ms / 1000))}s`
  return '未记录'
}

function RunTraceList({
  detail,
  runs,
  onSelect,
}: {
  detail: IterationDetail | null
  runs: NodeRunRecord[]
  onSelect: (run: NodeRunRecord) => void
}) {
  if (!detail || !runs.length) return null
  return (
    <div className={styles.traceList}>
      {runs.map((run, index) => (
        <button key={run.id} type="button" className={styles.traceRow} onClick={() => onSelect(run)}>
          <span className={styles.traceIndex}>{index + 1}</span>
          <span className={styles.traceMain}>
            <strong>{presentNodeName(run.node)}</strong>
            <span>{providerLabel(run.provider)} · {run.session_mode ?? 'new'} · {runDuration(run)}</span>
          </span>
          <span className={`${styles.traceStatus} ${run.status === 'success' ? styles.traceOk : styles.traceFail}`}>
            {run.timed_out ? 'timeout' : run.status}
          </span>
        </button>
      ))}
    </div>
  )
}

function JsonBlock({ value }: { value: unknown }) {
  return <pre className={styles.drawerCode}>{JSON.stringify(value, null, 2)}</pre>
}

function AttemptDrawer({
  detail,
  run,
  onClose,
}: {
  detail: IterationDetail
  run: NodeRunRecord
  onClose: () => void
}) {
  const [tab, setTab] = useState<'details' | 'raw' | 'context' | 'prompt' | 'worker'>('details')
  const [logs, setLogs] = useState<RunLogPage | null>(null)
  const [contextPackage, setContextPackage] = useState<ContextPackagePayload | null>(null)
  const [prompt, setPrompt] = useState<PromptBundlePayload | null>(null)
  const [workerRef, setWorkerRef] = useState<WorkerRefPayload | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setTab('details')
    setLogs(null)
    setContextPackage(null)
    setPrompt(null)
    setWorkerRef(null)
    setError(null)
  }, [run.id])

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        if (tab === 'raw' && !logs) {
          const page = await getRunLogs(detail.id, run.id, 0, 200)
          if (!cancelled) setLogs(page)
        }
        if (tab === 'context' && !contextPackage) {
          const payload = await getRunContextPackage(detail.id, run.id)
          if (!cancelled) setContextPackage(payload)
        }
        if (tab === 'prompt' && !prompt) {
          const payload = await getRunPromptBundle(detail.id, run.id)
          if (!cancelled) setPrompt(payload)
        }
        if (tab === 'worker' && !workerRef) {
          const payload = await getRunWorkerRef(detail.id, run.id)
          if (!cancelled) setWorkerRef(payload)
        }
      } catch (exc) {
        if (!cancelled) setError(exc instanceof Error ? exc.message : '读取失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    if (tab !== 'details') load().catch(console.error)
    return () => {
      cancelled = true
    }
  }, [tab, detail.id, run.id, logs, contextPackage, prompt, workerRef])

  async function loadMoreLogs() {
    if (!logs || loading) return
    setLoading(true)
    try {
      const page = await getRunLogs(detail.id, run.id, logs.offset + logs.items.length, logs.limit)
      setLogs({ ...page, items: [...logs.items, ...page.items], offset: 0 })
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : '读取失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <aside className={styles.drawer} aria-label="Attempt detail">
      <div className={styles.drawerHeader}>
        <div>
          <p className="eyebrow">Attempt trace</p>
          <h3>{presentNodeName(run.node)}</h3>
        </div>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>关闭</button>
      </div>
      <div className={styles.drawerTabs}>
        <button type="button" className={tab === 'details' ? styles.tabActive : ''} onClick={() => setTab('details')}>详情</button>
        <button type="button" className={tab === 'raw' ? styles.tabActive : ''} onClick={() => setTab('raw')}>原始输出</button>
        <button type="button" className={tab === 'context' ? styles.tabActive : ''} onClick={() => setTab('context')}>Context</button>
        <button type="button" className={tab === 'prompt' ? styles.tabActive : ''} onClick={() => setTab('prompt')} disabled={!run.prompt_url}>Prompt</button>
        <button type="button" className={tab === 'worker' ? styles.tabActive : ''} onClick={() => setTab('worker')} disabled={!run.worker_ref_url}>WorkerRef</button>
      </div>
      {error ? <div className="error-text">{error}</div> : null}
      {tab === 'details' ? (
        <div className={styles.drawerGrid}>
          <span>Run ID</span><strong>{run.id}</strong>
          <span>Provider</span><strong>{providerLabel(run.provider)}</strong>
          <span>Session</span><strong>{run.session_id ?? '未捕获'}</strong>
          <span>Mode</span><strong>{run.session_mode ?? 'new'}</strong>
          <span>Status</span><strong>{run.timed_out ? 'timeout' : run.status}</strong>
          <span>Exit code</span><strong>{run.exit_code ?? 'unknown'}</strong>
          <span>Output</span><strong>{run.stdout_bytes + run.stderr_bytes} bytes</strong>
          <span>Prompt hash</span><strong className={styles.mono}>{run.prompt_hash ?? 'n/a'}</strong>
        </div>
      ) : null}
      {tab === 'raw' ? (
        <div className={styles.rawPage}>
          {loading && !logs ? <RunningIndicator label="读取原始输出…" /> : null}
          {logs?.items.map((line, index) => (
            <pre key={`${line.stream}-${line.line}-${index}`} className={line.stream === 'stderr' ? styles.rawErrLine : styles.rawLine}>
              <span>{line.stream}:{line.line}</span> {line.text}
            </pre>
          ))}
          {logs?.has_more ? <button type="button" className="btn btn-sm" onClick={loadMoreLogs} disabled={loading}>{loading ? '读取中' : '加载更多'}</button> : null}
          {logs && !logs.items.length ? <div className="empty">没有原始输出。</div> : null}
        </div>
      ) : null}
      {tab === 'prompt' ? (
        loading && !prompt ? <RunningIndicator label="读取 Prompt Bundle…" /> : prompt ? <JsonBlock value={prompt} /> : null
      ) : null}
      {tab === 'context' ? (
        loading && !contextPackage ? <RunningIndicator label="读取 Context Package…" /> : contextPackage ? <JsonBlock value={contextPackage} /> : null
      ) : null}
      {tab === 'worker' ? (
        loading && !workerRef ? <RunningIndicator label="读取 WorkerRef…" /> : workerRef ? <JsonBlock value={workerRef} /> : null
      ) : null}
    </aside>
  )
}

export function RunLogPanel({ detail, stepKey = null, reviewMode = false }: Props) {
  const initializedRef = useRef(false)
  const previousEventIdsRef = useRef<Set<string>>(new Set())
  const timersRef = useRef<Map<string, number>>(new Map())
  const scrollRef = useRef<HTMLDivElement>(null)
  const [animatedEventIds, setAnimatedEventIds] = useState<Set<string>>(new Set())
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [selectedRun, setSelectedRun] = useState<NodeRunRecord | null>(null)
  const nodes = stepKey ? new Set(nodesForStep(stepKey)) : null
  const cliActive = isCliActive(detail, stepKey, reviewMode)
  const progress = latestNodeProgress(detail, stepKey)
  const cliDisplays = useMemo(() => {
    const raw = (detail?.events ?? [])
      .filter((event) => event.type === 'cli.display')
      .map(presentEvent)
      .filter((event) => !nodes || nodes.has(event.node))
    return mergeCliDisplayEvents(raw)
  }, [detail?.events, stepKey])
  const hasVerifyReject = Boolean((detail?.retry_counts?.planner_verify_reject ?? 0) > 0)
  const grouped = useMemo(
    () => groupAgentActivities(cliDisplays, stepKey, { reviewMode, stepLive: cliActive, hasVerifyReject }),
    [cliDisplays, stepKey, reviewMode, cliActive, hasVerifyReject],
  )
  const visibleCliDisplays = useMemo(() => {
    if (grouped.roundCount <= 1) {
      return [...cliDisplays].slice(-30).reverse()
    }
    const openGroups = grouped.groups.filter((group) => expanded.has(group.id))
    const source = openGroups.length ? openGroups : grouped.groups.filter((group) => group.isCurrent)
    return source.flatMap((group) => [...group.events].reverse())
  }, [cliDisplays, grouped, expanded])
  const cliDisplayKey = visibleCliDisplays.map((event) => event.id).join('|')
  const groupKey = grouped.groups.map((group) => group.id).join('|')
  const pendingNode = detail?.current_node ?? 'agent'
  const visibleRuns = useMemo(() => {
    const source = detail?.runs ?? []
    if (!nodes) return source
    return source.filter((run) => nodes.has(run.node))
  }, [detail?.runs, stepKey])

  useEffect(() => {
    setExpanded(defaultExpandedRunIds(grouped.groups, reviewMode))
  }, [groupKey, reviewMode])

  useEffect(() => {
    const nextIds = new Set(visibleCliDisplays.map((event) => event.id))
    if (!initializedRef.current) {
      initializedRef.current = true
      previousEventIdsRef.current = nextIds
      return
    }

    const newIds = visibleCliDisplays.map((event) => event.id).filter((id) => !previousEventIdsRef.current.has(id))
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

  function toggleGroup(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function renderCliRow(event: ReturnType<typeof presentEvent>) {
    const message = cliLogMessage(event)
    const preview = formatCliText(event.preview)
    const toolCard = buildToolCardView(event)
    const showStreamPreview = (event.phase === 'text' || event.phase === 'thinking') && preview
    return (
      <article key={event.id} className={rowClassName(event, animatedEventIds)}>
        <div className={styles.meta}>
          <span>{cliProviderLabel(event.provider)}</span>
          <span>{cliPhaseLabel(event.phase)}</span>
          <span>{presentNodeName(event.node)}</span>
        </div>
        <div className={styles.body}>
          <strong>{event.title}</strong>
          {toolCard ? <ToolCardBody event={event} /> : null}
          {!toolCard && message ? <p>{message}</p> : null}
          {!toolCard && event.tool ? <span className={styles.detail}>工具: {event.tool}</span> : null}
          {!toolCard && event.paths?.length ? (
            <div className={styles.paths}>
              {event.paths.map((path) => (
                <span key={path}>{path}</span>
              ))}
            </div>
          ) : null}
          {showStreamPreview ? <pre className={styles.streamPreview}>{preview}</pre> : null}
          {!toolCard && preview && preview !== message && !showStreamPreview ? (
            <pre className={styles.preview}>{preview}</pre>
          ) : null}
        </div>
      </article>
    )
  }

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
      <p className={styles.permissionHint}>流水线模式：Agent 权限按 provider 自动配置，无需逐项确认。</p>
      <RunTraceList detail={detail} runs={visibleRuns} onSelect={setSelectedRun} />
      <RawCliFold detail={detail} cliActive={cliActive} />
      {grouped.roundCount > 1 ? (
        <div className={styles.runToggles}>
          {grouped.groups.map((group) => (
            <button
              key={group.id}
              type="button"
              className={`${styles.runToggle} ${expanded.has(group.id) ? styles.runToggleOpen : ''}`}
              onClick={() => toggleGroup(group.id)}
            >
              {group.label} · {group.events.length} 条 {expanded.has(group.id) ? '▾' : '▸'}
            </button>
          ))}
        </div>
      ) : null}
      <div className={styles.scrollArea} ref={scrollRef}>
        {visibleCliDisplays.length ? (
          <div className={styles.stream} aria-label="CLI 操作流">
            {visibleCliDisplays.map((event) => renderCliRow(event))}
          </div>
        ) : (
          <div className="empty">
            {cliActive ? (
              <RunningIndicator label={`${presentNodeName(pendingNode)} 正在运行，等待格式化 CLI 事件…`} />
            ) : stepKey ? (
              '本阶段暂无格式化 CLI 日志'
            ) : (
              '暂无格式化 CLI 日志'
            )}
          </div>
        )}
      </div>
      {detail && selectedRun ? <AttemptDrawer detail={detail} run={selectedRun} onClose={() => setSelectedRun(null)} /> : null}
    </section>
  )
}
