import type { IterationDetail } from '../types'

interface Props {
  detail: IterationDetail | null
}

function eventMatches(detail: IterationDetail | null, token: string) {
  return detail?.events.filter((event) => event.type.includes(token)) ?? []
}

export function IterationSummaryPanel({ detail }: Props) {
  const changedPaths = detail?.events.flatMap((event) => {
    const value = event.payload.changed_paths
    return Array.isArray(value) ? value.map(String) : []
  }) ?? []
  const integrityEvents = eventMatches(detail, 'integrity')
  const verifyReport = detail?.documents.find((doc) => doc.name === 'verify_report')

  return (
    <section className="panel stack">
      <h2 className="section-title">Iteration 摘要</h2>
      {!detail ? <div className="empty">请选择 iteration</div> : null}
      {detail ? (
        <>
          <div className="summary-grid">
            <span>状态: {detail.status}</span>
            <span>模式: {detail.mode}</span>
            <span>节点: {detail.current_node ?? (detail.graph_next.join(', ') || 'END')}</span>
            <span>测试命令: {detail.test_command ?? 'project default'}</span>
          </div>
          {Object.keys(detail.retry_counts).length ? (
            <div className="retry-row">
              {Object.entries(detail.retry_counts).map(([key, value]) => (
                <span className="pill" key={key}>{key}: {value}</span>
              ))}
            </div>
          ) : null}
          {detail.last_error ? <div className="error-banner">{detail.last_error}</div> : null}
          <div className="summary-columns">
            <div>
              <strong>Changed paths</strong>
              <ul>
                {changedPaths.map((path) => <li key={path}>{path}</li>)}
                {!changedPaths.length ? <li className="muted">暂无代码路径事件</li> : null}
              </ul>
            </div>
            <div>
              <strong>Integrity / tests</strong>
              <ul>
                {integrityEvents.map((event) => <li key={event.id}>{event.type}</li>)}
                {!integrityEvents.length ? <li className="muted">暂无完整性事件</li> : null}
              </ul>
            </div>
            <div>
              <strong>Verify</strong>
              <p className="muted">{verifyReport ? 'verify_report 已生成' : 'verify_report 尚未生成'}</p>
            </div>
          </div>
        </>
      ) : null}
    </section>
  )
}
