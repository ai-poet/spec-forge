import type { IterationDetail } from '../../../shared/lib/types'

export type PipelineStepKey =
  | 'prd_planning'
  | 'test_planning'
  | 'coder'
  | 'integrity_check'
  | 'code_tester'
  | 'ui_tester'
  | 'planner_verify'
  | 'verify_approval'
  | 'done'

export const PIPELINE_STEPS: { key: PipelineStepKey; label: string; hint: string }[] = [
  { key: 'prd_planning', label: 'PRD 规划', hint: '需求澄清与 prd.md、上下文清单' },
  { key: 'test_planning', label: '测试规划', hint: 'testing_plan.md（自动化测试策略 + 人工测试场景）' },
  { key: 'coder', label: '实现', hint: '写入代码变更' },
  { key: 'code_tester', label: '代码验证', hint: '按 testing_plan 编写自动化测试；独立代码审查' },
  { key: 'integrity_check', label: '测试完整性', hint: '保护 Code Tester 建立的测试基线' },
  { key: 'ui_tester', label: 'UI 验证', hint: 'playwright-cli / cua-driver Agent' },
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

const PRD_PLANNING_NODES = new Set([
  'planner_discovery',
  'requirements_input',
  'prd_planner',
])

const TEST_PLANNING_NODES = new Set(['test_planner'])

export function nodesForStep(step: PipelineStepKey): string[] {
  switch (step) {
    case 'prd_planning':
      return [...PRD_PLANNING_NODES]
    case 'test_planning':
      return [...TEST_PLANNING_NODES]
    case 'coder':
      return ['coder', 'coder_retry', 'planner_clarification']
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

function focusPlanningStep(detail: IterationDetail): 'prd_planning' | 'test_planning' {
  const node = detail.current_node ?? detail.stopped_at_node
  if (node && TEST_PLANNING_NODES.has(node)) return 'test_planning'
  return 'prd_planning'
}

export function pipelineStepState(key: string, detail: IterationDetail | null): 'idle' | 'waiting' | 'active' | 'complete' {
  if (!detail) return 'idle'
  const next = new Set(detail.graph_next ?? [])
  const currentNode = detail.current_node
  const status = detail.status
  if (next.has(key)) return 'waiting'
  if (currentNode === key) return 'active'
  if (key === 'verify_approval' && status === 'awaiting_verify_approval') return 'waiting'
  if (key === 'prd_planning' && status === 'awaiting_requirements_input') return 'waiting'
  if (key === 'done' && status === 'delivered') return 'complete'
  if (key === 'prd_planning' && currentNode && PRD_PLANNING_NODES.has(currentNode)) return 'active'
  if (key === 'test_planning' && currentNode === 'test_planner') return 'active'
  if (key === 'prd_planning' && ['planning', 'queued', 'created'].includes(status) && currentNode !== 'test_planner') {
    return 'active'
  }
  if (key === 'coder' && ['coding', 'retrying'].includes(status)) return 'active'
  if (key === 'code_tester' && status === 'testing' && currentNode === 'code_tester') return 'active'
  if (key === 'integrity_check' && status === 'testing' && currentNode === 'integrity_check') return 'active'
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
    if (detail.stopped_at_node === 'planner_clarification') return 'coder'
    if (TEST_PLANNING_NODES.has(detail.stopped_at_node)) return 'test_planning'
    if (PRD_PLANNING_NODES.has(detail.stopped_at_node)) return 'prd_planning'
  }
  if (status === 'awaiting_requirements_input') return 'prd_planning'
  if (['queued', 'planning', 'created'].includes(status)) return focusPlanningStep(detail)
  if (['coding', 'retrying'].includes(status)) return 'coder'
  if (status === 'testing') {
    if (node === 'code_tester') return 'code_tester'
    if (node === 'integrity_check') return 'integrity_check'
    if (node === 'planner_verify') return 'planner_verify'
    if (node === 'ui_tester' || node === 'ui_driver') return 'ui_tester'
    return 'code_tester'
  }
  if (status === 'awaiting_verify_approval') return 'verify_approval'
  if (status === 'delivered') return 'done'
  if (node === 'planner_verify') return 'planner_verify'
  if (node === 'ui_tester' || node === 'ui_driver') return 'ui_tester'
  if (node === 'integrity_check') return 'integrity_check'
  if (node === 'code_tester') return 'code_tester'
  if (node === 'coder' || node === 'coder_retry' || node === 'planner_clarification') return 'coder'
  if (node && TEST_PLANNING_NODES.has(node)) return 'test_planning'
  if (node && PRD_PLANNING_NODES.has(node)) return 'prd_planning'
  return 'prd_planning'
}
