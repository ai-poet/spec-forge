import { eventLabel, graphNodeLabel, iterationStatusLabel, nodeLabel, retryLabel } from '../labels'
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
  const deliveryAdvice = detail?.documents.find((doc) => doc.name === 'delivery_advice')
  const uiResults = detail?.ui_results ?? []
  const adviceEvent = detail?.events.find((event) => event.type === 'tester.delivery_advice')
  const uxNotes = Array.isArray(adviceEvent?.payload.ux_notes) ? adviceEvent.payload.ux_notes.map(String) : []
  const recommendations = Array.isArray(adviceEvent?.payload.delivery_recommendations)
    ? adviceEvent.payload.delivery_recommendations.map(String)
    : []
  const currentNode = detail?.current_node ? nodeLabel[detail.current_node] : detail?.graph_next.map(graphNodeLabel).join(', ') || '结束'

  return (
    <section className="panel stack">
      <h2 className="section-title">迭代摘要</h2>
      {!detail ? <div className="empty">请选择迭代</div> : null}
      {detail ? (
        <>
          <div className="summary-grid">
            <span>状态: {iterationStatusLabel[detail.status]}</span>
            <span>模式: {detail.mode}</span>
            <span>节点: {currentNode}</span>
            <span>测试命令: {detail.test_command ?? '使用项目默认值'}</span>
          </div>
          {Object.keys(detail.retry_counts).length ? (
            <div className="retry-row">
              {Object.entries(detail.retry_counts).map(([key, value]) => (
                <span className="pill" key={key}>{retryLabel(key)}: {value}</span>
              ))}
            </div>
          ) : null}
          {detail.last_error ? <div className="error-banner">{detail.last_error}</div> : null}
          <div className="summary-columns">
            <div>
              <strong>变更路径</strong>
              <ul>
                {changedPaths.map((path) => <li key={path}>{path}</li>)}
                {!changedPaths.length ? <li className="muted">暂无代码路径事件</li> : null}
              </ul>
            </div>
            <div>
              <strong>测试完整性</strong>
              <ul>
                {integrityEvents.map((event) => <li key={event.id}>{eventLabel(event.type)}</li>)}
                {!integrityEvents.length ? <li className="muted">暂无完整性事件</li> : null}
              </ul>
            </div>
            <div>
              <strong>验证与交付</strong>
              <p className="muted">{verifyReport ? '验证报告已生成' : '验证报告尚未生成'}</p>
              <p className="muted">{deliveryAdvice ? '交付建议已生成' : '交付建议尚未生成'}</p>
              <p className="muted">UI 验证: {uiResults.length ? `${uiResults.filter((item) => item.status === 'passed').length}/${uiResults.length} 通过` : '未执行'}</p>
            </div>
          </div>
          {uxNotes.length || recommendations.length ? (
            <div className="summary-columns">
              <div>
                <strong>用户体验观察</strong>
                <ul>
                  {uxNotes.map((note) => <li key={note}>{note}</li>)}
                </ul>
              </div>
              <div>
                <strong>后续交付建议</strong>
                <ul>
                  {recommendations.map((item) => <li key={item}>{item}</li>)}
                </ul>
              </div>
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  )
}
