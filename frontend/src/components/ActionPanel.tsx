import type { IterationDetail } from '../types'

interface Props {
  detail: IterationDetail | null
  busy: boolean
  onApproveDesign: () => Promise<void>
  onApproveVerify: () => Promise<void>
  onStop: () => Promise<void>
}

const readable: Record<string, { title: string; body: string }> = {
  queued: { title: '已排队', body: '后台 worker 会开始执行 Planner。' },
  planning: { title: '正在规划', body: 'Planner 正在生成设计文档、修改计划和测试。' },
  awaiting_design_approval: { title: '需要审批设计', body: '请检查设计文档、修改计划和测试计划，然后批准进入实现。' },
  coding: { title: '正在写代码', body: 'Coder 正在根据批准后的规格实现代码。' },
  retrying: { title: '正在自动修复', body: '上一轮验证失败，系统正在带着失败信息回到 Coder。' },
  testing: { title: '正在验证', body: 'Tester 和完整性检查正在执行。' },
  awaiting_verify_approval: { title: '需要确认验证结果', body: '测试和验证报告已通过，请确认本轮交付。' },
  delivered: { title: '已交付', body: '这个 iteration 已完成并通过最终确认。' },
  blocked: { title: '需要处理阻断', body: '系统无法继续自动推进，请查看错误和事件流。' },
  blocked_user: { title: '等待人工澄清', body: '自动澄清次数已用完，需要你补充决策。' },
  stopped: { title: '已停止', body: '这个 iteration 已被手动停止。' },
}

export function ActionPanel({ detail, busy, onApproveDesign, onApproveVerify, onStop }: Props) {
  const state = detail ? readable[detail.status] ?? { title: detail.status, body: '查看事件流了解当前状态。' } : null
  const designDocs = detail?.documents.filter((doc) => ['system_design', 'modification_plan', 'testing_plan'].includes(doc.name)).length ?? 0
  const verifyReady = detail?.documents.some((doc) => doc.name === 'verify_report') ?? false

  return (
    <section className={`panel action-panel ${detail?.status ?? 'empty'}`}>
      <div>
        <p className="eyebrow">Action Required</p>
        <h2>{state?.title ?? '请选择 iteration'}</h2>
        <p className="muted">{state?.body ?? '选中一个 iteration 后，这里会显示下一步动作。'}</p>
        {detail?.last_error ? <div className="error-banner">{detail.last_error}</div> : null}
        {detail ? (
          <div className="summary-grid">
            <span>{designDocs} design docs</span>
            <span>{verifyReady ? 'verify report ready' : 'verify report pending'}</span>
            <span>{Object.values(detail.retry_counts).reduce((sum, value) => sum + value, 0)} retries</span>
          </div>
        ) : null}
      </div>
      <div className="actions">
        <button className="btn primary" onClick={onApproveDesign} disabled={busy || detail?.status !== 'awaiting_design_approval'}>
          Approve design
        </button>
        <button className="btn primary" onClick={onApproveVerify} disabled={busy || detail?.status !== 'awaiting_verify_approval'}>
          Approve verify
        </button>
        <button className="btn" onClick={onStop} disabled={busy || !detail || ['delivered', 'blocked', 'stopped'].includes(detail.status)}>
          Stop
        </button>
      </div>
    </section>
  )
}
