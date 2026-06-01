import type { SemanticEvent } from './types'

const MERGE_PHASES = new Set(['text', 'thinking'])

function mergeKey(event: SemanticEvent): string | null {
  if (!event.item_id || !event.phase || !MERGE_PHASES.has(event.phase)) return null
  return `${event.node}:${event.phase}:${event.item_id}`
}

/** Collapse streaming text/thinking deltas that share the same item_id. */
export function mergeCliDisplayEvents(events: SemanticEvent[]): SemanticEvent[] {
  const merged: SemanticEvent[] = []
  const indexByKey = new Map<string, number>()

  for (const event of events) {
    const key = mergeKey(event)
    if (!key) {
      merged.push(event)
      continue
    }
    const existingIndex = indexByKey.get(key)
    if (existingIndex === undefined) {
      indexByKey.set(key, merged.length)
      merged.push({ ...event })
      continue
    }
    const existing = merged[existingIndex]
    const nextPreview = [existing.preview, event.preview].filter(Boolean).join('')
    const nextMessage = nextPreview || [existing.message, event.message].filter(Boolean).join('')
    merged[existingIndex] = {
      ...existing,
      id: event.id,
      created_at: event.created_at,
      preview: nextPreview || undefined,
      message: nextMessage,
      title: event.title || existing.title,
    }
  }
  return merged
}
