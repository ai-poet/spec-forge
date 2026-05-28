import { useState } from 'react'
import type { IterationDetail } from '../types'
import type { PipelineStepKey } from '../pipelineSteps'
import { inferFocusStep, PIPELINE_STEPS } from '../pipelineSteps'
import { ActionPanel } from './ActionPanel'
import { AgentActivityPanel } from './AgentActivityPanel'
import { DocumentPanel } from './DocumentPanel'
import { IterationSummaryPanel } from './IterationSummaryPanel'
import { RunLogPanel } from './RunLogPanel'
import { TimelinePanel } from './TimelinePanel'
import { UIVerificationPanel } from './UIVerificationPanel'
import { WorkbenchPanel } from './WorkbenchPanel'

interface Props {
  detail: IterationDetail | null
  docText: string
  reviewStepKey: PipelineStepKey | null
  busy: boolean
  onLoadDocument: (name: string) => Promise<void>
  onApproveDesign: () => Promise<void>
  onApproveVerify: () => Promise<void>
  onStop: () => Promise<void>
}

const designDocs = ['system_design', 'modification_plan', 'testing_plan']

export function StageFocusPanel({
  detail,
  docText,
  reviewStepKey,
  busy,
  onLoadDocument,
  onApproveDesign,
  onApproveVerify,
  onStop,
}: Props) {
  const [showAllDetails, setShowAllDetails] = useState(false)
  const focusStep = reviewStepKey ?? (detail ? inferFocusStep(detail) : null)
  const stepMeta = PIPELINE_STEPS.find((step) => step.key === focusStep)

  async function loadFirstDoc(names: string[]) {
    if (!detail) return
    const doc = detail.documents.find((item) => names.includes(item.name))
    if (doc) await onLoadDocument(doc.name)
  }

  function renderStepContent() {
    if (!detail || !focusStep) return null

    if (reviewStepKey) {
      return renderReviewContent(focusStep)
    }

    switch (focusStep) {
      case 'planner':
        return (
          <div className="stack">
            <AgentActivityPanel detail={detail} />
            <TimelinePanel detail={detail} filter="runs" />
          </div>
        )
      case 'design_approval':
        return (
          <div className="stack">
            <DocumentPanel detail={detail} docText={docText} onLoadDocument={onLoadDocument} />
          </div>
        )
      case 'coder':
        return (
          <div className="stack">
            <RunLogPanel detail={detail} />
            <IterationSummaryPanel detail={detail} />
          </div>
        )
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
        return (
          <div className="stack">
            <DocumentPanel detail={detail} docText={docText} onLoadDocument={onLoadDocument} />
            <IterationSummaryPanel detail={detail} />
          </div>
        )
      case 'done':
        return (
          <div className="stack">
            <IterationSummaryPanel detail={detail} />
            <DocumentPanel detail={detail} docText={docText} onLoadDocument={onLoadDocument} />
          </div>
        )
      default:
        return <TimelinePanel detail={detail} filter="all" />
    }
  }

  function renderReviewContent(step: PipelineStepKey) {
    if (!detail) return null
    switch (step) {
      case 'planner':
        return (
          <div className="stack">
            <AgentActivityPanel detail={detail} />
            <TimelinePanel detail={detail} filter="runs" />
          </div>
        )
      case 'design_approval':
        return <DocumentPanel detail={detail} docText={docText} onLoadDocument={onLoadDocument} />
      case 'coder':
        return <RunLogPanel detail={detail} />
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
        return <TimelinePanel detail={detail} filter="all" />
    }
  }

  if (!detail) {
    return (
      <section className="panel stage-focus">
        <p className="muted">请选择一条流水线查看当前阶段。</p>
      </section>
    )
  }

  const isBlocked = ['blocked', 'blocked_user', 'stopped', 'failed'].includes(detail.status)

  return (
    <div className="stage-focus stack">
      {reviewStepKey ? (
        <div className="stage-focus-banner">
          <strong>回顾：{stepMeta?.label}</strong>
          <span className="muted">只读查看该阶段产物，不影响流水线状态</span>
        </div>
      ) : null}

      <ActionPanel
        detail={detail}
        busy={busy}
        onApproveDesign={onApproveDesign}
        onApproveVerify={onApproveVerify}
        onStop={onStop}
      />

      {isBlocked && !reviewStepKey ? (
        <section className="panel stack">
          <TimelinePanel detail={detail} filter="failures" />
        </section>
      ) : null}

      <section className="panel stack stage-focus-content">
        <div className="section-row">
          <div>
            <p className="eyebrow">{reviewStepKey ? '阶段回顾' : '当前阶段'}</p>
            <h2 className="section-title">{stepMeta?.label ?? '流转中'}</h2>
            <p className="muted">{stepMeta?.hint}</p>
          </div>
          {!reviewStepKey && focusStep === 'design_approval' ? (
            <button className="btn" onClick={() => loadFirstDoc(designDocs)}>
              打开设计文档
            </button>
          ) : null}
          {!reviewStepKey && focusStep === 'verify_approval' ? (
            <button className="btn" onClick={() => loadFirstDoc(['verify_report', 'delivery_advice'])}>
              打开验证报告
            </button>
          ) : null}
        </div>
        {renderStepContent()}
      </section>

      <section className="panel stack stage-focus-details">
        <div className="section-row">
          <h2 className="section-title">全部详情</h2>
          <button className="btn" onClick={() => setShowAllDetails((value) => !value)}>
            {showAllDetails ? '收起' : '展开'}
          </button>
        </div>
        {showAllDetails ? <WorkbenchPanel detail={detail} docText={docText} onLoadDocument={onLoadDocument} /> : null}
      </section>
    </div>
  )
}
