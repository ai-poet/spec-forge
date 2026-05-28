import type { EpicSummary } from '../../../shared/lib/types'
import { epicStatusLabel } from '../../../shared/lib/labels'

interface Props {
  epics: EpicSummary[]
  selectedEpicId: string | null
  onSelectEpic: (id: string) => void
}

export function EpicList({ epics, selectedEpicId, onSelectEpic }: Props) {
  return (
    <section className="panel stack">
      <div className="section-row">
        <h2 className="section-title">大需求</h2>
        <span className="pill">{epics.length}</span>
      </div>
      <div className="list epic-list">
        {epics.map((epic) => (
          <button key={epic.id} className={`item epic-item ${selectedEpicId === epic.id ? 'active' : ''}`} onClick={() => onSelectEpic(epic.id)}>
            <div className="item-head">
              <strong>{epic.title}</strong>
              <span className={`status-dot ${epic.status}`}>{epicStatusLabel[epic.status]}</span>
            </div>
            <div className="muted clamp">{epic.description || epic.acceptance_criteria || '暂无描述'}</div>
            <small>{epic.delivered_count}/{epic.iteration_count} 已交付 · {epic.blocked_count} 已阻断</small>
          </button>
        ))}
        {!epics.length ? <div className="empty">当前项目还没有大需求</div> : null}
      </div>
    </section>
  )
}
