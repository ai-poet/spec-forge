import type { IterationDetail } from '../types'
import { retryLabel } from '../labels'
import { classifyIterationProblem, documentSummary, presentEvent } from '../presentation'

interface Props {
  detail: IterationDetail | null
  busy: boolean
  onApproveDesign: () => Promise<void>
  onApproveVerify: () => Promise<void>
  onStop: () => Promise<void>
}

const readable: Record<string, { title: string; body: string }> = {
  queued: { title: '已排队', body: '后台执行器会开始运行规划节点。' },
  planning: { title: '正在规划', body: '规划节点正在生成设计文档、修改计划和测试。' },
  awaiting_design_approval: { title: '需要审批设计', body: '请检查设计文档、修改计划和测试计划，然后批准进入实现。' },
  coding: { title: '正在写代码', body: '实现节点正在根据批准后的规格实现代码。' },
  retrying: { title: '正在自动修复', body: '上一轮验证失败，系统正在带着失败信息回到实现节点。' },
  testing: { title: '正在验证', body: '独立验证和完整性检查正在执行。' },
  awaiting_verify_approval: { title: '需要确认验证结果', body: '测试和验证报告已通过，请确认本轮交付。' },
  delivered: { title: '已交付', body: '这个迭代已完成并通过最终确认。' },
  blocked: { title: '需要处理阻断', body: '系统无法继续自动推进，请查看错误和事件流。' },
  blocked_user: { title: '等待人工澄清', body: '自动澄清次数已用完，需要你补充决策。' },
  stopped: { title: '已停止', body: '这个迭代已被手动停止。' },
}

export function ActionPanel({ detail, busy, onApproveDesign, onApproveVerify, onStop }: Props) {
  const state = detail ? readable[detail.status] ?? { title: detail.status, body: '查看事件流了解当前状态。' } : null
  const designDocs = detail?.documents.filter((doc) => ['system_design', 'modification_plan', 'testing_plan'].includes(doc.name)).length ?? 0
  const verifyReady = detail?.documents.some((doc) => doc.name === 'verify_report') ?? false
  const problem = classifyIterationProblem(detail)
  const activities = detail?.events.map(presentEvent).filter((event) => event.type.startsWith('node.') || event.type.startsWith('artifact.')) ?? []
  const latestActivity = activities[activities.length - 1]
  const docs = documentSummary(detail)
  const designReady = docs.filter((doc) => ['system_design', 'modification_plan', 'testing_plan'].includes(doc.name)).every((doc) => doc.present)
  const warnings = detail?.events.map(presentEvent).filter((event) => event.severity === 'warning').length ?? 0

  return (
    <section className={`panel action-panel ${detail?.status ?? 'empty'}`}>
      <div>
        <p className="eyebrow">需要处理</p>
        <h2>{state?.title ?? '请选择迭代'}</h2>
        <p className="muted">{state?.body ?? '选中一个迭代后，这里会显示下一步动作。'}</p>
        {latestActivity ? (
          <div className={`status-narrative ${latestActivity.severity}`}>
            <strong>{latestActivity.title}</strong>
            <span>{latestActivity.message}</span>
          </div>
        ) : null}
        {problem ? (
          <div className={`error-banner ${problem.severity === 'warning' ? 'warning-banner' : ''}`}>
            <strong>{problem.title}</strong>
            <p>{problem.message}</p>
            <small>{problem.action_hint}</small>
          </div>
        ) : null}
        {detail ? (
          <div className="summary-grid">
            <span>{designDocs} 份设计文档</span>
            <span>{verifyReady ? '验证报告已生成' : '验证报告未生成'}</span>
            <span>{Object.values(detail.retry_counts).reduce((sum, value) => sum + value, 0)} 次重试</span>
            <span>{warnings ? `${warnings} 个 warning` : '无 warning'}</span>
          </div>
        ) : null}
        {detail?.status === 'awaiting_design_approval' || detail?.status === 'awaiting_verify_approval' ? (
          <div className="approval-checklist">
            <span className={designReady ? 'ok-text' : 'muted'}>{designReady ? '✓' : '·'} 设计/计划/测试文档齐全</span>
            <span className={verifyReady || detail.status === 'awaiting_design_approval' ? 'ok-text' : 'muted'}>{verifyReady ? '✓' : '·'} 验证报告{verifyReady ? '已生成' : '未生成'}</span>
            <span className={warnings ? 'warning-text' : 'ok-text'}>{warnings ? '!' : '✓'} {warnings ? '存在 warning，交付前请确认' : '暂无 warning'}</span>
          </div>
        ) : null}
        {detail?.retry_counts && Object.keys(detail.retry_counts).length ? (
          <div className="retry-row">
            {Object.entries(detail.retry_counts).map(([key, value]) => (
              <span className="pill" key={key}>{retryLabel(key)}: {value}</span>
            ))}
          </div>
        ) : null}
      </div>
      <div className="actions">
        <button className="btn primary" onClick={onApproveDesign} disabled={busy || detail?.status !== 'awaiting_design_approval'}>
          批准设计
        </button>
        <button className="btn primary" onClick={onApproveVerify} disabled={busy || detail?.status !== 'awaiting_verify_approval'}>
          确认验证
        </button>
        <button className="btn" onClick={onStop} disabled={busy || !detail || ['delivered', 'blocked', 'stopped'].includes(detail.status)}>
          停止
        </button>
      </div>
    </section>
  )
}
