import { useEffect, useRef } from 'react'
import type { IterationDetail } from '../../../shared/lib/types'
import type { PipelineStepKey } from '../../pipeline/lib/pipelineSteps'
import { nodesForStep } from '../../pipeline/lib/pipelineSteps'
import { nodeLabel } from '../../../shared/lib/labels'
import { presentNodeName, summarizeRun } from '../../../shared/lib/presentation'

interface Props {
  detail: IterationDetail | null
  stepKey?: PipelineStepKey | null
}

export function RunLogPanel({ detail, stepKey = null }: Props) {
  const liveRef = useRef<HTMLPreElement>(null)
  const nodes = stepKey ? new Set(nodesForStep(stepKey)) : null
  const live = detail?.live_cli && (!nodes || nodes.has(detail.live_cli.node)) ? detail.live_cli : null
  const runs = (detail?.runs ?? []).filter((run) => {
    if (!nodes) return true
    return nodes.has(run.node)
  })

  useEffect(() => {
    if (!liveRef.current) return
    liveRef.current.scrollTop = liveRef.current.scrollHeight
  }, [live?.stdout, live?.stderr])

  const liveText = live ? `${live.stdout}${live.stderr}` : ''

  return (
    <section className="panel stack">
      <h2 className="section-title">{stepKey ? '本阶段 CLI 日志' : '运行日志'}</h2>
      <div className="timeline">
        {live ? (
          <div className="item run-card live">
            <div className="item-head">
              <strong>{presentNodeName(live.node)} · 实时输出</strong>
              <span className="ok-text">streaming</span>
            </div>
            <pre ref={liveRef} className="code log live-cli-stream">{liveText || '等待 CLI 输出…'}</pre>
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
              <summary>查看原始 CLI 日志</summary>
              <div className="muted">{run.command}</div>
              <pre className="code log">{run.stdout || run.stderr || '暂无输出'}</pre>
            </details>
          </div>
        ))}
        {!runs.length && !live ? <div className="empty">{stepKey ? '本阶段暂无 CLI 运行记录' : '暂无日志'}</div> : null}
      </div>
    </section>
  )
}
