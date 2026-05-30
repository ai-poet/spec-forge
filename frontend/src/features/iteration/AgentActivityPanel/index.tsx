import type { IterationDetail } from '../../../shared/lib/types'
import type { PipelineStepKey } from '../../pipeline/lib/pipelineSteps'
import { AgentExecutionFlow } from '../../pipeline/AgentExecutionFlow'

interface Props {
  detail: IterationDetail | null
  stepKey?: PipelineStepKey | null
  reviewMode?: boolean
}

/** @deprecated Use AgentExecutionFlow directly */
export function AgentActivityPanel({ detail, stepKey = null, reviewMode = false }: Props) {
  return (
    <AgentExecutionFlow
      detail={detail}
      stepKey={stepKey}
      reviewMode={reviewMode}
      reviewStepKey={reviewMode ? stepKey : null}
    />
  )
}
