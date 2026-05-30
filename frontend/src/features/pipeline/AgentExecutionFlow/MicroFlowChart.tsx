import type { MicroRunModel } from '../lib/buildAgentFlow'
import {
  layoutHorizontal,
  MICRO_GAP,
  MICRO_NODE_HEIGHT,
  MICRO_NODE_WIDTH,
  MICRO_PADDING,
} from './layout'
import styles from './AgentExecutionFlow.module.less'

interface Props {
  run: MicroRunModel | null
  selectedMilestoneId: string | null
  onSelectMilestone: (milestoneId: string) => void
}

export function MicroFlowChart({ run, selectedMilestoneId, onSelectMilestone }: Props) {
  if (!run?.milestones.length) {
    return <div className="empty">本阶段暂无里程碑事件。</div>
  }

  const layout = layoutHorizontal(run.milestones, MICRO_NODE_WIDTH, MICRO_NODE_HEIGHT, MICRO_GAP, MICRO_PADDING)

  return (
    <div className={styles.microWrap}>
      {run.separatorBefore ? <div className={styles.runSeparator}>{run.separatorBefore}</div> : null}
      <svg
        className={styles.microSvg}
        viewBox={`0 0 ${layout.width} ${layout.height}`}
        role="img"
        aria-label={`${run.label} 里程碑流程`}
      >
        {run.edges.map((edge) => {
          const from = layout.nodes.get(edge.from)
          const to = layout.nodes.get(edge.to)
          if (!from || !to) return null
          return (
            <line
              key={edge.id}
              x1={from.x + from.width}
              y1={from.y + from.height / 2}
              x2={to.x}
              y2={to.y + to.height / 2}
              className={`${styles.edge} ${styles.edgeForward}`}
            />
          )
        })}
        {run.milestones.map((node) => {
          const rect = layout.nodes.get(node.id)
          if (!rect) return null
          const selected = selectedMilestoneId === node.id
          return (
            <g
              key={node.id}
              className={`${styles.nodeGroup} ${styles[`node${capitalize(node.state)}`]} ${node.isLive ? styles.nodeLive : ''}`}
              onClick={() => onSelectMilestone(node.id)}
              role="button"
              tabIndex={0}
              aria-pressed={selected}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  onSelectMilestone(node.id)
                }
              }}
            >
              <rect
                x={rect.x}
                y={rect.y}
                width={rect.width}
                height={rect.height}
                rx={6}
                className={`${styles.nodeRect} ${selected ? styles.nodeSelected : ''}`}
              />
              <text x={rect.x + rect.width / 2} y={rect.y + rect.height / 2 + 4} className={styles.nodeLabel}>
                {truncate(node.label, 12)}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1)
}

function truncate(value: string, max: number): string {
  if (value.length <= max) return value
  return `${value.slice(0, max - 1)}…`
}
