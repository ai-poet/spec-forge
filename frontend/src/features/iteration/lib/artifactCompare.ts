import type { DocumentRecord, IterationDetail, IterationSummary } from '../../../shared/lib/types'

export const ARTIFACT_COMPARE_PRIORITY = [
  'log_summary',
  'verify_report',
  'delivery_advice',
  'ui_report',
  'ui_results',
  'prd',
  'testing_plan',
  'requirements_brief',
]

export type ArtifactPresence = 'same' | 'different' | 'current_only' | 'target_only' | 'missing'

export interface ArtifactOption {
  name: string
  current: DocumentRecord | null
  target: DocumentRecord | null
  presence: ArtifactPresence
}

export interface LineDiffStats {
  current_lines: number
  target_lines: number
  changed: number
  added: number
  removed: number
  equal: boolean
}

export function comparisonCandidates(items: IterationSummary[], currentId: string | null): IterationSummary[] {
  return items
    .filter((item) => item.id !== currentId)
    .slice()
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
}

export function artifactOptions(current: IterationDetail | null, target: IterationDetail | null): ArtifactOption[] {
  const currentDocs = new Map((current?.documents ?? []).map((doc) => [doc.name, doc]))
  const targetDocs = new Map((target?.documents ?? []).map((doc) => [doc.name, doc]))
  const names = new Set([...ARTIFACT_COMPARE_PRIORITY, ...currentDocs.keys(), ...targetDocs.keys()])
  return [...names]
    .map((name) => {
      const currentDoc = currentDocs.get(name) ?? null
      const targetDoc = targetDocs.get(name) ?? null
      return {
        name,
        current: currentDoc,
        target: targetDoc,
        presence: artifactPresence(currentDoc, targetDoc),
      }
    })
    .filter((item) => item.current || item.target || ARTIFACT_COMPARE_PRIORITY.includes(item.name))
    .sort((a, b) => artifactRank(a.name) - artifactRank(b.name) || a.name.localeCompare(b.name))
}

export function defaultArtifactName(current: IterationDetail | null, target: IterationDetail | null): string | null {
  return artifactOptions(current, target).find((item) => item.current || item.target)?.name ?? null
}

export function artifactPresence(current: DocumentRecord | null, target: DocumentRecord | null): ArtifactPresence {
  if (current && target) return current.checksum === target.checksum ? 'same' : 'different'
  if (current) return 'current_only'
  if (target) return 'target_only'
  return 'missing'
}

export function diffLineStats(currentText: string, targetText: string): LineDiffStats {
  const currentLines = splitLines(currentText)
  const targetLines = splitLines(targetText)
  let changed = 0
  let added = 0
  let removed = 0
  const max = Math.max(currentLines.length, targetLines.length)
  for (let index = 0; index < max; index += 1) {
    const currentLine = currentLines[index]
    const targetLine = targetLines[index]
    if (currentLine === targetLine) continue
    if (currentLine === undefined) {
      added += 1
    } else if (targetLine === undefined) {
      removed += 1
    } else {
      changed += 1
    }
  }
  return {
    current_lines: currentLines.length,
    target_lines: targetLines.length,
    changed,
    added,
    removed,
    equal: changed === 0 && added === 0 && removed === 0,
  }
}

function splitLines(value: string): string[] {
  if (!value) return []
  return value.replace(/\r\n/g, '\n').split('\n')
}

function artifactRank(name: string) {
  const index = ARTIFACT_COMPARE_PRIORITY.indexOf(name)
  return index >= 0 ? index : ARTIFACT_COMPARE_PRIORITY.length + 1
}
