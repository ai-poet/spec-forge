import { connectionLabel, graphNodeLabel, iterationStatusLabel, retryLabel } from '../labels'
import { PIPELINE_STEPS, pipelineStepState, stepStateLabel, type PipelineStepKey } from '../pipelineSteps'
import type { EpicSummary, IterationDetail, LiveConnectionStatus } from '../types'

interface Props {
  detail: IterationDetail | null
  epic: EpicSummary | null
  liveError: string | null
  connectionStatus: LiveConnectionStatus
  lastMessageAt: string | null
  reviewStepKey: PipelineStepKey | null
  onSelectStep: (key: PipelineStepKey | null) => void
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
  const progress = epic?.iteration_count ? Math.round((epic.delivered_count / epic.iteration_count) * 100) : 0
  const uiEvents = detail?.events.filter((event) => event.type.startsWith('ui_driver.')) ?? []
  const lastUiEvent = uiEvents[uiEvents.length - 1]

  return (
    <aside className="pipeline-rail stack">
      <div className="pipeline-rail-header">
        <h2 className="section-title">流水线</h2>
        <div className="pipeline-rail-metrics">
          <div className="metric-chip">
            <strong>{progress}%</strong>
            <span>Epic 进度</span>
          </div>
          <div className="metric-chip">
            <strong>{connectionLabel[connectionStatus]}</strong>
            <span>{lastMessageAt ? new Date(lastMessageAt).toLocaleTimeString() : '等待事件'}</span>
          </div>
        </div>
        {detail ? (
          <p className="muted pipeline-rail-status">
            {iterationStatusLabel[detail.status]}
            {detail.graph_next.length ? ` · 下一步: ${detail.graph_next.map(graphNodeLabel).join(', ')}` : ''}
          </p>
        ) : null}
        {detail?.last_error ? <div className="error-text">{detail.last_error}</div> : null}
        {liveError ? <div className="error-text">{liveError}</div> : null}
        {detail?.retry_counts && Object.keys(detail.retry_counts).length ? (
          <div className="retry-row">
            {Object.entries(detail.retry_counts).map(([key, value]) => (
              <span className="pill" key={key}>
                {retryLabel(key)}: {value}
              </span>
            ))}
          </div>
        ) : null}
      </div>

      <div className="pipeline-steps-vertical">
        {PIPELINE_STEPS.map((step, index) => {
          const state = pipelineStepState(step.key, detail)
          const isReviewing = reviewStepKey === step.key
          const isLive = !reviewStepKey && (state === 'active' || state === 'waiting')
          return (
            <button
              key={step.key}
              type="button"
              className={`pipeline-step-vertical ${state} ${isReviewing ? 'reviewing' : ''} ${isLive ? 'live' : ''}`}
              onClick={() => onSelectStep(isReviewing ? null : step.key)}
              disabled={!detail}
            >
              <div className="pipeline-step-marker">
                <span>{index + 1}</span>
                {index < PIPELINE_STEPS.length - 1 ? <i className="pipeline-step-line" /> : null}
              </div>
              <div className="pipeline-step-body">
                <strong>{step.label}</strong>
                <span>{stepStateLabel[state]}</span>
                <small>{step.hint}</small>
              </div>
            </button>
          )
        })}
      </div>

      {uiEvents.length ? (
        <div className={`tool-call-strip ${lastUiEvent?.type.includes('failed') ? 'failed' : lastUiEvent?.type.includes('warning') ? 'warning' : ''}`}>
          <strong>UI Driver</strong>
          <span>
            {lastUiEvent?.type === 'ui_driver.started'
              ? '正在执行 UI trajectory'
              : lastUiEvent?.type === 'ui_driver.completed'
                ? `已完成 ${String(lastUiEvent.payload.count ?? '')} 条 UI 验证`
                : lastUiEvent?.type === 'ui_driver.warning'
                  ? 'Cua 不可用，已降级'
                  : lastUiEvent?.type === 'ui_driver.failed'
                    ? 'UI 验证失败'
                    : '已记录 UI Driver 事件'}
          </span>
        </div>
      ) : null}

      {reviewStepKey ? (
        <button className="btn pipeline-rail-back" onClick={() => onSelectStep(null)}>
          返回当前阶段
        </button>
      ) : null}
    </aside>
  )
}
