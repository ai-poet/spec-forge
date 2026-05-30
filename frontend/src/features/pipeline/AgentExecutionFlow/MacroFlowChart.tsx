import type { PipelineStepKey } from '../lib/pipelineSteps'
import type { FlowEdge, MacroFlowModel } from '../lib/buildAgentFlow'
import {
  edgePath,
  layoutHorizontal,
  MACRO_GAP,
  MACRO_NODE_HEIGHT,
  MACRO_NODE_WIDTH,
  MACRO_PADDING,
} from './layout'
import styles from './AgentExecutionFlow.module.less'

interface Props {
  model: MacroFlowModel
  selectedStepKey: PipelineStepKey | null
  onSelectStep: (stepKey: PipelineStepKey) => void
}

const EDGE_CLASS: Record<FlowEdge['kind'], string> = {
  forward: styles.edgeForward,
  retry_coder: styles.edgeRetryCoder,
  retry_self: styles.edgeRetrySelf,
  verify_reject: styles.edgeVerifyReject,
  clarify: styles.edgeClarify,
}

export function MacroFlowChart({ model, selectedStepKey, onSelectStep }: Props) {
  if (!model.nodes.length) return null

  const layout = layoutHorizontal(model.nodes, MACRO_NODE_WIDTH, MACRO_NODE_HEIGHT, MACRO_GAP, MACRO_PADDING)
  const nodeById = new Map(model.nodes.map((node) => [node.id, node]))

  return (
    <div className={styles.macroWrap}>
      <svg
        className={styles.macroSvg}
        viewBox={`0 0 ${layout.width} ${layout.height + 28}`}
        role="img"
        aria-label="流水线总览"
      >
        {model.edges.map((edge) => {
          const from = layout.nodes.get(edge.from)
          const to = layout.nodes.get(edge.to)
          if (!from || !to) return null
          const path = edgePath(from, to, edge.kind)
          return (
            <g key={edge.id}>
              <path d={path} className={`${styles.edge} ${EDGE_CLASS[edge.kind]}`} fill="none" />
              {edge.label ? (
                <text
                  x={(from.x + to.x + from.width) / 2}
                  y={Math.min(from.y, to.y) - 6}
                  className={styles.edgeLabel}
                >
                  {edge.label}
                </text>
              ) : null}
            </g>
          )
        })}
        {model.nodes.map((node) => {
          const rect = layout.nodes.get(node.id)
          if (!rect || !node.stepKey) return null
          const selected = selectedStepKey === node.stepKey
          return (
            <g
              key={node.id}
              className={`${styles.nodeGroup} ${styles[`node${capitalize(node.state)}`]}`}
              onClick={() => onSelectStep(node.stepKey!)}
              role="button"
              tabIndex={0}
              aria-pressed={selected}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  onSelectStep(node.stepKey!)
                }
              }}
            >
              <rect
                x={rect.x}
                y={rect.y}
                width={rect.width}
                height={rect.height}
                rx={8}
                className={`${styles.nodeRect} ${selected ? styles.nodeSelected : ''}`}
              />
              <text x={rect.x + rect.width / 2} y={rect.y + rect.height / 2 + 4} className={styles.nodeLabel}>
                {node.label}
              </text>
            </g>
          )
        })}
      </svg>
      <div className={styles.macroLegend}>
        {model.edges.filter((edge) => edge.kind !== 'forward').map((edge) => {
          const from = nodeById.get(edge.from)
          const to = nodeById.get(edge.to)
          if (!from || !to) return null
          return (
            <span key={edge.id} className={styles.legendItem}>
              {edge.label ?? edge.kind}: {from.label}
              {edge.kind === 'retry_self' ? ' 自环' : ` → ${to.label}`}
            </span>
          )
        })}
      </div>
    </div>
  )
}

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1)
}
