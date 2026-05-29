import { documentLabel, eventLabel, nodeLabel } from './labels'
import type { CliPhase, CliProvider, EventRecord, EventSeverity, IterationDetail, NodeRunRecord, ReadableError, SemanticEvent } from './types'

function stringValue(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined
}

function severityValue(value: unknown): EventSeverity | undefined {
  if (value === 'success' || value === 'warning' || value === 'error') return value
  if (value === 'info') return value
  return undefined
}

export function presentNodeName(value: string) {
  return value in nodeLabel ? nodeLabel[value as keyof typeof nodeLabel] : value === 'ui_driver' ? 'UI Driver' : value === 'done' ? '交付完成' : value === 'system' ? '系统' : value
}

export function presentEvent(event: EventRecord): SemanticEvent {
  const payload = event.payload
  const semanticTitle = stringValue(payload.title)
  const semanticMessage = stringValue(payload.message)
  const node = stringValue(payload.node) ?? inferNode(event.type)
  const fallback = fallbackPresentation(event)
  return {
    id: event.id,
    type: event.type,
    node,
    title: semanticTitle ?? fallback.title,
    message: semanticMessage ?? fallback.message,
    severity: severityValue(payload.severity) ?? fallback.severity,
    created_at: event.created_at,
    provider: providerValue(payload.provider),
    phase: phaseValue(payload.phase),
    status: stringValue(payload.status),
    command: stringValue(payload.command),
    paths: arrayValue(payload.paths),
    tool: stringValue(payload.tool),
    preview: stringValue(payload.preview),
    run_id: stringValue(payload.run_id),
    document: stringValue(payload.document),
    action_hint: stringValue(payload.action_hint) ?? fallback.action_hint,
    raw: event,
  }
}

export function isAgentActivity(event: EventRecord) {
  return event.type === 'cli.display' || event.type.startsWith('node.') || event.type.startsWith('artifact.') || event.type.startsWith('error.')
}

export function isCliDisplayEvent(event: EventRecord) {
  return event.type === 'cli.display'
}

export function cliPhaseLabel(value: string | undefined) {
  const labels: Record<string, string> = {
    session: '会话',
    thinking: '推理',
    text: '输出',
    tool: '工具',
    command: '命令',
    file_change: '文件',
    mcp: 'MCP',
    todo: '清单',
    retry: '重试',
    result: '结果',
    error: '错误',
  }
  return value ? labels[value] ?? value : '事件'
}

export function cliProviderLabel(value: string | undefined) {
  if (value === 'claude_code') return 'Claude Code'
  if (value === 'codex') return 'Codex'
  return value ?? 'CLI'
}

export function classifyIterationProblem(detail: IterationDetail | null): ReadableError | null {
  if (!detail) return null
  const semanticError = [...detail.events].reverse().map(presentEvent).find((event) => event.severity === 'error')
  if (detail.status === 'blocked' || detail.status === 'blocked_user' || detail.last_error) {
    return {
      title: semanticError?.title ?? (detail.status === 'blocked_user' ? '需要人工澄清' : '流水线已阻断'),
      message: semanticError?.message ?? detail.last_error ?? '系统无法继续自动推进。',
      action_hint: semanticError?.action_hint ?? '查看事件流和运行日志，处理问题后重新启动或重试迭代。',
      severity: 'error',
    }
  }
  const warning = [...detail.events].reverse().map(presentEvent).find((event) => event.severity === 'warning')
  if (warning) {
    return {
      title: warning.title,
      message: warning.message,
      action_hint: warning.action_hint ?? '这不是阻断项，但建议在交付前确认影响。',
      severity: 'warning',
    }
  }
  return null
}

export function summarizeRun(run: NodeRunRecord) {
  const outputSize = run.stdout.length + run.stderr.length
  const status = run.status === 'success' ? '成功' : '失败'
  const message = outputSize
    ? `已捕获 ${outputSize} 个字符的原始输出。`
    : '没有原始输出。'
  return {
    title: `${presentNodeName(run.node)}运行${status}`,
    message,
    severity: run.status === 'success' ? 'success' as EventSeverity : 'error' as EventSeverity,
  }
}

export function documentSummary(detail: IterationDetail | null) {
  if (!detail) return []
  const important = ['system_design', 'modification_plan', 'testing_plan', 'verify_report', 'delivery_advice', 'ui_report']
  return important.map((name) => {
    const doc = detail.documents.find((item) => item.name === name)
    return {
      name,
      label: documentLabel(name),
      present: Boolean(doc),
      checksum: doc?.checksum,
    }
  })
}

function inferNode(type: string) {
  if (type.includes('planner')) return 'planner'
  if (type.includes('coder')) return 'coder'
  if (type.includes('tester')) return 'tester'
  if (type.includes('integrity')) return 'integrity_check'
  if (type.includes('ui_driver')) return 'ui_driver'
  if (type.includes('verify')) return 'planner_verify'
  return 'system'
}

function providerValue(value: unknown): CliProvider | undefined {
  if (value === 'claude_code' || value === 'codex') return value
  return undefined
}

function phaseValue(value: unknown): CliPhase | undefined {
  if (
    value === 'session' ||
    value === 'thinking' ||
    value === 'text' ||
    value === 'tool' ||
    value === 'command' ||
    value === 'file_change' ||
    value === 'mcp' ||
    value === 'todo' ||
    value === 'retry' ||
    value === 'result' ||
    value === 'error'
  ) return value
  return undefined
}

function arrayValue(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined
  return value.map(String)
}

function fallbackPresentation(event: EventRecord): { title: string; message: string; severity: EventSeverity; action_hint?: string } {
  const payload = event.payload
  const reason = stringValue(payload.stderr) ?? stringValue(payload.reason) ?? stringValue(payload.notes) ?? stringValue(payload.warning)
  const count = typeof payload.count === 'number' ? `数量: ${payload.count}` : undefined
  const severity: EventSeverity =
    event.type.includes('failed') || event.type.includes('blocked') || event.type.includes('max_retries') || event.type === 'artifact.invalid'
      ? 'error'
      : event.type.includes('warning') || event.type.includes('rejected')
        ? 'warning'
        : event.type.includes('completed') || event.type.includes('approved') || event.type.includes('passed') || event.type.includes('delivered')
          ? 'success'
          : 'info'
  return {
    title: eventLabel(event.type),
    message: reason ?? count ?? '系统状态已更新。',
    severity,
    action_hint: severity === 'error' ? '查看运行摘要和原始日志，定位失败原因。' : undefined,
  }
}
