import { useEffect, useState } from 'react'
import { approveDesign, approveVerify, createIteration, listIterationsForProject, stopIteration } from '../api'
import { CreateIterationPanel } from '../components/CreateIterationPanel'
import { DocumentPanel } from '../components/DocumentPanel'
import { IterationList } from '../components/IterationList'
import { PipelineBoard } from '../components/PipelineBoard'
import { ProjectConfigPanel } from '../components/ProjectConfigPanel'
import { ProjectSidebar } from '../components/ProjectSidebar'
import { RunLogPanel } from '../components/RunLogPanel'
import { TimelinePanel } from '../components/TimelinePanel'
import { useIterationLive } from '../hooks/useIterationLive'
import { useProjects } from '../hooks/useProjects'
import type { IterationSummary, Mode, UpdateProjectInput } from '../types'

export function DashboardPage() {
  const projects = useProjects()
  const [iterations, setIterations] = useState<IterationSummary[]>([])
  const [selectedIterationId, setSelectedIterationId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const live = useIterationLive(selectedIterationId)

  async function refreshIterations(projectId = projects.selectedProjectId, preferredIterationId?: string) {
    if (!projectId) {
      setIterations([])
      setSelectedIterationId(null)
      return
    }
    const items = await listIterationsForProject(projectId)
    setIterations(items)
    const nextSelection =
      preferredIterationId && items.some((item) => item.id === preferredIterationId)
        ? preferredIterationId
        : items[0]?.id ?? null
    setSelectedIterationId(nextSelection)
  }

  useEffect(() => {
    setSelectedIterationId(null)
    refreshIterations().catch(console.error)
  }, [projects.selectedProjectId])

  async function handleAddProject(name: string, description?: string) {
    await projects.addProject(name, description)
  }

  async function handleCreateIteration(goal: string, mode: Mode | null) {
    if (!projects.selectedProjectId) return
    setBusy(true)
    try {
      const item = await createIteration({
        project_id: projects.selectedProjectId,
        goal,
        mode,
      })
      await projects.refreshProjects()
      await refreshIterations(projects.selectedProjectId, item.id)
      setSelectedIterationId(item.id)
    } finally {
      setBusy(false)
    }
  }

  async function handleApproveDesign() {
    if (!selectedIterationId) return
    setBusy(true)
    try {
      await approveDesign(selectedIterationId)
      await live.loadDetail()
      await refreshIterations()
      await projects.refreshProjects()
    } finally {
      setBusy(false)
    }
  }

  async function handleApproveVerify() {
    if (!selectedIterationId) return
    setBusy(true)
    try {
      await approveVerify(selectedIterationId)
      await live.loadDetail()
      await refreshIterations()
      await projects.refreshProjects()
    } finally {
      setBusy(false)
    }
  }

  async function handleStop() {
    if (!selectedIterationId) return
    setBusy(true)
    try {
      await stopIteration(selectedIterationId, 'user stop')
      await live.loadDetail()
      await refreshIterations()
      await projects.refreshProjects()
    } finally {
      setBusy(false)
    }
  }

  async function handleSaveProject(projectId: string, input: UpdateProjectInput) {
    setBusy(true)
    try {
      await projects.saveProject(projectId, input)
      await refreshIterations(projectId, selectedIterationId ?? undefined)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="app">
      <ProjectSidebar
        projects={projects.projects}
        selectedProjectId={projects.selectedProjectId}
        onSelectProject={projects.setSelectedProjectId}
        onAddProject={handleAddProject}
      />

      <main className="main stack">
        <header className="workspace-header">
          <div>
            <p className="eyebrow">Project</p>
            <h1>{projects.selectedProject?.name ?? '请选择或添加项目'}</h1>
            <p className="muted">{projects.selectedProject?.description ?? '每个项目拥有独立流水线列表和 LangGraph 状态视图。'}</p>
          </div>
          <div className="status-card">
            <strong>{iterations.length}</strong>
            <span>iterations</span>
          </div>
        </header>

        <div className="work-grid">
          <div className="stack">
            <CreateIterationPanel disabled={!projects.selectedProjectId || busy} onCreate={handleCreateIteration} />
            <ProjectConfigPanel project={projects.selectedProject} busy={busy} onSave={handleSaveProject} />
            <IterationList iterations={iterations} selectedIterationId={selectedIterationId} onSelectIteration={setSelectedIterationId} />
          </div>

          <div className="stack">
            <PipelineBoard
              detail={live.detail}
              liveError={live.liveError}
              busy={busy}
              onApproveDesign={handleApproveDesign}
              onApproveVerify={handleApproveVerify}
              onStop={handleStop}
            />
            <div className="grid">
              <DocumentPanel detail={live.detail} docText={live.docText} onLoadDocument={live.loadDocument} />
              <TimelinePanel detail={live.detail} />
            </div>
            <RunLogPanel detail={live.detail} />
          </div>
        </div>
      </main>
    </div>
  )
}
