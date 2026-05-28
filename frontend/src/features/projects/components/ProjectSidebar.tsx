import { useState } from 'react'
import type { CreateProjectInput, ProjectSummary } from '../../../shared/lib/types'
import { formatProjectPath } from '../lib/formatPath'
import { CreateProjectDialog } from './CreateProjectDialog'

interface Props {
  projects: ProjectSummary[]
  selectedProjectId: string | null
  onSelectProject: (id: string) => void
  onAddProject: (input: CreateProjectInput) => Promise<void>
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
  const [showCreateForm, setShowCreateForm] = useState(false)

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
          <CreateProjectDialog
            onCreate={async (input) => {
              await onAddProject(input)
              setShowCreateForm(false)
            }}
          />
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
                <span className="project-path">{formatProjectPath(project.root_path)}</span>
                <small>
                  {project.iteration_count} 条流水线 · {project.active_count} 进行中 / {project.delivered_count} 已交付
                </small>
              </button>
            ))}
            {!projects.length ? <div className="empty">暂无项目，绑定一个文件夹开始</div> : null}
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
