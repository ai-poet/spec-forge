import type { EpicStatus, IterationStatus, LiveConnectionStatus, NodeName, TimelineFilter } from './types'

export const iterationStatusLabel: Record<IterationStatus, string> = {
  created: '已创建',
  queued: '已排队',
  planning: '正在规划',
  awaiting_requirements_input: '等待需求澄清',
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
  prd_planner: 'PRD 规划',
  test_planner: '测试规划',
  planner_discovery: '需求澄清',
  coder: '实现',
  coder_retry: '实现重试',
  integrity_check: '测试完整性检查',
  code_tester: '代码验证',
  ui_tester: 'UI 验证',
  log_summarizer: '日志总结',
  artifact_comparator: '产物对比分析',
  ui_driver: 'UI Driver',
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
  if (value === 'requirements_input') return '需求回答'
  if (value === 'verify_approval') return '交付确认'
  if (value === 'done') return '交付完成'
  if (value === 'END') return '结束'
  return value
}

export function retryLabel(value: string) {
  if (value === 'coder_tester') return '实现/验证重试'
  if (value === 'code_tester_self') return 'Code Tester 自修'
  if (value === 'test_planner_self') return '测试规划修订'
  if (value.endsWith('_artifact_self')) return 'Agent 产物自修'
  if (value === 'coder_planner_clarify') return '实现澄清'
  if (value === 'discovery_round') return '需求澄清轮次'
  if (value === 'planner_verify_reject') return '规格复核驳回'
  return value
}

export function eventLabel(value: string) {
  const labels: Record<string, string> = {
    'iteration.queued': '流水线已排队',
    'iteration.started': '规划已开始',
    'discovery.question': '需求澄清提问',
    'discovery.answered': '需求澄清已回答',
    'discovery.ready': '需求已足够清晰',
    'prd_planner.completed': 'PRD 规划完成',
    'test_planner.completed': '测试规划完成',
    'test_planner.retry': '受保护测试需修订',
    'coder.completed': '实现完成',
    'test_integrity.passed': '测试完整性通过',
    'ui_tester.completed': '验证完成',
    'code_tester.delivery_advice': '交付建议已生成',
    'code_tester.retry_to_coder': '验证失败，回到实现节点',
    'code_tester.retry_to_self': '验证产物不合格，Code Tester 自修',
    'code_tester.nonzero_artifact.accepted': '验证产物已保留',
    'code_tester.review_fallback.started': '代码审查兜底已启动',
    'code_tester.review_fallback.completed': '代码审查兜底完成',
    'code_tester.review_fallback.failed': '代码审查兜底失败',
    'ui_tester.started': 'UI 验证已开始',
    'ui_tester.cua_busy': 'CuaDriver 会话占用',
    'ui_tester.warning': '部分 UI 未执行',
    'ui_tester.failed': 'UI 验证需复核',
    'ui_driver.started': 'UI Driver 已开始',
    'ui_driver.completed': 'UI Driver 已完成',
    'ui_driver.fallback': 'Playwright 回退执行',
    'ui_driver.warning': '部分 UI 未执行',
    'ui_driver.failed': 'UI Driver 需复核',
    'planner_verify.accepted': '规格复核通过',
    'planner_verify.rejected': '规格复核驳回',
    'log_summary.queued': '日志总结已排队',
    'log_summary.started': '日志总结已开始',
    'log_summary.completed': '日志总结已生成',
    'log_summary.failed': '日志总结失败',
    'artifact_comparison.queued': '产物对比分析已排队',
    'artifact_comparison.started': '产物对比分析已开始',
    'artifact_comparison.completed': '产物对比分析已生成',
    'artifact_comparison.failed': '产物对比分析失败',
    'verify.approved': '验证结果已确认',
    'iteration.delivered': '流水线已交付',
    'iteration.stopped': '流水线已停止',
    'iteration.resumed': '流水线已恢复',
    'resume.queued': '继续执行已排队',
    'artifact.invalid': '产物格式无效',
    'artifact.retry_to_self': '产物错误，回到 Agent 自修',
    'artifact.self_max_retries': '产物自修已达上限',
    'test_integrity.failed': '测试完整性失败',
    'prd_planner.failed': 'PRD 规划失败',
    'coder.failed': '实现失败',
    'code_tester.max_retries': '验证重试已达上限',
    'clarification.answered': '澄清已处理',
    'clarification.max_retries': '澄清次数已达上限',
    'planner_verify.max_retries': '规格复核驳回已达上限',
  }
  return labels[value] ?? value
}

export function documentLabel(value: string) {
  if (value.startsWith('artifact_comparison:')) return '产物对比分析'
  const labels: Record<string, string> = {
    prd: 'PRD',
    testing_plan: '测试计划',
    verify_report: '验证报告',
    delivery_advice: '交付建议',
    requirements_brief: '需求摘要',
    ui_report: 'UI 验证报告',
    ui_results: 'UI 验证结果',
    log_summary: '日志总结',
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
