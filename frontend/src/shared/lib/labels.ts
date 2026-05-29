import type { EpicStatus, IterationStatus, LiveConnectionStatus, NodeName, TimelineFilter } from './types'

export const iterationStatusLabel: Record<IterationStatus, string> = {
  created: '已创建',
  queued: '已排队',
  planning: '正在规划',
  awaiting_design_approval: '自动推进中',
  coding: '正在实现',
  retrying: '自动重试中',
  testing: '正在验证',
  awaiting_verify_approval: '等待确认交付',
  delivered: '已交付',
  blocked: '已阻断',
  blocked_user: '等待人工处理',
  failed: '失败',
  stopped: '已停止',
}

export const epicStatusLabel: Record<EpicStatus, string> = {
  draft: '草稿',
  active: '进行中',
  blocked: '已阻断',
  delivered: '已交付',
}

export const nodeLabel: Record<NodeName, string> = {
  planner: '规划',
  coder: '实现',
  coder_retry: '实现重试',
  integrity_check: '测试完整性检查',
  tester: '验证',
  planner_clarification: '规划澄清',
  planner_verify: '规格复核',
}

export const connectionLabel: Record<LiveConnectionStatus, string> = {
  idle: '未连接',
  connecting: '连接中',
  connected: '已连接',
  reconnecting: '重连中',
  disconnected: '已断开',
}

export const timelineFilterLabel: Record<TimelineFilter, string> = {
  all: '全部',
  decisions: '决策',
  failures: '失败',
  tests: '测试',
  runs: '运行',
}

export function graphNodeLabel(value: string) {
  if (value in nodeLabel) return nodeLabel[value as NodeName]
  if (value === 'verify_approval') return '交付确认'
  if (value === 'done') return '交付完成'
  if (value === 'END') return '结束'
  return value
}

export function retryLabel(value: string) {
  if (value === 'coder_tester') return '实现/验证重试'
  if (value === 'coder_planner_clarify') return '实现澄清'
  if (value === 'planner_verify_reject') return '规格复核驳回'
  return value
}

export function eventLabel(value: string) {
  const labels: Record<string, string> = {
    'iteration.queued': '流水线已排队',
    'iteration.started': '规划已开始',
    'planner.completed': '规划完成',
    'design.approved': '设计已审批',
    'coder.completed': '实现完成',
    'test_integrity.passed': '测试完整性通过',
    'tester.completed': '验证完成',
    'tester.delivery_advice': '交付建议已生成',
    'tester.failed_retry': '验证失败，准备重试',
    'tester.nonzero_artifact.accepted': '验证产物已保留',
    'tester.review_fallback.started': '代码审查兜底已启动',
    'tester.review_fallback.completed': '代码审查兜底完成',
    'tester.review_fallback.failed': '代码审查兜底失败',
    'ui_driver.started': 'UI Driver 已开始',
    'ui_driver.completed': 'UI Driver 已完成',
    'ui_driver.fallback': 'Playwright 回退执行',
    'ui_driver.warning': '部分 UI 未执行',
    'ui_driver.failed': 'UI Driver 需复核',
    'planner_verify.accepted': '规格复核通过',
    'planner_verify.rejected': '规格复核驳回',
    'verify.approved': '验证结果已确认',
    'iteration.delivered': '流水线已交付',
    'iteration.stopped': '流水线已停止',
    'iteration.resumed': '流水线已恢复',
    'resume.queued': '继续执行已排队',
    'artifact.invalid': '产物格式无效',
    'test_integrity.failed': '测试完整性失败',
    'planner.failed': '规划失败',
    'coder.failed': '实现失败',
    'tester.max_retries': '验证重试已达上限',
    'clarification.answered': '澄清已处理',
    'clarification.max_retries': '澄清次数已达上限',
    'planner_verify.max_retries': '规格复核驳回已达上限',
  }
  return labels[value] ?? value
}

export function documentLabel(value: string) {
  const labels: Record<string, string> = {
    system_design: '系统设计',
    modification_plan: '修改计划',
    testing_plan: '测试计划',
    verify_report: '验证报告',
    delivery_advice: '交付建议',
    ui_report: 'UI 验证报告',
    ui_results: 'UI 验证结果',
  }
  return labels[value] ?? value
}

export function uiStatusLabel(value: string) {
  const labels: Record<string, string> = {
    passed: '通过',
    failed: '失败',
    skipped: '跳过',
    warning: '未执行',
  }
  return labels[value] ?? value
}

export function uiDriverLabel(value: string | null | undefined) {
  const labels: Record<string, string> = {
    cua: 'CuaDriver',
    playwright: 'Playwright',
  }
  return value ? labels[value] ?? value : ''
}
