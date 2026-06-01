import { useEffect, useMemo, useState } from 'react'
import type { IterationDetail } from '../../../shared/lib/types'
import { isStepLive, latestNodeProgress } from '../lib/pipelineLive'
import { inferFocusStep, PIPELINE_STEPS, type PipelineStepKey } from '../lib/pipelineSteps'
import { buildMacroFlow, buildMicroFlow, findMilestone } from '../lib/buildAgentFlow'
import { RunningIndicator } from '../../../shared/ui/RunningIndicator'
import { presentNodeName } from '../../../shared/lib/presentation'
import { MacroFlowChart } from './MacroFlowChart'
import { MicroFlowChart } from './MicroFlowChart'
import { FlowDetailCard } from './FlowDetailCard'
import { RunRoundSelector } from './RunRoundSelector'
import { MicroLoopBridge } from './MicroLoopBridge'
import { RunOverviewLane } from './RunOverviewLane'
import styles from './AgentExecutionFlow.module.less'

interface Props {
  detail: IterationDetail | null
  stepKey?: PipelineStepKey | null
  reviewMode?: boolean
  reviewStepKey?: PipelineStepKey | null
  onSelectStep?: (key: PipelineStepKey | null) => void
}

export function AgentExecutionFlow({
  detail,
  stepKey = null,
  reviewMode = false,
  reviewStepKey = null,
  onSelectStep,
}: Props) {
  const focusStep = reviewMode
    ? (reviewStepKey ?? stepKey)
    : (stepKey ?? (detail ? inferFocusStep(detail) : null))

  const selectedStepKey = focusStep ?? null
  const stepLive = !reviewMode && isStepLive(detail, selectedStepKey)
  const progress = latestNodeProgress(detail, selectedStepKey)

  const macro = useMemo(() => buildMacroFlow(detail), [detail])
  const micro = useMemo(
    () => (selectedStepKey ? buildMicroFlow(detail, selectedStepKey, { reviewMode, stepLive }) : { runs: [], defaultRunId: null, defaultMilestoneId: null }),
    [detail, selectedStepKey, reviewMode, stepLive],
  )

  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [selectedMilestoneId, setSelectedMilestoneId] = useState<string | null>(null)

  const runsKey = micro.runs.map((run) => run.id).join('|')
  useEffect(() => {
    setSelectedRunId(micro.defaultRunId)
    setSelectedMilestoneId(micro.defaultMilestoneId)
  }, [runsKey, selectedStepKey, micro.defaultRunId, micro.defaultMilestoneId])

  const activeRun = micro.runs.find((run) => run.id === selectedRunId) ?? micro.runs[micro.runs.length - 1] ?? null
  const selectedMilestone = findMilestone(micro, activeRun?.id ?? null, selectedMilestoneId)

  const stepMeta = PIPELINE_STEPS.find((step) => step.key === selectedStepKey)
  const execCount = detail?.runs.filter((run) => {
    if (selectedStepKey === 'coder') {
      return ['coder', 'coder_retry', 'planner_clarification'].includes(run.node)
    }
    if (selectedStepKey === 'prd_planning') {
      return ['prd_planner', 'planner_discovery'].includes(run.node)
    }
    if (selectedStepKey === 'test_planning') return run.node === 'test_planner'
    if (selectedStepKey === 'code_tester') return run.node === 'code_tester'
    if (selectedStepKey === 'ui_tester') return run.node === 'ui_tester' || run.node === 'ui_driver'
    return false
  }).length
  const countLabel = micro.runs.length > 1
    ? `${execCount || micro.runs.length} 次执行 · ${activeRun?.milestones.length ?? 0} 个里程碑`
    : `${activeRun?.milestones.length ?? 0} 个里程碑`

  function handleMacroSelect(key: PipelineStepKey) {
    if (!onSelectStep) return
    if (reviewMode && reviewStepKey === key) {
      onSelectStep(null)
      return
    }
    onSelectStep(key)
  }

  function selectRun(runId: string) {
    setSelectedRunId(runId)
    const run = micro.runs.find((item) => item.id === runId)
    const defaultMilestone = run?.milestones[run.milestones.length - 1]
    setSelectedMilestoneId(defaultMilestone?.id ?? null)
  }

  return (
    <section className="panel stack">
      <div className="section-row">
        <h2 className="section-title">{stepKey ? '本阶段 Agent 执行' : 'Agent 运行状态'}</h2>
        <div className={styles.headerMeta}>
          {stepLive ? <RunningIndicator size="sm" mode="dot" label="执行中" /> : null}
          {selectedStepKey ? <span className="pill">{countLabel}</span> : null}
        </div>
      </div>

      {stepLive ? (
        <div className={styles.liveBanner}>
          <RunningIndicator mode="both" label={progress?.title ?? `${presentNodeName(detail?.current_node ?? 'agent')} 正在运行…`} />
          {progress?.message ? <p>{progress.message}</p> : null}
        </div>
      ) : null}

      <MacroFlowChart
        model={macro}
        selectedStepKey={selectedStepKey}
        onSelectStep={handleMacroSelect}
      />

      {selectedStepKey ? (
        <div className={styles.microSection}>
          <div className="section-row">
            <div>
              <h3 className="section-title">{stepMeta?.label ?? '阶段'} · 里程碑</h3>
              {micro.stepSummary ? <p className={`muted ${styles.stepSummary}`}>回环：{micro.stepSummary}</p> : null}
            </div>
          </div>
          <RunOverviewLane runs={micro.runs} activeRunId={activeRun?.id ?? null} onSelectRun={selectRun} />
          <RunRoundSelector runs={micro.runs} activeRunId={activeRun?.id ?? null} onSelectRun={selectRun} />
          <MicroLoopBridge runs={micro.runs} activeRun={activeRun} />
          <MicroFlowChart
            run={activeRun}
            selectedMilestoneId={selectedMilestoneId}
            onSelectMilestone={setSelectedMilestoneId}
          />
          <FlowDetailCard milestone={selectedMilestone} />
        </div>
      ) : (
        <div className="empty">选择流水线阶段以查看里程碑流程。</div>
      )}
    </section>
  )
}
