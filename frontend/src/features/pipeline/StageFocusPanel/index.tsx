import type { IterationDetail } from '../../../shared/lib/types'
import { RunningIndicator } from '../../../shared/ui/RunningIndicator'
import type { PipelineStepKey } from '../lib/pipelineSteps'
import { inferFocusStep, PIPELINE_STEPS } from '../lib/pipelineSteps'
import { isPipelineRunning, isStepLive, latestNodeProgress, runningNodeLabel } from '../lib/pipelineLive'
import { ActionPanel } from '../../iteration/ActionPanel'
import { DocumentPanel } from '../../iteration/DocumentPanel'
import { IterationSummaryPanel } from '../../iteration/IterationSummaryPanel'
import { StepExecutionPanel } from '../StepExecutionPanel'
import { TimelinePanel } from '../../iteration/TimelinePanel'
import { UIVerificationPanel } from '../../iteration/UIVerificationPanel'
import styles from './StageFocusPanel.module.less'

interface Props {
  detail: IterationDetail | null
  docText: string
  reviewStepKey: PipelineStepKey | null
  onSelectStep?: (key: PipelineStepKey | null) => void
  isLoading: boolean
  busy: boolean
  onLoadDocument: (name: string) => Promise<void>
  onApproveVerify: () => Promise<void>
  onStop: () => Promise<void>
  onResume: () => Promise<void>
}

export function StageFocusPanel({
  detail,
  docText,
  reviewStepKey,
  onSelectStep,
  isLoading,
  busy,
  onLoadDocument,
  onApproveVerify,
  onStop,
  onResume,
}: Props) {
  const reviewMode = Boolean(reviewStepKey)
  const focusStep = reviewStepKey ?? (detail ? inferFocusStep(detail) : null)
  const stepMeta = PIPELINE_STEPS.find((step) => step.key === focusStep)
  const stepLive = !reviewMode && isStepLive(detail, focusStep)
  const progress = latestNodeProgress(detail, focusStep)
  const pipelineRunning = isPipelineRunning(detail)
  const liveNode = runningNodeLabel(detail)

  async function loadFirstDoc(names: string[]) {
    if (!detail) return
    const doc = detail.documents.find((item) => names.includes(item.name))
    if (doc) await onLoadDocument(doc.name)
  }

  function renderStepExtras(step: PipelineStepKey) {
    if (!detail) return null
    switch (step) {
      case 'planner':
        return <DocumentPanel detail={detail} docText={docText} onLoadDocument={onLoadDocument} />
      case 'coder':
        return <IterationSummaryPanel detail={detail} />
      case 'integrity_check':
      case 'tester':
      case 'planner_verify':
        return (
          <div className="stack">
            <UIVerificationPanel detail={detail} />
            <TimelinePanel detail={detail} filter="tests" />
          </div>
        )
      case 'verify_approval':
      case 'done':
        return (
          <div className="stack">
            <IterationSummaryPanel detail={detail} />
            <DocumentPanel detail={detail} docText={docText} onLoadDocument={onLoadDocument} />
          </div>
        )
      default:
        return null
    }
  }

  function renderStepContent() {
    if (!detail || !focusStep) return null
    return (
      <div className="stack">
        <StepExecutionPanel
          detail={detail}
          stepKey={focusStep}
          reviewMode={reviewMode}
          reviewStepKey={reviewStepKey}
          onSelectStep={onSelectStep}
        />
        {renderStepExtras(focusStep)}
      </div>
    )
  }

  if (isLoading && !detail) {
    return (
      <section className={`${styles.section} ${styles.loading}`}>
        <RunningIndicator label="正在加载流水线状态…" />
        <div className={styles.skeletonStack}>
          <div className={styles.skeletonBar} />
          <div className={styles.skeletonPanel} />
          <div className={styles.skeletonPanel} />
        </div>
      </section>
    )
  }

  if (!detail) {
    return (
      <section className={styles.section}>
        <p className="muted">请选择一条流水线查看当前阶段。</p>
      </section>
    )
  }

  const isBlocked = ['blocked', 'blocked_user', 'stopped', 'failed'].includes(detail.status)

  return (
    <div className={styles.focus}>
      {reviewMode ? (
        <div className={styles.banner}>
          <strong>回顾：{stepMeta?.label}</strong>
          <span className="muted">
            {pipelineRunning
              ? `只读查看该阶段历史；流水线仍在运行${liveNode ? `（当前：${liveNode}）` : ''}。`
              : '只读查看该阶段产物与 Agent 执行详情。'}
          </span>
        </div>
      ) : null}

      <div className={styles.stickyBar}>
        <ActionPanel
          detail={detail}
          reviewMode={reviewMode}
          busy={busy}
          onApproveVerify={onApproveVerify}
          onStop={onStop}
          onResume={onResume}
        />
      </div>

      {isBlocked && !reviewMode ? (
        <section className={`surface stack ${styles.section}`}>
          <TimelinePanel detail={detail} filter="failures" />
        </section>
      ) : null}

      <section className={`${styles.section} stack ${styles.content}`}>
        <div className="section-row">
          <div>
            <p className="eyebrow">{reviewMode ? '阶段回顾' : '当前阶段'}</p>
            <div className={styles.stageTitleRow}>
              <h2 className="section-title">{stepMeta?.label ?? '流转中'}</h2>
              {stepLive ? <RunningIndicator size="sm" mode="dot" label="执行中" /> : null}
            </div>
            <p className="muted">{stepLive && progress?.message ? progress.message : stepMeta?.hint}</p>
          </div>
          {!reviewMode && focusStep === 'verify_approval' ? (
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => loadFirstDoc(['verify_report', 'delivery_advice'])}>
              打开验证报告
            </button>
          ) : null}
        </div>
        {renderStepContent()}
      </section>
    </div>
  )
}
