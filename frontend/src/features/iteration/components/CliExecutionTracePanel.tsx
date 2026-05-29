import type { IterationDetail } from '../../../shared/lib/types'
import { cliPhaseLabel, cliProviderLabel, presentEvent, presentNodeName } from '../../../shared/lib/presentation'

interface Props {
  detail: IterationDetail | null
}

const TRACE_PHASES = new Set(['command', 'file_change', 'mcp', 'todo', 'tool', 'retry', 'result', 'error'])

export function CliExecutionTracePanel({ detail }: Props) {
  const events = (detail?.events ?? [])
    .filter((event) => event.type === 'cli.display')
    .map(presentEvent)
    .filter((event) => event.phase && TRACE_PHASES.has(event.phase))
    .slice(-24)
    .reverse()

  return (
    <section className="panel stack">
      <div className="section-row">
        <h2 className="section-title">实时执行轨迹</h2>
        <span className="pill">{events.length} 条</span>
      </div>
      <div className="cli-trace-list">
        {events.map((event) => (
          <article key={event.id} className={`cli-trace-item ${event.phase ?? 'text'} ${event.severity}`}>
            <div className="cli-trace-head">
              <span className="cli-phase">{cliPhaseLabel(event.phase)}</span>
              <strong>{event.title}</strong>
              <span className={`status-dot ${event.severity}`}>{cliProviderLabel(event.provider)}</span>
            </div>
            <p>{event.message}</p>
            {event.command ? <code className="trace-command">{event.command}</code> : null}
            {event.tool ? <div className="muted">工具: {event.tool}</div> : null}
            {event.paths?.length ? (
              <div className="trace-paths">
                {event.paths.map((path) => <span key={path}>{path}</span>)}
              </div>
            ) : null}
            {event.preview && event.phase === 'todo' ? <pre className="trace-preview">{event.preview}</pre> : null}
            <div className="muted">{presentNodeName(event.node)}</div>
          </article>
        ))}
        {!events.length ? <div className="empty">真实 CLI 运行时，这里会显示命令、文件变更、MCP 调用和任务清单。</div> : null}
      </div>
    </section>
  )
}
