import type { IterationDetail } from '../../../shared/lib/types'
import type { PipelineStepKey } from '../lib/pipelineSteps'
import { inferFocusStep, PIPELINE_STEPS } from '../lib/pipelineSteps'
import { ActionPanel } from '../../iteration/ActionPanel'
import { DocumentPanel } from '../../iteration/DocumentPanel'
import { IterationSummaryPanel } from '../../iteration/IterationSummaryPanel'
import { StepExecutionPanel } from '../StepExecutionPanel'
import { TimelinePanel } from '../../iteration/TimelinePanel'
import { UIVerificationPanel } from '../../iteration/UIVerificationPanel'

interface Props {
  detail: IterationDetail | null
  docText: string
  reviewStepKey: PipelineStepKey | null
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
  busy,
  onLoadDocument,
  onApproveVerify,
  onStop,
  onResume,
}: Props) {
  const focusStep = reviewStepKey ?? (detail ? inferFocusStep(detail) : null)
  const stepMeta = PIPELINE_STEPS.find((step) => step.key === focusStep)

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
        <StepExecutionPanel detail={detail} stepKey={focusStep} />
        {renderStepExtras(focusStep)}
      </div>
    )
  }

  if (!detail) {
    return (
      <section className="stage-section">
        <p className="muted">请选择一条流水线查看当前阶段。</p>
      </section>
    )
  }

  const isBlocked = ['blocked', 'blocked_user', 'stopped', 'failed'].includes(detail.status)

  return (
    <div className="stage-focus">
      {reviewStepKey ? (
        <div className="stage-focus-banner">
          <strong>回顾：{stepMeta?.label}</strong>
          <span className="muted">只读查看该阶段产物与 Agent 执行详情</span>
        </div>
      ) : null}

      <div className="action-bar-sticky">
        <ActionPanel
          detail={detail}
          busy={busy}
          onApproveVerify={onApproveVerify}
          onStop={onStop}
          onResume={onResume}
        />
      </div>

      {isBlocked && !reviewStepKey ? (
        <section className="surface stack stage-section">
          <TimelinePanel detail={detail} filter="failures" />
        </section>
      ) : null}

      <section className="stage-section stack stage-focus-content">
        <div className="section-row">
          <div>
            <p className="eyebrow">{reviewStepKey ? '阶段回顾' : '当前阶段'}</p>
            <h2 className="section-title">{stepMeta?.label ?? '流转中'}</h2>
            <p className="muted">{stepMeta?.hint}</p>
          </div>
          {!reviewStepKey && focusStep === 'verify_approval' ? (
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
