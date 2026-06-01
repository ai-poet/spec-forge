import { artifactUrl } from '../../../shared/lib/api'
import { uiDriverLabel, uiStatusLabel } from '../../../shared/lib/labels'
import type { IterationDetail, UITestResult } from '../../../shared/lib/types'
import { needsPlaywrightInstall, UI_PLAYWRIGHT_INSTALL_HINT } from '../../../shared/lib/uiInstallHint'
import { isUiDriverRunning } from '../../pipeline/lib/pipelineLive'
import { RunningIndicator } from '../../../shared/ui/RunningIndicator'
import styles from './UIVerificationPanel.module.less'

interface Props {
  detail: IterationDetail | null
}

const RESULT_STATUS_CLASS: Record<string, string | undefined> = {
  failed: styles.resultFailed,
  warning: styles.resultWarning,
  skipped: styles.resultWarning,
}

function count(results: UITestResult[], status: UITestResult['status']) {
  return results.filter((result) => result.status === status).length
}

function showInstallGuide(results: UITestResult[]) {
  return results.some((result) => result.status === 'warning' && needsPlaywrightInstall(result.error))
}

export function UIVerificationPanel({ detail }: Props) {
  const results = detail?.ui_results ?? []
  const warnings = results.filter((result) => result.status === 'warning')
  const failed = count(results, 'failed')
  const uiDriverRunning = isUiDriverRunning(detail)
  const installGuideVisible = showInstallGuide(results)

  return (
    <section className={`${styles.root} stack`}>
      <div className="section-row">
        <div>
          <h3 className="section-title">UI 验证</h3>
          <div className="muted">Node 4 作为 Tester 的工具调用，不改变 LangGraph 主节点。</div>
        </div>
        <div className={styles.metrics}>
          {uiDriverRunning ? <RunningIndicator size="sm" mode="dot" label="运行中" /> : null}
          <span className="pill">总数: {results.length}</span>
          <span className="pill good">通过: {count(results, 'passed')}</span>
          <span className={`pill ${failed ? 'danger-pill' : ''}`}>失败: {failed}</span>
          <span className={`pill ${warnings.length ? 'warning-pill' : ''}`}>未执行: {warnings.length}</span>
        </div>
      </div>

      {uiDriverRunning ? (
        <div className={styles.runningBanner}>
          <RunningIndicator label="UI Driver 正在执行 trajectory…" />
          <span className="muted">完成后会在此展示每条 UI 测试结果。</span>
        </div>
      ) : null}

      {!results.length && !uiDriverRunning ? <div className="empty">本轮没有 Planner 定义的 UI trajectory，或尚未执行到 Tester。</div> : null}
      {installGuideVisible ? (
        <div className={styles.installGuide}>
          <strong>Web UI（CSS selector）需要 Playwright</strong>
          <p className="muted">
            在运行后端的同一 Python 环境中安装 UI 依赖，然后重启后端并重新跑 Tester。
          </p>
          <pre className={styles.installCommand}>{UI_PLAYWRIGHT_INSTALL_HINT}</pre>
          <p className="muted">跳过自动安装：启动前设置 <code>SPECFORGE_SKIP_UI=1</code>（仅当你不需要 UI 自动化时）。</p>
        </div>
      ) : null}
      <div className={styles.resultList}>
        {results.map((result) => (
          <article key={result.id} className={`${styles.result} ${RESULT_STATUS_CLASS[result.status] ?? ''}`}>
            <div className="section-row">
              <div>
                <strong>{result.title || result.id}</strong>
                <div className="muted">
                  {result.kind === 'web' ? 'Web 应用' : '原生应用'} · {result.target || '未声明目标'}
                  {result.driver ? ` · ${uiDriverLabel(result.driver)}` : ''}
                </div>
              </div>
              <span className={`status-dot ${result.status}`}>{uiStatusLabel(result.status)}</span>
            </div>
            {result.error ? <div className="error-text">{result.error}</div> : null}
            {result.observations.length ? (
              <ul className={styles.compactList}>
                {result.observations.map((item) => <li key={item}>{item}</li>)}
              </ul>
            ) : null}
            {result.artifacts.length ? (
              <div className="actions">
                {result.artifacts.map((artifact) => (
                  <a
                    key={`${result.id}-${artifact.path}`}
                    className={styles.artifactLink}
                    href={detail ? artifactUrl(detail.id, artifact.path) : '#'}
                    target="_blank"
                    rel="noreferrer"
                    title={artifact.path}
                  >
                    {artifact.label}
                  </a>
                ))}
              </div>
            ) : null}
          </article>
        ))}
      </div>
    </section>
  )
}
