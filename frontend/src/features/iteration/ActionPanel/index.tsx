import type { IterationDetail } from '../../../shared/lib/types'
import { retryLabel } from '../../../shared/lib/labels'
import { RunningIndicator } from '../../../shared/ui/RunningIndicator'
import {
  isPipelineRunning,
  isPlannerVerifyRejectRetry,
  isVerifyRejectRetest,
  latestRetryTarget,
  latestNodeProgress,
  runningNodeLabel,
} from '../../pipeline/lib/pipelineLive'
import { classifyIterationProblem, presentNodeName } from '../../../shared/lib/presentation'
import { RequirementsDiscoveryPanel } from '../RequirementsDiscoveryPanel'
import styles from './ActionPanel.module.less'

interface Props {
  detail: IterationDetail | null
  reviewMode?: boolean
  busy: boolean
  onAnswerRequirements: (answer: string) => Promise<void>
  onSkipDiscovery: () => Promise<void>
  onApproveDesign: () => Promise<void>
  onApproveVerify: () => Promise<void>
  onStop: () => Promise<void>
  onResume: () => Promise<void>
}

const readable: Record<string, { title: string; body: string }> = {
  queued: { title: '已排队', body: '后台执行器会开始运行规划节点。' },
  planning: { title: '正在规划', body: '规划节点正在根据大需求拆分任务并生成设计文档、修改计划和测试。' },
  awaiting_requirements_input: { title: '等待需求澄清', body: 'Planner 需要你回答一个问题，以便在生成设计文档前把需求具体化。' },
  awaiting_design_approval: { title: '等待设计审批', body: '规划文档已生成，请审阅系统设计、修改计划与测试方案后批准进入实现。' },
  coding: { title: '正在写代码', body: '实现节点正在根据规划产出的规格实现代码。' },
  retrying: { title: '正在自动修复', body: '上一轮验证失败，系统正在带着失败信息回到实现节点。' },
  testing: { title: '正在验证', body: '独立验证和完整性检查正在执行。' },
  awaiting_verify_approval: { title: '等待确认交付', body: '测试和验证报告已通过，请确认本轮交付。' },
  delivered: { title: '已交付', body: '这个迭代已完成并通过最终确认。' },
  blocked: { title: '需要处理阻断', body: '系统无法继续自动推进，请查看错误和事件流。' },
  blocked_user: { title: '等待人工澄清', body: '自动澄清次数已用完，需要你补充决策。' },
  stopped: { title: '已停止', body: '流水线已在当前步骤暂停，可从该步骤继续执行。' },
}

const BAR_STATUS_CLASS: Record<string, string> = {
  awaiting_requirements_input: styles.barAwaitingApproval,
  awaiting_design_approval: styles.barAwaitingApproval,
  awaiting_verify_approval: styles.barAwaitingApproval,
  blocked: styles.barBlocked,
  blocked_user: styles.barBlocked,
  failed: styles.barBlocked,
}

const RUNNING_BAR_CLASS: Record<string, string> = {
  queued: styles.barRunning,
  planning: styles.barRunning,
  awaiting_design_approval: styles.barRunning,
  coding: styles.barRunning,
  retrying: styles.barRunning,
  testing: styles.barRunning,
}

function resolveStatusCopy(detail: IterationDetail) {
  const base = readable[detail.status] ?? { title: detail.status, body: '查看事件流了解当前状态。' }
  if (isVerifyRejectRetest(detail)) {
    return {
      title: '正在重新验证（规格复核驳回后）',
      body: '上一轮 verify_report 格式不合格，Tester 正在重写报告，无需 Coder 改代码。',
    }
  }
  if (isPlannerVerifyRejectRetry(detail)) {
    return {
      title: '规格复核驳回，准备重新验证',
      body: 'verify_report 格式不合格，系统将回到 Tester 重写验证报告。',
    }
  }
  if (detail.status === 'retrying' && latestRetryTarget(detail) === 'tester') {
    return {
      title: 'Tester 正在自修验证产物',
      body: '缺陷落在 Tester 写区（adversarial / 验证文档），无需 Coder 改 src。',
    }
  }
  if (detail.status === 'retrying' && (detail.retry_counts?.coder_tester ?? 0) > 0) {
    return {
      title: '正在自动修复',
      body: '上一轮验证失败，系统正在带着失败信息回到实现节点。',
    }
  }
  if (detail.status === 'testing' && latestRetryTarget(detail) === 'tester') {
    return {
      title: 'Tester 正在自修验证产物',
      body: '上一轮验证产物不合格，Tester 正在修复 adversarial 或验证文档。',
    }
  }
  if (detail.status === 'retrying') {
    return base
  }
  return base
}

