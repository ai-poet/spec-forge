import type { ProjectSummary } from '../../../shared/lib/types'
import { formatProjectPath } from '../lib/formatPath'
import { deriveProjectStatus } from '../lib/projectStatus'
import sidebar from '../../../shared/ui/sidebar.module.less'

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
    <aside className={`${sidebar.sidebar} ${sidebar.layout}`}>
      <div className={sidebar.top}>
        <div className={sidebar.brand}>
          <h1>SpecForge</h1>
        </div>

        <button type="button" className="btn btn-ghost" onClick={onOpenCreateModal}>
          + 打开 / 新建项目
        </button>

        <section>
          <h2 className={sidebar.sectionTitle}>项目</h2>
          <div className={sidebar.projectList}>
            {projects.map((project) => {
              const status = deriveProjectStatus(project)
              return (
                <button
                  key={project.id}
                  type="button"
                  className={`${sidebar.row} ${selectedProjectId === project.id ? sidebar.active : ''}`}
                  onClick={() => onSelectProject(project.id)}
                >
                  <div className={sidebar.rowHead}>
                    <strong>{project.name}</strong>
                    <span className={`${sidebar.status} ${sidebar[status.kind]}`}>
                      {status.kind === 'running' ? <span className={sidebar.statusDot} aria-hidden="true" /> : null}
                      {status.label}
                    </span>
                  </div>
                  <span className={sidebar.projectPath}>{formatProjectPath(project.root_path)}</span>
                  {status.detail ? <span className={sidebar.rowMeta}>{status.detail}</span> : null}
                </button>
              )
            })}
            {!projects.length ? <div className={`empty ${sidebar.empty}`}>暂无项目</div> : null}
          </div>
        </section>
      </div>

      <div className={sidebar.footer}>
        <button
          type="button"
          className={`${sidebar.link} ${settingsOpen ? sidebar.active : ''}`}
          onClick={onToggleSettings}
          disabled={!selectedProjectId}
        >
          目录 · 设置 · 移除
        </button>
      </div>
    </aside>
  )
}
