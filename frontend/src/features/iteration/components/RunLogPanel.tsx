import { useEffect, useRef } from 'react'
import type { IterationDetail, LiveCliOutput } from '../../../shared/lib/types'
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
          <div className="item run-card">
            <div className="item-head">
              <strong>原版 CLI 风格摘要</strong>
              <span className="status-dot info">{cliDisplays.length} 条</span>
            </div>
            <div className="cli-summary-list">
              {cliDisplays.map((event) => (
                <div key={event.id} className={`cli-summary-row ${event.severity}`}>
                  <span>{cliProviderLabel(event.provider)} · {cliPhaseLabel(event.phase)}</span>
                  <strong>{event.title}</strong>
                  <p>{event.command ?? event.message}</p>
                </div>
              ))}
            </div>
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
