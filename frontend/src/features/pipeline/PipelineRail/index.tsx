import { connectionLabel, graphNodeLabel, iterationStatusLabel, retryLabel } from '../../../shared/lib/labels'
import { PIPELINE_STEPS, pipelineStepState, stepStateLabel, type PipelineStepKey } from '../lib/pipelineSteps'
import type { EpicSummary, IterationDetail, LiveConnectionStatus } from '../../../shared/lib/types'

interface Props {
  detail: IterationDetail | null
  epic: EpicSummary | null
  liveError: string | null
  connectionStatus: LiveConnectionStatus
  lastMessageAt: string | null
  reviewStepKey: PipelineStepKey | null
  onSelectStep: (key: PipelineStepKey | null) => void
}

function stepIcon(state: string, isLive: boolean) {
  if (state === 'complete') return '✓'
  if (state === 'active' || state === 'waiting' || isLive) return '●'
  return '○'
}

export function PipelineRail({
  detail,
  epic,
  liveError,
  connectionStatus,
  lastMessageAt,
  reviewStepKey,
  onSelectStep,
}: Props) {
  const uiEvents = detail?.events.filter((event) => event.type.startsWith('ui_driver.')) ?? []
  const lastUiEvent = uiEvents[uiEvents.length - 1]
  const connected = connectionStatus === 'connected'

  return (
    <aside className="pipeline-rail">
      <div className="pipeline-rail-top">
        <h2 className="rail-title">进度</h2>
        <div className="rail-meta">
          <span className={`connection-dot ${connected ? 'online' : ''}`} />
          <span className="muted">{connectionLabel[connectionStatus]}</span>
          {epic ? <span className="muted">· {epic.title}</span> : null}
        </div>
        {detail ? (
          <p className="muted rail-status">
            {iterationStatusLabel[detail.status]}
            {detail.graph_next.length ? ` · ${detail.graph_next.map(graphNodeLabel).join(', ')}` : ''}
          </p>
        ) : null}
      </div>

      <div className="progress-checklist">
        {PIPELINE_STEPS.map((step) => {
          const state = pipelineStepState(step.key, detail)
          const isReviewing = reviewStepKey === step.key
          const isLive = !reviewStepKey && (state === 'active' || state === 'waiting')
          return (
            <button
              key={step.key}
              type="button"
              className={`progress-row ${state} ${isReviewing ? 'reviewing' : ''} ${isLive ? 'live' : ''}`}
              onClick={() => onSelectStep(isReviewing ? null : step.key)}
              disabled={!detail}
            >
              <span className="progress-icon">{stepIcon(state, isLive)}</span>
              <span className="progress-label">{step.label}</span>
              <span className="progress-state">{stepStateLabel[state]}</span>
            </button>
          )
        })}
      </div>

      {(detail?.last_error || liveError) ? (
        <div className="rail-banner error">{detail?.last_error ?? liveError}</div>
      ) : null}

      {detail?.retry_counts && Object.keys(detail.retry_counts).length ? (
        <div className="rail-banner">
          {Object.entries(detail.retry_counts).map(([key, value]) => (
            <span key={key}>{retryLabel(key)}: {value}</span>
          ))}
        </div>
      ) : null}

      {uiEvents.length ? (
        <div className={`rail-banner ${lastUiEvent?.type.includes('failed') ? 'error' : lastUiEvent?.type.includes('warning') ? 'warning' : ''}`}>
          UI Driver · {lastUiEvent?.type === 'ui_driver.completed' ? '已完成' : lastUiEvent?.type === 'ui_driver.failed' ? '失败' : '运行中'}
        </div>
      ) : null}

      {reviewStepKey ? (
        <button type="button" className="btn btn-ghost btn-sm pipeline-rail-back" onClick={() => onSelectStep(null)}>
          返回当前阶段
        </button>
      ) : null}

      {lastMessageAt ? <p className="muted rail-footnote">更新 {new Date(lastMessageAt).toLocaleTimeString()}</p> : null}
    </aside>
  )
}
