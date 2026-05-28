import type { CreateProjectInput, ProjectSummary } from '../../../shared/lib/types'
import { formatProjectPath } from '../lib/formatPath'

interface Props {
  projects: ProjectSummary[]
  selectedProjectId: string | null
  onSelectProject: (id: string) => void
  onOpenCreateModal: () => void
  settingsOpen: boolean
  onToggleSettings: () => void
}

export function ProjectSidebar({
  projects,
  selectedProjectId,
  onSelectProject,
  onOpenCreateModal,
  settingsOpen,
  onToggleSettings,
}: Props) {
  return (
    <aside className="sidebar sidebar-layout">
      <div className="sidebar-top">
        <div className="brand compact-brand">
          <h1>SpecForge</h1>
        </div>

        <button type="button" className="btn btn-ghost sidebar-new-btn" onClick={onOpenCreateModal}>
          + 打开 / 新建项目
        </button>

        <section className="sidebar-projects">
          <h2 className="sidebar-section-title">项目</h2>
          <div className="sidebar-project-list">
            {projects.map((project) => (
              <button
                key={project.id}
                type="button"
                className={`sidebar-row ${selectedProjectId === project.id ? 'active' : ''}`}
                onClick={() => onSelectProject(project.id)}
              >
                <strong>{project.name}</strong>
                <span className="project-path">{formatProjectPath(project.root_path)}</span>
              </button>
            ))}
            {!projects.length ? <div className="empty sidebar-empty">暂无项目</div> : null}
          </div>
        </section>
      </div>

      <div className="sidebar-footer">
        <button
          type="button"
          className={`sidebar-link ${settingsOpen ? 'active' : ''}`}
          onClick={onToggleSettings}
          disabled={!selectedProjectId}
        >
          项目设置
        </button>
      </div>
    </aside>
  )
}
