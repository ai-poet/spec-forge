import type { CliOutputPayload, EventRecord, IterationDetail } from '../../../shared/lib/types'

export const LIVE_CLI_MAX_CHARS = 64 * 1024

function trimTail(value: string): string {
  if (value.length <= LIVE_CLI_MAX_CHARS) return value
  return value.slice(value.length - LIVE_CLI_MAX_CHARS)
}

export function mergeLiveEvent(detail: IterationDetail | null, event: EventRecord): IterationDetail | null {
  if (!detail) return detail
  if (detail.events.some((item) => item.id === event.id)) return detail
  return {
    ...detail,
    events: [...detail.events, event],
  }
}

export function mergeLiveCliOutput(detail: IterationDetail | null, payload: CliOutputPayload): IterationDetail | null {
  if (!detail) return detail
  const existing = detail.live_cli ?? { node: payload.node, stdout: '', stderr: '' }
  const stdout = payload.stream === 'stdout' ? trimTail(existing.stdout + payload.chunk) : existing.stdout
  const stderr = payload.stream === 'stderr' ? trimTail(existing.stderr + payload.chunk) : existing.stderr
  return {
    ...detail,
    live_cli: {
      node: payload.node,
      stdout,
      stderr,
    },
  }
}
