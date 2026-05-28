import type { IterationDetail } from '../../../shared/lib/types'
import { nodeLabel, retryLabel } from '../../../shared/lib/labels'
import { classifyIterationProblem, documentSummary, presentEvent } from '../../../shared/lib/presentation'

interface Props {
  detail: IterationDetail | null
  busy: boolean
  onApproveVerify: () => Promise<void>
  onStop: () => Promise<void>
  onResume: () => Promise<void>
}

const readable: Record<string, { title: string; body: string }> = {
  queued: { title: '已排队', body: '后台执行器会开始运行规划节点。' },
  planning: { title: '正在规划', body: '规划节点正在根据大需求拆分任务并生成设计文档、修改计划和测试。' },
  awaiting_design_approval: { title: '正在推进', body: '规划已完成，系统正在自动进入实现。' },
  coding: { title: '正在写代码', body: '实现节点正在根据规划产出的规格实现代码。' },
  retrying: { title: '正在自动修复', body: '上一轮验证失败，系统正在带着失败信息回到实现节点。' },
  testing: { title: '正在验证', body: '独立验证和完整性检查正在执行。' },
  awaiting_verify_approval: { title: '等待确认交付', body: '测试和验证报告已通过，请确认本轮交付。' },
  delivered: { title: '已交付', body: '这个迭代已完成并通过最终确认。' },
  blocked: { title: '需要处理阻断', body: '系统无法继续自动推进，请查看错误和事件流。' },
  blocked_user: { title: '等待人工澄清', body: '自动澄清次数已用完，需要你补充决策。' },
  stopped: { title: '已停止', body: '流水线已在当前步骤暂停，可从该步骤继续执行。' },
}

export function ActionPanel({ detail, busy, onApproveVerify, onStop, onResume }: Props) {
  const state = detail ? readable[detail.status] ?? { title: detail.status, body: '查看事件流了解当前状态。' } : null
  const stoppedStep = detail?.stopped_at_node ? (nodeLabel[detail.stopped_at_node] ?? detail.stopped_at_node) : null
  const problem = classifyIterationProblem(detail)
  const docs = documentSummary(detail)
  const verifyReady = detail?.documents.some((doc) => doc.name === 'verify_report') ?? false

  return (
    <section className={`action-bar ${detail?.status ?? 'empty'}`}>
      <div className="action-bar-main">
        <div>
          <strong>{state?.title ?? '请选择迭代'}</strong>
          <p className="muted action-bar-body">
            {detail?.status === 'stopped' && stoppedStep
              ? `停止于「${stoppedStep}」步骤，点击继续执行将从该步骤恢复。`
              : (state?.body ?? '选中一条流水线后，这里会显示下一步动作。')}
          </p>
        </div>
        {problem ? (
          <div className={`action-bar-alert ${problem.severity === 'warning' ? 'warning' : 'error'}`}>
            <strong>{problem.title}</strong>
            <span>{problem.message}</span>
          </div>
        ) : null}
        {detail?.status === 'awaiting_verify_approval' ? (
          <div className="approval-checklist compact-checklist">
            <span className={verifyReady ? 'ok-text' : 'muted'}>{verifyReady ? '✓' : '○'} 验证报告</span>
          </div>
        ) : null}
        {detail?.retry_counts && Object.keys(detail.retry_counts).length ? (
          <div className="retry-row compact-retry">
            {Object.entries(detail.retry_counts).map(([key, value]) => (
              <span className="pill" key={key}>{retryLabel(key)}: {value}</span>
            ))}
          </div>
        ) : null}
      </div>
      <div className="action-bar-actions">
        <button type="button" className="btn primary" onClick={onApproveVerify} disabled={busy || detail?.status !== 'awaiting_verify_approval'}>
          确认交付
        </button>
        <button type="button" className="btn primary" onClick={onResume} disabled={busy || detail?.status !== 'stopped' || !detail.stopped_at_node}>
          继续执行
        </button>
        <button type="button" className="btn btn-ghost" onClick={onStop} disabled={busy || !detail || ['delivered', 'blocked', 'stopped'].includes(detail.status)}>
          停止
        </button>
      </div>
    </section>
  )
}
