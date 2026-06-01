import type { SemanticEvent } from './types'

export type ToolCardKind = 'edit' | 'write' | 'bash' | 'todo' | 'ask' | 'generic'

export interface ToolCardView {
  kind: ToolCardKind
  headline: string
  detail?: string
  paths: string[]
  command?: string
  todos: string[]
}

function rawInput(event: SemanticEvent): Record<string, unknown> | null {
  const raw = event.raw?.payload?.raw_event
  if (!raw || typeof raw !== 'object') return null
  const message = (raw as { message?: { content?: unknown } }).message
  if (message && Array.isArray(message.content)) {
    for (const block of message.content) {
      if (block && typeof block === 'object' && (block as { type?: string }).type === 'tool_use') {
        const input = (block as { input?: unknown }).input
        if (input && typeof input === 'object') return input as Record<string, unknown>
      }
    }
  }
  const stream = (raw as { stream_event?: { content_block?: unknown } }).stream_event
  const block = stream?.content_block
  if (block && typeof block === 'object' && (block as { input?: unknown }).input) {
    const input = (block as { input?: unknown }).input
    if (input && typeof input === 'object') return input as Record<string, unknown>
  }
  return null
}

function toolKind(tool: string | undefined): ToolCardKind {
  const name = (tool ?? '').toLowerCase()
  if (name.includes('edit') || name === 'multiedit') return 'edit'
  if (name.includes('write') || name === 'notebookedit') return 'write'
  if (name === 'bash' || name === 'shell') return 'bash'
  if (name === 'todowrite' || name === 'todo_write') return 'todo'
  if (name.includes('askuser') || name === 'ask_user_question') return 'ask'
  return 'generic'
}

function pathsFromInput(input: Record<string, unknown> | null, fallback: string[]): string[] {
  if (!input) return fallback
  const paths: string[] = [...fallback]
  for (const key of ['file_path', 'filePath', 'path', 'notebook_path']) {
    const value = input[key]
    if (typeof value === 'string' && value.trim()) paths.push(value.trim())
  }
  const list = input.paths ?? input.files
  if (Array.isArray(list)) {
    for (const item of list) {
      if (typeof item === 'string' && item.trim()) paths.push(item.trim())
    }
  }
  return [...new Set(paths)]
}

function todosFromInput(input: Record<string, unknown> | null): string[] {
  if (!input) return []
  const todos = input.todos ?? input.items
  if (!Array.isArray(todos)) return []
  return todos
    .slice(0, 8)
    .map((item) => {
      if (!item || typeof item !== 'object') return ''
      const row = item as { status?: string; text?: string; content?: string; title?: string }
      const text = row.text ?? row.content ?? row.title ?? ''
      if (!text) return ''
      const status = row.status ?? 'pending'
      return `${status}: ${text}`
    })
    .filter(Boolean)
}

export function buildToolCardView(event: SemanticEvent): ToolCardView | null {
  if (event.phase !== 'tool' && event.phase !== 'command' && event.phase !== 'todo') return null
  const tool = event.tool ?? ''
  const kind = event.phase === 'todo' ? 'todo' : toolKind(tool)
  const input = rawInput(event)
  const paths = pathsFromInput(input, event.paths ?? [])
  const command =
    event.command ??
    (typeof input?.command === 'string' ? input.command : undefined) ??
    (Array.isArray(input?.command) ? (input?.command as string[]).join(' ') : undefined)
  const todos = event.phase === 'todo' ? (event.preview?.split('\n').filter(Boolean) ?? []) : todosFromInput(input)

  const headlines: Record<ToolCardKind, string> = {
    edit: '编辑文件',
    write: '写入文件',
    bash: '执行命令',
    todo: '任务清单',
    ask: '向用户提问',
    generic: event.title,
  }

  return {
    kind,
    headline: headlines[kind],
    detail: event.preview || event.message,
    paths,
    command,
    todos,
  }
}
