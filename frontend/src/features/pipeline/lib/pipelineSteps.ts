import type { IterationDetail } from '../../../shared/lib/types'

export type PipelineStepKey =
  | 'planning'
  | 'coder'
  | 'integrity_check'
  | 'code_tester'
  | 'ui_tester'
  | 'planner_verify'
  | 'verify_approval'
  | 'done'

export const PIPELINE_STEPS: { key: PipelineStepKey; label: string; hint: string }[] = [
  { key: 'planning', label: '规划', hint: '需求澄清、PRD 与受保护测试' },
  { key: 'coder', label: '实现', hint: '写入代码变更' },
  { key: 'integrity_check', label: '测试完整性', hint: '保护测试基线' },
  { key: 'code_tester', label: '代码验证', hint: '独立代码审查与测试命令' },
  { key: 'ui_tester', label: 'UI 验证', hint: '执行 UI trajectory' },
  { key: 'planner_verify', label: '规格复核', hint: '机械检查报告' },
  { key: 'verify_approval', label: '交付确认', hint: '人工确认交付' },
  { key: 'done', label: '交付完成', hint: '归档本轮结果' },
]

export const stepStateLabel: Record<string, string> = {
  idle: '未开始',
  waiting: '等待中',
  active: '执行中',
  complete: '完成',
}

const PLANNING_NODES = new Set([
  'planner_discovery',
  'requirements_input',
  'prd_planner',
  'test_planner',
  'planner_clarification',
])

export function nodesForStep(step: PipelineStepKey): string[] {
  switch (step) {
    case 'planning':
      return [...PLANNING_NODES]
    case 'coder':
      return ['coder', 'coder_retry']
    case 'integrity_check':
      return ['integrity_check']
    case 'code_tester':
      return ['code_tester']
    case 'ui_tester':
      return ['ui_tester', 'ui_driver']
    case 'planner_verify':
      return ['planner_verify']
    case 'verify_approval':
      return ['verify_approval']
    case 'done':
      return ['done']
    default:
      return []
  }
}

export function pipelineStepState(key: string, detail: IterationDetail | null): 'idle' | 'waiting' | 'active' | 'complete' {
  if (!detail) return 'idle'
  const next = new Set(detail.graph_next ?? [])
  const currentNode = detail.current_node
  const status = detail.status
  if (next.has(key)) return 'waiting'
  if (currentNode === key) return 'active'
  if (key === 'verify_approval' && status === 'awaiting_verify_approval') return 'waiting'
  if (key === 'planning' && status === 'awaiting_requirements_input') return 'waiting'
  if (key === 'done' && status === 'delivered') return 'complete'
  if (key === 'planning' && ['planning', 'queued'].includes(status)) return 'active'
  if (key === 'coder' && ['coding', 'retrying'].includes(status)) return 'active'
  if (key === 'integrity_check' && status === 'testing' && currentNode === 'integrity_check') return 'active'
  if (key === 'code_tester' && status === 'testing' && currentNode === 'code_tester') return 'active'
  if (key === 'ui_tester' && status === 'testing' && currentNode === 'ui_tester') return 'active'
  if (key === 'planner_verify' && currentNode === 'planner_verify') return 'active'
  const stepIndex = PIPELINE_STEPS.findIndex((step) => step.key === key)
  const activeIndex = inferActiveStepIndex(detail)
  if (stepIndex >= 0 && activeIndex >= 0 && stepIndex < activeIndex) return 'complete'
  return 'idle'
}

function inferActiveStepIndex(detail: IterationDetail): number {
  const focus = inferFocusStep(detail)
  return PIPELINE_STEPS.findIndex((step) => step.key === focus)
}

export function inferFocusStep(detail: IterationDetail): PipelineStepKey {
  const status = detail.status
  const node = detail.current_node ?? detail.stopped_at_node
  if (status === 'stopped' && detail.stopped_at_node) {
    if (detail.stopped_at_node === 'integrity_check') return 'integrity_check'
    if (detail.stopped_at_node === 'planner_verify') return 'planner_verify'
    if (detail.stopped_at_node === 'verify_approval') return 'verify_approval'
    if (detail.stopped_at_node === 'ui_tester' || detail.stopped_at_node === 'ui_driver') return 'ui_tester'
    if (detail.stopped_at_node === 'code_tester') return 'code_tester'
    if (detail.stopped_at_node === 'coder' || detail.stopped_at_node === 'coder_retry') return 'coder'
    if (PLANNING_NODES.has(detail.stopped_at_node)) return 'planning'
  }
  if (status === 'awaiting_requirements_input') return 'planning'
  if (['queued', 'planning', 'created'].includes(status)) return 'planning'
  if (['coding', 'retrying'].includes(status)) return 'coder'
  if (status === 'testing') {
    if (node === 'integrity_check') return 'integrity_check'
    if (node === 'planner_verify') return 'planner_verify'
    if (node === 'ui_tester' || node === 'ui_driver') return 'ui_tester'
    if (node === 'code_tester') return 'code_tester'
    return 'code_tester'
  }
  if (status === 'awaiting_verify_approval') return 'verify_approval'
  if (status === 'delivered') return 'done'
  if (node === 'planner_verify') return 'planner_verify'
  if (node === 'ui_tester' || node === 'ui_driver') return 'ui_tester'
  if (node === 'code_tester') return 'code_tester'
  if (node === 'integrity_check') return 'integrity_check'
  if (node === 'coder' || node === 'coder_retry') return 'coder'
  if (node && PLANNING_NODES.has(node)) return 'planning'
  return 'planning'
}
