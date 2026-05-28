import type { ReactNode } from 'react'
import { useState } from 'react'
import type { ProjectSummary } from '../types'

interface Props {
  projects: ProjectSummary[]
  selectedProjectId: string | null
  onSelectProject: (id: string) => void
  onAddProject: (name: string, description?: string) => Promise<void>
  children?: ReactNode
}

export function ProjectSidebar({ projects, selectedProjectId, onSelectProject, onAddProject, children }: Props) {
  const [name, setName] = useState('specforge-demo')
  const [description, setDescription] = useState('本地 agent 流水线')
  const [busy, setBusy] = useState(false)

  async function handleAdd() {
    if (!name.trim()) return
    setBusy(true)
    try {
      await onAddProject(name.trim(), description.trim() || undefined)
      setName('')
      setDescription('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <aside className="sidebar stack">
      <div className="brand">
        <h1>SpecForge</h1>
        <p>项目级 agent pipeline 控制台</p>
      </div>

      <section className="panel stack">
        <h2 className="section-title">添加项目</h2>
        <div className="form compact">
          <input value={name} onChange={(event) => setName(event.target.value)} placeholder="项目名称" />
          <input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="描述" />
          <button className="btn primary" onClick={handleAdd} disabled={busy || !name.trim()}>
            添加项目
          </button>
        </div>
      </section>

      <section className="panel stack">
        <h2 className="section-title">项目</h2>
        <div className="list">
          {projects.map((project) => (
            <button
              key={project.id}
              className={`item project-item ${selectedProjectId === project.id ? 'active' : ''}`}
              onClick={() => onSelectProject(project.id)}
            >
              <strong>{project.name}</strong>
              <span>{project.iteration_count} 条流水线</span>
              <small>{project.active_count} 进行中 / {project.delivered_count} 已交付</small>
            </button>
          ))}
          {!projects.length ? <div className="empty">暂无项目</div> : null}
        </div>
      </section>
      {children}
    </aside>
  )
}
