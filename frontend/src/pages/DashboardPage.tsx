import { useEffect, useMemo, useState } from 'react'
import { approveDesign, approveVerify, createIteration, listIterationsForEpic, stopIteration } from '../api'
import { ActionPanel } from '../components/ActionPanel'
import { CreateEpicPanel } from '../components/CreateEpicPanel'
import { CreateIterationPanel } from '../components/CreateIterationPanel'
import { EpicHeader } from '../components/EpicHeader'
import { EpicList } from '../components/EpicList'
import { IterationList } from '../components/IterationList'
import { PipelineBoard } from '../components/PipelineBoard'
import { ProjectConfigPanel } from '../components/ProjectConfigPanel'
import { ProjectSidebar } from '../components/ProjectSidebar'
import { WorkbenchPanel } from '../components/WorkbenchPanel'
import { useEpics } from '../hooks/useEpics'
import { useIterationLive } from '../hooks/useIterationLive'
import { useProjects } from '../hooks/useProjects'
import type { IterationSummary, Mode, UpdateProjectInput } from '../types'

type MainTab = 'iterations' | 'config'

export function DashboardPage() {
  const projects = useProjects()
  const epics = useEpics(projects.selectedProjectId)
  const [iterations, setIterations] = useState<IterationSummary[]>([])
  const [selectedIterationId, setSelectedIterationId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [mainTab, setMainTab] = useState<MainTab>('iterations')
  const live = useIterationLive(selectedIterationId)

  const defaultGoal = useMemo(() => {
    if (!epics.selectedEpic) return 'Build the first verified slice for this project'
    return [
      epics.selectedEpic.description,
      epics.selectedEpic.acceptance_criteria ? `Acceptance criteria:\n${epics.selectedEpic.acceptance_criteria}` : '',
    ].filter(Boolean).join('\n\n')
  }, [epics.selectedEpic])

  async function refreshIterations(preferredIterationId?: string) {
    const items = epics.selectedEpicId ? await listIterationsForEpic(epics.selectedEpicId) : []
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
  }, [projects.selectedProjectId, epics.selectedEpicId])

  useEffect(() => {
    const selected = iterations.find((item) => item.id === selectedIterationId)
    if (!selected || !live.detail || selected.id !== live.detail.id) return
    if (selected.status !== live.detail.status || selected.updated_at !== live.detail.updated_at) {
      live.loadDetail().catch(console.error)
    }
  }, [iterations, selectedIterationId, live.detail?.status, live.detail?.updated_at])

  useEffect(() => {
    if (!live.detail || live.detail.id !== selectedIterationId) return
    refreshIterations(selectedIterationId ?? undefined).catch(console.error)
    epics.refreshEpics(epics.selectedEpicId ?? undefined).catch(console.error)
    projects.refreshProjects().catch(console.error)
  }, [live.detail?.status])

  async function handleAddProject(name: string, description?: string) {
    await projects.addProject(name, description)
  }

  async function handleCreateEpic(input: { title: string; description: string; acceptance_criteria: string }) {
    setBusy(true)
    try {
      await epics.addEpic(input)
      await projects.refreshProjects()
    } finally {
      setBusy(false)
    }
  }

  async function handleCreateIteration(goal: string, mode: Mode | null) {
    if (!projects.selectedProjectId || !epics.selectedEpicId) return
    setBusy(true)
    try {
      const item = await createIteration({
        project_id: projects.selectedProjectId,
        epic_id: epics.selectedEpicId,
        goal,
        mode,
      })
      await projects.refreshProjects()
      await epics.refreshEpics(epics.selectedEpicId ?? undefined)
      await refreshIterations(item.id)
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
      await refreshIterations(selectedIterationId)
      await epics.refreshEpics(epics.selectedEpicId ?? undefined)
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
      await refreshIterations(selectedIterationId)
      await epics.refreshEpics(epics.selectedEpicId ?? undefined)
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
      await refreshIterations(selectedIterationId)
      await epics.refreshEpics(epics.selectedEpicId ?? undefined)
      await projects.refreshProjects()
    } finally {
      setBusy(false)
    }
  }

  async function handleSaveProject(projectId: string, input: UpdateProjectInput) {
    setBusy(true)
    try {
      await projects.saveProject(projectId, input)
      await refreshIterations(selectedIterationId ?? undefined)
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
      >
        <CreateEpicPanel disabled={!projects.selectedProjectId || busy} onCreate={handleCreateEpic} />
        <EpicList epics={epics.epics} selectedEpicId={epics.selectedEpicId} onSelectEpic={epics.setSelectedEpicId} />
      </ProjectSidebar>

      <main className="main stack">
        <EpicHeader
          project={projects.selectedProject}
          epic={epics.selectedEpic}
          connectionStatus={live.connectionStatus}
          lastMessageAt={live.lastMessageAt}
        />

        <div className="tabbar">
          <button className={`tab ${mainTab === 'iterations' ? 'active' : ''}`} onClick={() => setMainTab('iterations')}>
            Iterations
          </button>
          <button className={`tab ${mainTab === 'config' ? 'active' : ''}`} onClick={() => setMainTab('config')}>
            Config
          </button>
        </div>

        {mainTab === 'config' ? (
          <ProjectConfigPanel project={projects.selectedProject} busy={busy} onSave={handleSaveProject} />
        ) : (
          <div className="workbench-grid">
            <div className="stack">
              <CreateIterationPanel disabled={!projects.selectedProjectId || !epics.selectedEpicId || busy} defaultGoal={defaultGoal} onCreate={handleCreateIteration} />
              <IterationList iterations={iterations} selectedIterationId={selectedIterationId} onSelectIteration={setSelectedIterationId} />
            </div>

            <div className="stack">
              <ActionPanel
                detail={live.detail}
                busy={busy}
                onApproveDesign={handleApproveDesign}
                onApproveVerify={handleApproveVerify}
                onStop={handleStop}
              />
              <WorkbenchPanel detail={live.detail} docText={live.docText} onLoadDocument={live.loadDocument} />
              <PipelineBoard detail={live.detail} liveError={live.liveError} />
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
