import { graphNodeLabel, iterationStatusLabel, retryLabel } from '../labels'
import type { IterationDetail } from '../types'

interface Props {
  detail: IterationDetail | null
  liveError: string | null
}

const steps = [
  { key: 'planner', label: '规划' },
  { key: 'design_approval', label: '设计审批' },
  { key: 'coder', label: '实现' },
  { key: 'integrity_check', label: '测试完整性' },
  { key: 'tester', label: '独立验证' },
  { key: 'planner_verify', label: '规格复核' },
  { key: 'verify_approval', label: '验证确认' },
  { key: 'done', label: '交付完成' },
]

const stepStateLabel: Record<string, string> = {
  idle: '未开始',
  waiting: '等待中',
  active: '执行中',
  complete: '完成',
}

export function PipelineBoard({ detail, liveError }: Props) {
  const next = new Set(detail?.graph_next ?? [])
  const currentNode = detail?.current_node
  const status = detail?.status

  function stepState(key: string) {
    if (!detail) return 'idle'
    if (next.has(key)) return 'waiting'
    if (currentNode === key) return 'active'
    if (key === 'design_approval' && status === 'awaiting_design_approval') return 'waiting'
    if (key === 'verify_approval' && status === 'awaiting_verify_approval') return 'waiting'
    if (key === 'done' && status === 'delivered') return 'complete'
    return 'idle'
  }

  return (
    <section className="panel stack">
      <div className="section-row">
        <div>
          <h2 className="section-title">LangGraph 实时流转</h2>
          <div className="muted">
            {detail
              ? `状态: ${iterationStatusLabel[detail.status]} · 下一步: ${detail.graph_next.length ? detail.graph_next.map(graphNodeLabel).join(', ') : '结束'}`
              : '请选择流水线'}
          </div>
          {detail?.last_error ? <div className="error-text">最近错误: {detail.last_error}</div> : null}
          {detail?.retry_counts && Object.keys(detail.retry_counts).length ? (
            <div className="retry-row">
              {Object.entries(detail.retry_counts).map(([key, value]) => (
                <span className="pill" key={key}>{retryLabel(key)}: {value}</span>
              ))}
            </div>
          ) : null}
          {liveError ? <div className="error-text">{liveError}</div> : null}
        </div>
      </div>

      <div className="graph-strip">
        {steps.map((step) => {
          const state = stepState(step.key)
          return (
            <div key={step.key} className={`graph-step ${state}`}>
              <strong>{step.label}</strong>
              <span>{stepStateLabel[state]}</span>
            </div>
          )
        })}
      </div>
    </section>
  )
}
