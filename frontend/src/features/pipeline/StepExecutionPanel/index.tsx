import type { IterationDetail } from '../../../shared/lib/types'
import type { PipelineStepKey } from '../lib/pipelineSteps'
import { AgentExecutionFlow } from '../AgentExecutionFlow'
import { RunLogPanel } from '../../iteration/RunLogPanel'

interface Props {
  detail: IterationDetail | null
  stepKey: PipelineStepKey
  reviewMode?: boolean
  reviewStepKey?: PipelineStepKey | null
  onSelectStep?: (key: PipelineStepKey | null) => void
}

export function StepExecutionPanel({ detail, stepKey, reviewMode = false, reviewStepKey = null, onSelectStep }: Props) {
  return (
    <div className="stack">
      <AgentExecutionFlow
        detail={detail}
        stepKey={stepKey}
        reviewMode={reviewMode}
        reviewStepKey={reviewStepKey}
        onSelectStep={onSelectStep}
      />
      <RunLogPanel detail={detail} stepKey={stepKey} reviewMode={reviewMode} />
    </div>
  )
}
