import type { MicroRunModel } from '../lib/buildAgentFlow'
import styles from './AgentExecutionFlow.module.less'

interface Props {
  runs: MicroRunModel[]
  activeRun: MicroRunModel | null
}

function terminalSummary(run: MicroRunModel | null): string {
  if (!run?.milestones.length) return '无里程碑'
  const last = run.milestones[run.milestones.length - 1]
  if (run.semantic?.status === 'running') return '执行中'
  return last.label
}

export function MicroLoopBridge({ runs, activeRun }: Props) {
  if (!activeRun || runs.length <= 1) return null

  const index = runs.findIndex((run) => run.id === activeRun.id)
  if (index <= 0) return null

  const previous = runs[index - 1]
  const loop = activeRun.bridgeLoop

  return (
    <div className={styles.loopBridge}>
      <span className={styles.loopBridgeNode}>
        第 {previous.semantic?.round ?? index} 轮 · {terminalSummary(previous)}
      </span>
      {loop ? (
        <>
          <span className={styles.loopBridgeEdge}>{loop.kind}</span>
          <span className={styles.loopBridgeHint}>{loop.hint}</span>
        </>
      ) : (
        <span className={styles.loopBridgeEdge}>→</span>
      )}
      <span className={`${styles.loopBridgeNode} ${styles.loopBridgeNodeActive}`}>
        第 {activeRun.semantic?.round ?? index + 1} 轮{activeRun.isCurrent ? '（当前）' : ''}
      </span>
    </div>
  )
}
