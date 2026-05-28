import type { IterationDetail } from '../../../shared/lib/types'

export type PipelineStepKey =
  | 'planner'
  | 'coder'
  | 'integrity_check'
  | 'tester'
  | 'planner_verify'
  | 'verify_approval'
  | 'done'

export const PIPELINE_STEPS: { key: PipelineStepKey; label: string; hint: string }[] = [
  { key: 'planner', label: '规划', hint: '根据大需求拆分任务并生成计划' },
  { key: 'coder', label: '实现', hint: '写入代码变更' },
  { key: 'integrity_check', label: '测试完整性', hint: '保护测试基线' },
  { key: 'tester', label: '独立验证', hint: '运行验证与交付评审' },
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

export function pipelineStepState(key: string, detail: IterationDetail | null): 'idle' | 'waiting' | 'active' | 'complete' {
  if (!detail) return 'idle'
  const next = new Set(detail.graph_next ?? [])
  const currentNode = detail.current_node
  const status = detail.status
  if (next.has(key)) return 'waiting'
  if (currentNode === key) return 'active'
  if (key === 'verify_approval' && status === 'awaiting_verify_approval') return 'waiting'
  if (key === 'done' && status === 'delivered') return 'complete'
  if (key === 'planner' && ['planning', 'queued'].includes(status)) return 'active'
  if (key === 'coder' && ['coding', 'retrying', 'awaiting_design_approval'].includes(status)) return 'active'
  if (key === 'integrity_check' && status === 'testing' && currentNode === 'integrity_check') return 'active'
  if (key === 'tester' && status === 'testing' && (currentNode === 'tester' || !currentNode)) return 'active'
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
  const node = detail.current_node
  if (['queued', 'planning', 'created'].includes(status)) return 'planner'
  if (['coding', 'retrying', 'awaiting_design_approval'].includes(status)) return 'coder'
  if (status === 'testing') {
    if (node === 'integrity_check') return 'integrity_check'
    if (node === 'planner_verify') return 'planner_verify'
    return 'tester'
  }
  if (status === 'awaiting_verify_approval') return 'verify_approval'
  if (status === 'delivered') return 'done'
  if (node === 'planner_verify') return 'planner_verify'
  if (node === 'tester') return 'tester'
  if (node === 'integrity_check') return 'integrity_check'
  if (node === 'coder' || node === 'coder_retry') return 'coder'
  if (node === 'planner') return 'planner'
  return 'planner'
}
