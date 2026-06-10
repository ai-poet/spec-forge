import type { IterationDetail, LogSummaryResponse } from '../../../shared/lib/types'

function escapeTableCell(value: string) {
  return value.replace(/\|/g, '\\|').replace(/\r?\n/g, '<br>')
}

function listItem(value: string) {
  return value.replace(/\r?\n/g, ' ').trim()
}

function safeFilePart(value: string) {
  return value
    .trim()
    .replace(/[^a-zA-Z0-9._-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80)
}

export function logSummaryMarkdownFilename(detail: IterationDetail) {
  const base = safeFilePart(detail.project_name) || 'iteration'
  const suffix = safeFilePart(detail.id) || 'log-summary'
  return `${base}-${suffix}-log-summary.md`
}

export function formatLogSummaryMarkdown(summary: LogSummaryResponse, detail: IterationDetail) {
  const lines: string[] = [
    `# ${detail.project_name} 日志总结`,
    '',
    `- Iteration: ${detail.id}`,
    `- 状态: ${detail.status}`,
  ]

  if (summary.generated_at) lines.push(`- 生成时间: ${new Date(summary.generated_at).toLocaleString()}`)
  lines.push('', '## 阶段状态', '', '| 阶段 | 状态 | 说明 | 关联 Run |', '| --- | --- | --- | --- |')

  if (summary.stages.length) {
    for (const stage of summary.stages) {
      lines.push([
        escapeTableCell(stage.stage || '未命名阶段'),
        escapeTableCell(stage.status || '未知'),
        escapeTableCell(stage.description || '暂无说明'),
        escapeTableCell(stage.run_ids?.length ? stage.run_ids.join(', ') : '暂无'),
      ].join(' | ').replace(/^/, '| ').replace(/$/, ' |'))
    }
  } else {
    lines.push('| 暂无 | 暂无 | 暂无阶段运行记录。 | 暂无 |')
  }

  lines.push('', '## 最终总结', '', summary.final_summary || '暂无最终总结。')

  lines.push('', '## 验收点', '')
  if (summary.acceptance_points.length) {
    for (const point of summary.acceptance_points) {
      const evidence = point.evidence ? ` Evidence: ${listItem(point.evidence)}` : ''
      lines.push(`- [${point.status || '未知'}] ${listItem(point.point || '未命名验收点')}${evidence}`)
    }
  } else {
    lines.push('暂无验收点。')
  }

  lines.push('', '## 风险与后续', '')
  if (summary.risks_or_followups.length) {
    for (const item of summary.risks_or_followups) {
      lines.push(`- ${listItem(item)}`)
    }
  } else {
    lines.push('暂无风险与后续。')
  }

  return `${lines.join('\n')}\n`
}