export function ActionPanel({
  detail,
  reviewMode = false,
  busy,
  onAnswerRequirements,
  onSkipDiscovery,
  onApproveDesign,
  onApproveVerify,
  onStop,
  onResume,
}: Props) {
  const state = detail ? resolveStatusCopy(detail) : null
  const stoppedStep = detail?.stopped_at_node ? presentNodeName(detail.stopped_at_node) : null
  const problem = reviewMode ? null : classifyIterationProblem(detail)
  const verifyReady = detail?.documents.some((doc) => doc.name === 'verify_report') ?? false
  const running = !reviewMode && isPipelineRunning(detail)
  const progress = latestNodeProgress(detail)
  const currentNode = runningNodeLabel(detail)
  const statusClass = detail?.status ? BAR_STATUS_CLASS[detail.status] ?? RUNNING_BAR_CLASS[detail.status] ?? '' : ''

  return (
    <section className={`${styles.bar} ${statusClass} ${running ? styles.barRunning : ''} ${reviewMode ? styles.barReview : ''}`.trim()}>
      <div className={styles.main}>
        {reviewMode && isPipelineRunning(detail) ? (
          <div className={styles.reviewNote}>
            流水线仍在运行{currentNode ? `（当前：${currentNode}）` : ''}，上方为实时状态；下方为阶段回顾。
          </div>
        ) : null}
        <div>
          <div className={styles.titleRow}>
            {running ? <RunningIndicator size="sm" mode="spinner" /> : null}
            <strong>{state?.title ?? '请选择迭代'}</strong>
            {running && currentNode ? <span className={styles.nodeBadge}>{currentNode}</span> : null}
          </div>
          <p className={`muted ${styles.body}`}>
            {detail?.status === 'stopped' && stoppedStep
              ? `停止于「${stoppedStep}」步骤，点击继续执行将从该步骤恢复。`
              : (state?.body ?? '选中一条流水线后，这里会显示下一步动作。')}
          </p>
          {running && progress ? (
            <div className={styles.progressBox}>
              <strong>{progress.title}</strong>
              <span>{progress.message}</span>
            </div>
          ) : null}
        </div>
        {problem ? (
          <div className={`${styles.alert} ${problem.severity === 'warning' ? styles.alertWarning : styles.alertError}`}>
            <strong>{problem.title}</strong>
            <span>{problem.message}</span>
          </div>
        ) : null}
        {detail?.status === 'awaiting_requirements_input' && !reviewMode ? (
          <RequirementsDiscoveryPanel
            detail={detail}
            busy={busy}
            onSubmitAnswer={onAnswerRequirements}
            onSkip={onSkipDiscovery}
          />
        ) : null}
        {detail?.status === 'awaiting_design_approval' ? (
          <div className={styles.approvalChecklist}>
            <span className={detail.documents.some((doc) => doc.name === 'system_design') ? 'ok-text' : 'muted'}>
              {detail.documents.some((doc) => doc.name === 'system_design') ? '✓' : '○'} 系统设计
            </span>
            <span className={detail.documents.some((doc) => doc.name === 'modification_plan') ? 'ok-text' : 'muted'}>
              {detail.documents.some((doc) => doc.name === 'modification_plan') ? '✓' : '○'} 修改计划
            </span>
            <span className={detail.documents.some((doc) => doc.name === 'testing_plan') ? 'ok-text' : 'muted'}>
              {detail.documents.some((doc) => doc.name === 'testing_plan') ? '✓' : '○'} 测试计划
            </span>
          </div>
        ) : null}
        {detail?.status === 'awaiting_verify_approval' ? (
          <div className={styles.approvalChecklist}>
            <span className={verifyReady ? 'ok-text' : 'muted'}>{verifyReady ? '✓' : '○'} 验证报告</span>
          </div>
        ) : null}
        {detail?.retry_counts && Object.keys(detail.retry_counts).length ? (
          <div className={styles.retryRow}>
            {Object.entries(detail.retry_counts).map(([key, value]) => (
              <span className="pill" key={key}>{retryLabel(key)}: {value}</span>
            ))}
          </div>
        ) : null}
      </div>
      <div className={styles.actions}>
        <button
          type="button"
          className="btn primary"
          onClick={onApproveDesign}
          disabled={busy || detail?.status !== 'awaiting_design_approval'}
        >
          批准设计
        </button>
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
