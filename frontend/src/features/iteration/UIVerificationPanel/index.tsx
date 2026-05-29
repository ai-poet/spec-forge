import { artifactUrl } from '../../../shared/lib/api'
import { uiDriverLabel, uiStatusLabel } from '../../../shared/lib/labels'
import type { IterationDetail, UITestResult } from '../../../shared/lib/types'

interface Props {
  detail: IterationDetail | null
}

function count(results: UITestResult[], status: UITestResult['status']) {
  return results.filter((result) => result.status === status).length
}

export function UIVerificationPanel({ detail }: Props) {
  const results = detail?.ui_results ?? []
  const warnings = results.filter((result) => result.status === 'warning')
  const failed = count(results, 'failed')

  return (
    <section className="ui-verify stack">
      <div className="section-row">
        <div>
          <h3 className="section-title">UI 验证</h3>
          <div className="muted">Node 4 作为 Tester 的工具调用，不改变 LangGraph 主节点。</div>
        </div>
        <div className="ui-metrics">
          <span className="pill">总数: {results.length}</span>
          <span className="pill good">通过: {count(results, 'passed')}</span>
          <span className={`pill ${failed ? 'danger-pill' : ''}`}>失败: {failed}</span>
          <span className={`pill ${warnings.length ? 'warning-pill' : ''}`}>未执行: {warnings.length}</span>
        </div>
      </div>

      {!results.length ? <div className="empty">本轮没有 Planner 定义的 UI trajectory，或尚未执行到 Tester。</div> : null}
      <div className="ui-result-list">
        {results.map((result) => (
          <article key={result.id} className={`ui-result ${result.status}`}>
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
              <ul className="compact-list">
                {result.observations.map((item) => <li key={item}>{item}</li>)}
              </ul>
            ) : null}
            {result.artifacts.length ? (
              <div className="actions">
                {result.artifacts.map((artifact) => (
                  <a
                    key={`${result.id}-${artifact.path}`}
                    className="artifact-link"
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
