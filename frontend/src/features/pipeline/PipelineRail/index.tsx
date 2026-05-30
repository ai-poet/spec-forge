import { connectionLabel, graphNodeLabel, iterationStatusLabel, retryLabel } from '../../../shared/lib/labels'
import { RunningIndicator } from '../../../shared/ui/RunningIndicator'
import { formatElapsed, isPipelineRunning, isUiDriverRunning, latestNodeProgress, runningNodeLabel } from '../lib/pipelineLive'
import { PIPELINE_STEPS, pipelineStepState, stepStateLabel, type PipelineStepKey } from '../lib/pipelineSteps'
import type { EpicSummary, IterationDetail, LiveConnectionStatus } from '../../../shared/lib/types'
import styles from './PipelineRail.module.less'

interface Props {
  detail: IterationDetail | null
  epic: EpicSummary | null
  liveError: string | null
  connectionStatus: LiveConnectionStatus
  lastMessageAt: string | null
  reviewStepKey: PipelineStepKey | null
  onSelectStep: (key: PipelineStepKey | null) => void
}

const ROW_STATE_CLASS: Record<string, string | undefined> = {
  active: styles.rowActive,
  waiting: styles.rowWaiting,
  complete: styles.rowComplete,
  idle: styles.rowIdle,
}

function stepIcon(state: string, isLive: boolean) {
  if (state === 'complete') return '✓'
  if (isLive) return null
  if (state === 'active' || state === 'waiting') return '●'
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
  const uiDriverRunning = isUiDriverRunning(detail)
  const connected = connectionStatus === 'connected'
  const running = isPipelineRunning(detail)
  const progress = latestNodeProgress(detail)
  const currentNode = runningNodeLabel(detail)
  const elapsed = running ? formatElapsed(detail?.updated_at ?? lastMessageAt) : null

  return (
    <aside className={styles.rail}>
      <div className={styles.top}>
        <h2 className={styles.railTitle}>进度</h2>
        <div className={styles.railMeta}>
          <span className={`${styles.connectionDot} ${connected ? styles.online : ''} ${connectionStatus === 'connecting' || connectionStatus === 'reconnecting' ? styles.connecting : ''}`} />
          <span className="muted">{connectionLabel[connectionStatus]}</span>
          {epic ? <span className="muted">· {epic.title}</span> : null}
        </div>
        {detail ? (
          <p className={`muted ${styles.railStatus}`}>
            {iterationStatusLabel[detail.status]}
            {currentNode ? ` · ${currentNode}` : ''}
            {detail.graph_next.length ? ` · 下一步 ${detail.graph_next.map(graphNodeLabel).join(', ')}` : ''}
          </p>
        ) : null}
        {running && progress ? (
          <div className={styles.railProgress}>
            <RunningIndicator size="sm" mode="dot" label={progress.title} />
            {progress.message ? <p className={styles.railProgressMessage}>{progress.message}</p> : null}
          </div>
        ) : null}
        {running && !progress && currentNode ? (
          <div className={styles.railProgress}>
            <RunningIndicator size="sm" mode="dot" label={`${currentNode} 执行中…`} />
          </div>
        ) : null}
      </div>

      <div className={styles.checklist}>
        {PIPELINE_STEPS.map((step) => {
          const state = pipelineStepState(step.key, detail)
          const isReviewing = reviewStepKey === step.key
          const isLive = !reviewStepKey && (state === 'active' || state === 'waiting')
          const icon = stepIcon(state, isLive)
          return (
            <button
              key={step.key}
              type="button"
              className={[styles.progressRow, ROW_STATE_CLASS[state], isReviewing ? styles.rowReviewing : '', isLive ? styles.rowLive : ''].filter(Boolean).join(' ')}
              onClick={() => onSelectStep(isReviewing ? null : step.key)}
              disabled={!detail}
            >
              <span className={`${styles.progressIcon} ${isLive ? styles.progressIconLive : ''}`}>
                {icon ?? <span className={styles.liveDot} aria-hidden="true" />}
              </span>
              <span className={styles.progressLabel}>{step.label}</span>
              <span className={styles.progressState}>{isLive ? '执行中' : stepStateLabel[state]}</span>
            </button>
          )
        })}
      </div>

      {(detail?.last_error || liveError) ? (
        <div className={`${styles.railBanner} ${styles.error}`}>{detail?.last_error ?? liveError}</div>
      ) : null}

      {detail?.retry_counts && Object.keys(detail.retry_counts).length ? (
        <div className={styles.railBanner}>
          {Object.entries(detail.retry_counts).map(([key, value]) => (
            <span key={key}>{retryLabel(key)}: {value}</span>
          ))}
        </div>
      ) : null}

      {uiDriverRunning ? (
        <div className={`${styles.railBanner} ${styles.running}`}>
          <RunningIndicator size="sm" mode="dot" label="UI Driver 运行中" />
        </div>
      ) : uiEvents.length ? (
        <div className={`${styles.railBanner} ${lastUiEvent?.type.includes('failed') || lastUiEvent?.type.includes('warning') ? styles.warning : ''}`}>
          UI Driver · {lastUiEvent?.type === 'ui_driver.completed' ? '已完成' : lastUiEvent?.type === 'ui_driver.failed' ? '需复核' : '运行中'}
        </div>
      ) : null}

      {reviewStepKey ? (
        <button type="button" className={`btn btn-ghost btn-sm ${styles.railBack}`} onClick={() => onSelectStep(null)}>
          返回当前阶段
        </button>
      ) : null}

      {lastMessageAt ? (
        <p className={`muted ${styles.railFootnote}`}>
          更新 {new Date(lastMessageAt).toLocaleTimeString()}
          {elapsed ? ` · 已运行 ${elapsed}` : ''}
        </p>
      ) : null}
    </aside>
  )
}
