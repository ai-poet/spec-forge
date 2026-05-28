import { useEffect, useMemo, useState } from 'react'
import { approveDesign, approveVerify, createIteration, listIterationsForEpic, stopIteration } from '../shared/lib/api'
import { ProjectConfigPanel } from '../features/projects/components/ProjectConfigPanel'
import { ProjectSidebar } from '../features/projects/components/ProjectSidebar'
import { useEpics } from '../features/epics/hooks/useEpics'
import { PipelineRail } from '../features/pipeline/components/PipelineRail'
import { StageFocusPanel } from '../features/pipeline/components/StageFocusPanel'
import type { PipelineStepKey } from '../features/pipeline/lib/pipelineSteps'
import { useIterationLive } from '../features/iteration/hooks/useIterationLive'
import { useProjects } from '../features/projects/hooks/useProjects'
import { ContextHeader } from '../features/workspace/components/ContextHeader'
import { WorkspaceShell } from '../features/workspace/components/WorkspaceShell'
import type { CreateProjectInput, IterationSummary, Mode, UpdateProjectInput } from '../shared/lib/types'

export function DashboardPage() {
  const projects = useProjects()
  const epics = useEpics(projects.selectedProjectId)
  const [iterations, setIterations] = useState<IterationSummary[]>([])
  const [selectedIterationId, setSelectedIterationId] = useState<string | null>(null)
  const [reviewStepKey, setReviewStepKey] = useState<PipelineStepKey | null>(null)
  const [busy, setBusy] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [showCreateEpic, setShowCreateEpic] = useState(false)
  const [showCreateIteration, setShowCreateIteration] = useState(false)
  const live = useIterationLive(selectedIterationId)

  const goalPlaceholder = useMemo(() => {
    if (!epics.selectedEpic) return undefined
    return [
      epics.selectedEpic.description,
      epics.selectedEpic.acceptance_criteria ? `验收标准:\n${epics.selectedEpic.acceptance_criteria}` : '',
    ]
      .filter(Boolean)
      .join('\n\n')
  }, [epics.selectedEpic])

  async function refreshIterations(preferredIterationId?: string) {
    const items = epics.selectedEpicId ? await listIterationsForEpic(epics.selectedEpicId) : []
    setIterations(items)
    setSelectedIterationId((current) => {
      if (preferredIterationId && items.some((item) => item.id === preferredIterationId)) return preferredIterationId
      if (current && items.some((item) => item.id === current)) return current
      return null
    })
  }

  useEffect(() => {
    setSelectedIterationId(null)
    setReviewStepKey(null)
    setShowCreateIteration(false)
    refreshIterations().catch(console.error)
  }, [projects.selectedProjectId, epics.selectedEpicId])

  useEffect(() => {
    setReviewStepKey(null)
    setShowCreateEpic(false)
    setShowCreateIteration(false)
    setSettingsOpen(false)
  }, [projects.selectedProjectId])

  useEffect(() => {
    setReviewStepKey(null)
    setShowCreateIteration(false)
  }, [epics.selectedEpicId, selectedIterationId])

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

  async function handleAddProject(input: CreateProjectInput) {
    await projects.addProject(input)
  }

  async function handleCreateEpic(input: { title: string; description: string; acceptance_criteria: string }) {
    setBusy(true)
    try {
      const epic = await epics.addEpic(input)
      if (epic) epics.setSelectedEpicId(epic.id)
      setShowCreateEpic(false)
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
      setShowCreateIteration(false)
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
      await stopIteration(selectedIterationId, '用户停止')
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

  function handleSelectProject(id: string) {
    projects.setSelectedProjectId(id)
    setSettingsOpen(false)
  }

  function handleSelectEpic(id: string | null) {
    epics.setSelectedEpicId(id)
    setShowCreateEpic(false)
  }

  function handleSelectIteration(id: string | null) {
    setSelectedIterationId(id)
    setShowCreateIteration(false)
  }

  const showRail = Boolean(selectedIterationId && !settingsOpen)

  return (
    <div className={`app ${showRail ? '' : 'no-rail'}`}>
      <ProjectSidebar
        projects={projects.projects}
        selectedProjectId={projects.selectedProjectId}
        onSelectProject={handleSelectProject}
        onAddProject={handleAddProject}
        settingsOpen={settingsOpen}
        onToggleSettings={() => setSettingsOpen((value) => !value)}
      />

      <main className="main workspace-main stack">
        {settingsOpen && projects.selectedProject ? (
          <div className="stack">
            <div className="section-row">
              <div>
                <p className="eyebrow">项目设置</p>
                <h1 className="workspace-title">{projects.selectedProject.name}</h1>
                <p className="muted project-path-inline">{projects.selectedProject.root_path ?? '未绑定目录'}</p>
              </div>
              <button className="btn" onClick={() => setSettingsOpen(false)}>
                返回工作台
              </button>
            </div>
            <ProjectConfigPanel project={projects.selectedProject} busy={busy} onSave={handleSaveProject} />
          </div>
        ) : (
          <>
            {projects.selectedProject ? (
              <ContextHeader
                project={projects.selectedProject}
                epics={epics.epics}
                selectedEpicId={epics.selectedEpicId}
                onSelectEpic={handleSelectEpic}
                iterations={iterations}
                selectedIterationId={selectedIterationId}
                onSelectIteration={handleSelectIteration}
                onCreateEpic={() => {
                  setShowCreateEpic(true)
                  setShowCreateIteration(false)
                }}
                onCreateIteration={() => {
                  setShowCreateIteration(true)
                  setShowCreateEpic(false)
                }}
              />
            ) : null}

            <WorkspaceShell
              project={projects.selectedProject}
              epics={epics.epics}
              selectedEpicId={epics.selectedEpicId}
              onSelectEpic={epics.setSelectedEpicId}
              iterations={iterations}
              selectedIterationId={selectedIterationId}
              onSelectIteration={setSelectedIterationId}
              busy={busy}
              showCreateEpic={showCreateEpic}
              showCreateIteration={showCreateIteration}
              onCreateEpic={handleCreateEpic}
              onCreateIteration={handleCreateIteration}
              goalPlaceholder={goalPlaceholder}
            >
              <StageFocusPanel
                detail={live.detail}
                docText={live.docText}
                reviewStepKey={reviewStepKey}
                busy={busy}
                onLoadDocument={live.loadDocument}
                onApproveDesign={handleApproveDesign}
                onApproveVerify={handleApproveVerify}
                onStop={handleStop}
              />
            </WorkspaceShell>
          </>
        )}
      </main>

      {showRail ? (
        <PipelineRail
          detail={live.detail}
          epic={epics.selectedEpic}
          liveError={live.liveError}
          connectionStatus={live.connectionStatus}
          lastMessageAt={live.lastMessageAt}
          reviewStepKey={reviewStepKey}
          onSelectStep={setReviewStepKey}
        />
      ) : null}
    </div>
  )
}
