import { useCallback, useEffect, useState } from 'react'
import { getEnvironmentChecks } from '../../../shared/lib/api'
import type { EnvironmentChecksResult, EnvironmentCheckStatus } from '../../../shared/lib/types'
import { sortEnvironmentChecks, summarizeEnvironmentChecks } from '../lib/environmentChecks'

const STATUS_LABEL: Record<EnvironmentCheckStatus, string> = {
  ok: '正常',
  warning: '留意',
  error: '异常',
}

export function EnvironmentCheckPanel() {
  const [result, setResult] = useState<EnvironmentChecksResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setResult(await getEnvironmentChecks())
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : '无法连接后端，请确认服务已启动。')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load().catch(console.error)
  }, [load])

  const checks = sortEnvironmentChecks(result?.checks ?? [])
  const summary = error ? '检测失败' : loading && !result ? '检测中' : summarizeEnvironmentChecks(checks)

  return (
    <section className="surface stack">
      <div className="section-row">
        <div>
          <h2 className="section-title">环境检测</h2>
          <p className="muted">运行前预检 CLI、Web 自动化与 CuaDriver 状态；异常只提示，不阻断流水线。</p>
        </div>
        <div className="actions">
          <span className={`status-dot ${error ? 'error' : result?.status ?? 'info'}`}>{summary}</span>
          <button type="button" className="btn btn-sm" onClick={() => load().catch(console.error)} disabled={loading}>
            {loading ? '检测中' : '重新检测'}
          </button>
        </div>
      </div>

      {error ? <div className="error-text">{error}</div> : null}
      {!error && !checks.length ? <div className="empty">正在读取本机环境状态。</div> : null}

      {checks.length ? (
        <div className="list">
          {checks.map((check) => (
            <article key={check.id} className="item">
              <div className="section-row">
                <div>
                  <strong>{check.label}</strong>
                  <div className="muted">{check.message}</div>
                </div>
                <span className={`status-dot ${check.status}`}>{STATUS_LABEL[check.status]}</span>
              </div>
              {check.detail ? <div className="clamp muted">{check.detail}</div> : null}
              {check.hint ? <code className="inline-code">{check.hint}</code> : null}
            </article>
          ))}
        </div>
      ) : null}
    </section>
  )
}
