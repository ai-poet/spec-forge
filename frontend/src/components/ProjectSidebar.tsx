import { useState } from 'react'
import type { ProjectSummary } from '../types'

interface Props {
  projects: ProjectSummary[]
  selectedProjectId: string | null
  onSelectProject: (id: string) => void
  onAddProject: (name: string, description?: string) => Promise<void>
  settingsOpen: boolean
  onToggleSettings: () => void
}

export function ProjectSidebar({
  projects,
  selectedProjectId,
  onSelectProject,
  onAddProject,
  settingsOpen,
  onToggleSettings,
}: Props) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [busy, setBusy] = useState(false)

  async function handleAdd() {
    if (!name.trim()) return
    setBusy(true)
    try {
      await onAddProject(name.trim(), description.trim() || undefined)
      setName('')
      setDescription('')
      setShowCreateForm(false)
    } finally {
      setBusy(false)
    }
  }

  return (
    <aside className="sidebar sidebar-layout">
      <div className="sidebar-top stack">
        <div className="brand">
          <h1>SpecForge</h1>
          <p>Agent 流水线工作台</p>
        </div>

        <button className="btn sidebar-new-btn" onClick={() => setShowCreateForm((value) => !value)}>
          {showCreateForm ? '取消' : '+ 新建项目'}
        </button>

        {showCreateForm ? (
          <section className="panel stack">
            <div className="form compact">
              <input value={name} onChange={(event) => setName(event.target.value)} placeholder="项目名称" />
              <input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="描述（可选）" />
              <button className="btn primary" onClick={handleAdd} disabled={busy || !name.trim()}>
                创建
              </button>
            </div>
          </section>
        ) : null}

        <section className="sidebar-projects stack">
          <h2 className="section-title sidebar-section-title">项目</h2>
          <div className="list sidebar-project-list">
            {projects.map((project) => (
              <button
                key={project.id}
                className={`item project-item ${selectedProjectId === project.id ? 'active' : ''}`}
                onClick={() => onSelectProject(project.id)}
              >
                <strong>{project.name}</strong>
                <span>{project.iteration_count} 条流水线</span>
                <small>
                  {project.active_count} 进行中 / {project.delivered_count} 已交付
                </small>
              </button>
            ))}
            {!projects.length ? <div className="empty">暂无项目，创建一个开始</div> : null}
          </div>
        </section>
      </div>

      <div className="sidebar-footer">
        <button
          className={`btn sidebar-settings-btn ${settingsOpen ? 'active' : ''}`}
          onClick={onToggleSettings}
          disabled={!selectedProjectId}
        >
          项目设置
        </button>
      </div>
    </aside>
  )
}
