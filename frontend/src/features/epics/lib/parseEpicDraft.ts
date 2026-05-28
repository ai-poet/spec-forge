export interface ParsedEpicDraft {
  title: string
  description: string
  acceptance_criteria: string
}

const ACCEPTANCE_HEADING = /(?:^|\n)\s*验收标准\s*[:：]\s*\n?/i

export function parseEpicDraft(text: string): ParsedEpicDraft | null {
  const trimmed = text.trim()
  if (!trimmed) return null

  const acceptanceMatch = trimmed.match(ACCEPTANCE_HEADING)
  let body = trimmed
  let acceptance_criteria = ''

  if (acceptanceMatch && acceptanceMatch.index !== undefined) {
    body = trimmed.slice(0, acceptanceMatch.index).trim()
    acceptance_criteria = trimmed.slice(acceptanceMatch.index + acceptanceMatch[0].length).trim()
  }

  const lines = body.split('\n')
  const firstLineIndex = lines.findIndex((line) => line.trim())
  if (firstLineIndex === -1) return null

  const title = lines[firstLineIndex].trim().slice(0, 80)
  const descriptionLines = lines.slice(firstLineIndex + 1)
  const description = descriptionLines.join('\n').trim()

  return {
    title,
    description,
    acceptance_criteria,
  }
}
