import type { IterationDetail } from '../../../shared/lib/types'
import type { PipelineStepKey } from '../lib/pipelineSteps'
import { AgentActivityPanel } from '../../iteration/AgentActivityPanel'
import { RunLogPanel } from '../../iteration/RunLogPanel'

interface Props {
  detail: IterationDetail | null
  stepKey: PipelineStepKey
}

export function StepExecutionPanel({ detail, stepKey }: Props) {
  return (
    <div className="stack">
      <AgentActivityPanel detail={detail} stepKey={stepKey} />
      <RunLogPanel detail={detail} stepKey={stepKey} />
    </div>
  )
}
