import type { FlowEdge, FlowNode } from '../lib/buildAgentFlow'

export const MACRO_NODE_WIDTH = 88
export const MACRO_NODE_HEIGHT = 36
export const MACRO_GAP = 24
export const MACRO_PADDING = 16

export const MICRO_NODE_WIDTH = 100
export const MICRO_NODE_HEIGHT = 32
export const MICRO_GAP = 20
export const MICRO_PADDING = 12

export interface LayoutPoint {
  x: number
  y: number
}

export interface LayoutRect extends LayoutPoint {
  width: number
  height: number
}

export interface LayoutResult {
  nodes: Map<string, LayoutRect>
  width: number
  height: number
}

export function layoutHorizontal(nodes: FlowNode[], nodeWidth: number, nodeHeight: number, gap: number, padding: number): LayoutResult {
  const map = new Map<string, LayoutRect>()
  nodes.forEach((node, index) => {
    map.set(node.id, {
      x: padding + index * (nodeWidth + gap),
      y: padding,
      width: nodeWidth,
      height: nodeHeight,
    })
  })
  const width = padding * 2 + nodes.length * nodeWidth + Math.max(0, nodes.length - 1) * gap
  return { nodes: map, width, height: padding * 2 + nodeHeight }
}

export function edgePath(from: LayoutRect, to: LayoutRect, kind: FlowEdge['kind']): string {
  const x1 = from.x + from.width
  const y1 = from.y + from.height / 2
  const x2 = to.x
  const y2 = to.y + to.height / 2

  if (kind === 'retry_self') {
    const cx = from.x + from.width / 2
    const top = from.y - 18
    return `M ${cx} ${from.y} C ${cx} ${top}, ${cx + 40} ${top}, ${cx + 40} ${y1} S ${cx} ${top + 8}, ${cx} ${from.y}`
  }

  if (kind !== 'forward') {
    const midX = (x1 + x2) / 2
    const arch = kind === 'retry_coder' || kind === 'verify_reject' ? 36 : 28
    return `M ${x1} ${y1} C ${midX} ${y1 - arch}, ${midX} ${y2 - arch}, ${x2} ${y2}`
  }

  return `M ${x1} ${y1} L ${x2} ${y2}`
}

export function macroEdgeAnchor(from: LayoutRect, to: LayoutRect, kind: FlowEdge['kind']): { x1: number; y1: number; x2: number; y2: number } {
  if (kind === 'retry_self') {
    const cx = from.x + from.width / 2
    return { x1: cx, y1: from.y, x2: cx + 40, y2: from.y - 10 }
  }
  if (kind === 'forward') {
    return {
      x1: from.x + from.width,
      y1: from.y + from.height / 2,
      x2: to.x,
      y2: to.y + to.height / 2,
    }
  }
  return {
    x1: from.x + from.width / 2,
    y1: from.y,
    x2: to.x + to.width / 2,
    y2: to.y,
  }
}
