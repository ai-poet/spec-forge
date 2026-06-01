import type { IterationDetail } from '../../../shared/lib/types'
import type { PipelineStepKey } from '../lib/pipelineSteps'
import { AgentExecutionFlow } from '../AgentExecutionFlow'
import { RunLogPanel } from '../../iteration/RunLogPanel'
import { RuntimeNotePanel } from '../../iteration/RuntimeNotePanel'

interface Props {
  detail: IterationDetail | null
  stepKey: PipelineStepKey
  reviewMode?: boolean
  reviewStepKey?: PipelineStepKey | null
  onSelectStep?: (key: PipelineStepKey | null) => void
  onRuntimeNoteSubmitted?: () => void
}

export function StepExecutionPanel({
  detail,
  stepKey,
  reviewMode = false,
  reviewStepKey = null,
  onSelectStep,
  onRuntimeNoteSubmitted,
}: Props) {
  return (
    <div className="stack">
      <AgentExecutionFlow
        detail={detail}
        stepKey={stepKey}
        reviewMode={reviewMode}
        reviewStepKey={reviewStepKey}
        onSelectStep={onSelectStep}
      />
      <RuntimeNotePanel detail={detail} reviewMode={reviewMode} onSubmitted={onRuntimeNoteSubmitted} />
      <RunLogPanel detail={detail} stepKey={stepKey} reviewMode={reviewMode} />
    </div>
  )
}
