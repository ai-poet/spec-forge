import type { IterationDetail } from '../types'

interface Props {
  detail: IterationDetail | null
  liveError: string | null
  busy: boolean
  onApproveDesign: () => Promise<void>
  onApproveVerify: () => Promise<void>
  onStop: () => Promise<void>
}

const steps = [
  { key: 'planner', label: 'Planner' },
  { key: 'design_approval', label: 'Design approval' },
  { key: 'coder', label: 'Coder' },
  { key: 'tester', label: 'Tester' },
  { key: 'verify_approval', label: 'Verify approval' },
  { key: 'done', label: 'Delivered' },
]

export function PipelineBoard({ detail, liveError, busy, onApproveDesign, onApproveVerify, onStop }: Props) {
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
            {detail ? `status: ${detail.status} · next: ${detail.graph_next.length ? detail.graph_next.join(', ') : 'END'}` : '请选择流水线'}
          </div>
          {liveError ? <div className="error-text">{liveError}</div> : null}
        </div>
        <div className="actions">
          <button className="btn" onClick={onApproveDesign} disabled={busy || detail?.status !== 'awaiting_design_approval'}>
            Approve design
          </button>
          <button className="btn" onClick={onApproveVerify} disabled={busy || detail?.status !== 'awaiting_verify_approval'}>
            Approve verify
          </button>
          <button className="btn" onClick={onStop} disabled={busy || !detail}>
            Stop
          </button>
        </div>
      </div>

      <div className="graph-strip">
        {steps.map((step) => {
          const state = stepState(step.key)
          return (
            <div key={step.key} className={`graph-step ${state}`}>
              <strong>{step.label}</strong>
              <span>{state}</span>
            </div>
          )
        })}
      </div>
    </section>
  )
}
