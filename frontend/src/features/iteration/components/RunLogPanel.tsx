import { useEffect, useRef } from 'react'
import type { IterationDetail, LiveCliOutput, SemanticEvent } from '../../../shared/lib/types'
import type { PipelineStepKey } from '../../pipeline/lib/pipelineSteps'
import { nodesForStep } from '../../pipeline/lib/pipelineSteps'
import { nodeLabel } from '../../../shared/lib/labels'
import { cliPhaseLabel, cliProviderLabel, presentEvent, presentNodeName, summarizeRun } from '../../../shared/lib/presentation'

interface Props {
  detail: IterationDetail | null
  stepKey?: PipelineStepKey | null
}

const CLI_ACTIVE_STATUSES = new Set(['planning', 'coding', 'testing', 'retrying'])

function resolveLiveCli(detail: IterationDetail | null, stepKey: PipelineStepKey | null): LiveCliOutput | null {
  if (!detail?.live_cli) return null
  if (!stepKey) return detail.live_cli
  const nodes = new Set(nodesForStep(stepKey))
  const live = detail.live_cli
  if (nodes.has(live.node)) return live
  if (detail.current_node && nodes.has(detail.current_node)) {
    return { ...live, node: detail.current_node }
  }
  return null
}

function isCliStarting(detail: IterationDetail | null, stepKey: PipelineStepKey | null): boolean {
  if (!detail || !stepKey || !detail.current_node) return false
  if (!CLI_ACTIVE_STATUSES.has(detail.status)) return false
  return nodesForStep(stepKey).includes(detail.current_node)
}

function cliLogMessage(event: SemanticEvent): string {
  if (event.command) return event.command
  return event.message
}

export function RunLogPanel({ detail, stepKey = null }: Props) {
  const liveRef = useRef<HTMLPreElement>(null)
  const nodes = stepKey ? new Set(nodesForStep(stepKey)) : null
  const live = resolveLiveCli(detail, stepKey)
  const cliStarting = !live && isCliStarting(detail, stepKey)
  const runs = (detail?.runs ?? []).filter((run) => {
    if (!nodes) return true
    return nodes.has(run.node)
  })
  const cliDisplays = (detail?.events ?? [])
    .filter((event) => event.type === 'cli.display')
    .map(presentEvent)
    .filter((event) => !nodes || nodes.has(event.node))
    .slice(-30)
    .reverse()

  useEffect(() => {
    if (!liveRef.current) return
    liveRef.current.scrollTop = liveRef.current.scrollHeight
  }, [live?.stdout, live?.stderr])

  const liveText = live ? `${live.stdout}${live.stderr}` : ''
  const pendingNode = detail?.current_node ?? 'agent'

  return (
    <section className="panel stack">
      <h2 className="section-title">{stepKey ? '本阶段 CLI 日志' : '运行日志'}</h2>
      <div className="timeline">
        {cliDisplays.length ? (
          <div className="cli-log-stream" aria-label="CLI 操作流">
            {cliDisplays.map((event) => (
              <article key={event.id} className={`cli-log-row ${event.phase ?? 'text'} ${event.severity}`}>
                <div className="cli-log-meta">
                  <span>{cliProviderLabel(event.provider)}</span>
                  <span>{cliPhaseLabel(event.phase)}</span>
                  <span>{presentNodeName(event.node)}</span>
                </div>
                <div className="cli-log-body">
                  <strong>{event.title}</strong>
                  <p>{cliLogMessage(event)}</p>
                  {event.tool ? <span className="cli-log-detail">工具: {event.tool}</span> : null}
                  {event.paths?.length ? (
                    <div className="trace-paths">
                      {event.paths.map((path) => <span key={path}>{path}</span>)}
                    </div>
                  ) : null}
                  {event.preview && event.preview !== event.message ? <pre className="trace-preview">{event.preview}</pre> : null}
                </div>
              </article>
            ))}
          </div>
        ) : null}
        {live ? (
          <div className="item run-card live">
            <div className="item-head">
              <strong>{presentNodeName(live.node)} · 实时输出</strong>
              <span className="ok-text">streaming</span>
            </div>
            <pre ref={liveRef} className="code log live-cli-stream">{liveText || '等待 CLI 输出…'}</pre>
          </div>
        ) : null}
        {cliStarting ? (
          <div className="item run-card live">
            <div className="item-head">
              <strong>{presentNodeName(pendingNode)} · 实时输出</strong>
              <span className="ok-text">starting</span>
            </div>
            <pre className="code log live-cli-stream">CLI 启动中…</pre>
          </div>
        ) : null}
        {runs.map((run) => (
          <div key={run.id} className={`item run-card ${run.status === 'success' ? 'success' : 'error'}`}>
            <div className="item-head">
              <strong>{nodeLabel[run.node] ?? run.node}</strong>
              <span className={run.status === 'success' ? 'ok-text' : 'error-text'}>{run.status === 'success' ? '成功' : '失败'}</span>
            </div>
            <div className="muted">{summarizeRun(run).message}</div>
            <details className="run-details" open={Boolean(live)}>
              <summary>查看原始 JSONL / CLI 日志</summary>
              <div className="muted">{run.command}</div>
              <pre className="code log">{run.stdout || run.stderr || '暂无输出'}</pre>
            </details>
          </div>
        ))}
        {!runs.length && !live && !cliStarting ? <div className="empty">{stepKey ? '本阶段暂无 CLI 运行记录' : '暂无日志'}</div> : null}
      </div>
    </section>
  )
}
