import { describe, expect, it } from 'vitest'
import type { IterationDetail, LogSummaryResponse } from '../../../shared/lib/types'
import { formatLogSummaryMarkdown, logSummaryMarkdownFilename } from './logSummaryMarkdown'

const detail = {
  id: 'iter_123',
  project_name: 'spec forge',
  status: 'blocked',
} as IterationDetail

const summary: LogSummaryResponse = {
  generated: true,
  generating: false,
  generated_at: '2026-06-10T03:00:00Z',
  updated_at: '2026-06-10T03:00:00Z',
  error: null,
  stages: [
    {
      stage: 'PRD | 规划',
      status: '完成',
      description: '锁定 API\n数据契约',
      run_ids: ['run_1', 'run_2'],
    },
  ],
  final_summary: 'AI 已整理任务日志。',
  acceptance_points: [
    {
      point: '可查看任务级日志总结',
      status: '通过',
      evidence: '页面显示阶段表',
    },
  ],
  risks_or_followups: ['继续观察生成失败重试路径'],
}

describe('log summary markdown export', () => {
  it('formats generated log summary as markdown', () => {
    const markdown = formatLogSummaryMarkdown(summary, detail)

    expect(markdown).toContain('# spec forge 日志总结')
    expect(markdown).toContain('| PRD \\| 规划 | 完成 | 锁定 API<br>数据契约 | run_1, run_2 |')
    expect(markdown).toContain('## 最终总结\n\nAI 已整理任务日志。')
    expect(markdown).toContain('- [通过] 可查看任务级日志总结 Evidence: 页面显示阶段表')
    expect(markdown).toContain('- 继续观察生成失败重试路径')
  })

  it('builds a safe markdown filename', () => {
    expect(logSummaryMarkdownFilename(detail)).toBe('spec-forge-iter_123-log-summary.md')
  })
})
