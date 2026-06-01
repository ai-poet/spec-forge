import { useEffect, useState } from 'react'
import { approveVerify, createIteration, listIterationsForProject, resumeIteration, stopIteration } from '../shared/lib/api'
import { parseEpicDraft } from '../features/epics/lib/parseEpicDraft'
import { ProjectConfigPanel } from '../features/projects/ProjectConfigPanel'
import { CreateProjectModal } from '../features/projects/CreateProjectModal'
import { ProjectSidebar } from '../features/projects/ProjectSidebar'
import { useEpics } from '../features/epics/hooks/useEpics'
import { EpicPipelineSidebar } from '../features/pipeline/EpicPipelineSidebar'
import { iterationForEpic } from '../features/pipeline/lib/epicPipeline'
import { PipelineRail } from '../features/pipeline/PipelineRail'
import { StageFocusPanel } from '../features/pipeline/StageFocusPanel'
import type { PipelineStepKey } from '../features/pipeline/lib/pipelineSteps'
import { useIterationLive } from '../features/iteration/hooks/useIterationLive'
import { useProjects } from '../features/projects/hooks/useProjects'
import { ContextHeader } from '../features/workspace/ContextHeader'
import { WorkspaceShell } from '../features/workspace/WorkspaceShell'
import type { CreateProjectInput, IterationSummary, UpdateProjectInput } from '../shared/lib/types'

function buildIterationGoal(title: string, description: string, acceptanceCriteria: string) {
  return [description, acceptanceCriteria ? `验收标准:\n${acceptanceCriteria}` : ''].filter(Boolean).join('\n\n') || title
}

export function DashboardPage() {
  const projects = useProjects()
  const epics = useEpics(projects.selectedProjectId)
  const [iterations, setIterations] = useState<IterationSummary[]>([])
  const [selectedIterationId, setSelectedIterationId] = useState<string | null>(null)
  const [reviewStepKey, setReviewStepKey] = useState<PipelineStepKey | null>(null)
  const [busy, setBusy] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [showCreatePipeline, setShowCreatePipeline] = useState(false)
  const [createProjectOpen, setCreateProjectOpen] = useState(false)
  const live = useIterationLive(selectedIterationId)

  async function refreshIterations(preferredEpicId?: string, preferredIterationId?: string) {
    if (!projects.selectedProjectId) {
      setIterations([])
      setSelectedIterationId(null)
      return
    }
    const items = await listIterationsForProject(projects.selectedProjectId)
    setIterations(items)

    const epicId = preferredEpicId ?? epics.selectedEpicId
    if (preferredIterationId && items.some((item) => item.id === preferredIterationId)) {
      setSelectedIterationId(preferredIterationId)
      const iteration = items.find((item) => item.id === preferredIterationId)
      if (iteration?.epic_id) epics.setSelectedEpicId(iteration.epic_id)
      return
    }
    if (epicId) {
      const iteration = iterationForEpic(items, epicId)
      setSelectedIterationId(iteration?.id ?? null)
    }
  }

  useEffect(() => {
    epics.setSelectedEpicId(null)
    setSelectedIterationId(null)
    setReviewStepKey(null)
    setShowCreatePipeline(false)
    refreshIterations().catch(console.error)
  }, [projects.selectedProjectId])

  useEffect(() => {
    setReviewStepKey(null)
    setShowCreatePipeline(false)
    setSettingsOpen(false)
  }, [projects.selectedProjectId])

  useEffect(() => {
    if (!epics.selectedEpicId) {
      setSelectedIterationId(null)
      return
    }
    const iteration = iterationForEpic(iterations, epics.selectedEpicId)
    setSelectedIterationId(iteration?.id ?? null)
    setReviewStepKey(null)
    setShowCreatePipeline(false)
  }, [epics.selectedEpicId, iterations])

  useEffect(() => {
    const selected = iterations.find((item) => item.id === selectedIterationId)
    if (!selected || !live.detail || selected.id !== live.detail.id) return
    if (selected.status !== live.detail.status || selected.updated_at !== live.detail.updated_at) {
      live.loadDetail().catch(console.error)
    }
  }, [iterations, selectedIterationId, live.detail?.status, live.detail?.updated_at])

  useEffect(() => {
    if (!live.detail || live.detail.id !== selectedIterationId) return
    refreshIterations(epics.selectedEpicId ?? undefined, selectedIterationId ?? undefined).catch(console.error)
    epics.refreshEpics(epics.selectedEpicId ?? undefined).catch(console.error)
    projects.refreshProjects().catch(console.error)
  }, [live.detail?.status])

  async function handleAddProject(input: CreateProjectInput) {
    await projects.addProject(input)
  }

  async function handleCreatePipeline(input: { text: string }) {
    if (!projects.selectedProjectId) return
    setBusy(true)
    try {
      const parsed = parseEpicDraft(input.text)
      if (!parsed) return
      const epic = await epics.addEpic(parsed)
      if (!epic) return
      const goal = buildIterationGoal(parsed.title, parsed.description, parsed.acceptance_criteria)
      const item = await createIteration({
        project_id: projects.selectedProjectId,
        epic_id: epic.id,
        goal,
        mode: 'real-cli',
      })
      epics.setSelectedEpicId(epic.id)
      await projects.refreshProjects()
      await epics.refreshEpics(epic.id)
      await refreshIterations(epic.id, item.id)
      setShowCreatePipeline(false)
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
      await refreshIterations(epics.selectedEpicId ?? undefined, selectedIterationId)
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
      await refreshIterations(epics.selectedEpicId ?? undefined, selectedIterationId)
      await epics.refreshEpics(epics.selectedEpicId ?? undefined)
      await projects.refreshProjects()
    } finally {
      setBusy(false)
    }
  }

  async function handleResume() {
    if (!selectedIterationId) return
    setBusy(true)
    try {
      await resumeIteration(selectedIterationId, '用户恢复')
      await live.loadDetail()
      await refreshIterations(epics.selectedEpicId ?? undefined, selectedIterationId)
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
      await refreshIterations(epics.selectedEpicId ?? undefined, selectedIterationId ?? undefined)
    } finally {
      setBusy(false)
    }
  }

  async function handleBindFolder(projectId: string, rootPath: string, createIfMissing: boolean) {
    setBusy(true)
    try {
      await projects.saveProject(projectId, { root_path: rootPath, create_if_missing: createIfMissing })
      await projects.refreshProjects()
    } finally {
      setBusy(false)
    }
  }

  async function handleDeleteProject(projectId: string) {
    setBusy(true)
    try {
      await projects.removeProject(projectId)
      setSettingsOpen(false)
      setSelectedIterationId(null)
      epics.setSelectedEpicId(null)
    } finally {
      setBusy(false)
    }
  }

  async function handleDeletePipeline(epicId: string) {
    setBusy(true)
    try {
      await epics.removeEpic(epicId)
      if (epics.selectedEpicId === epicId) {
        setSelectedIterationId(null)
        setReviewStepKey(null)
      }
      await refreshIterations()
      await projects.refreshProjects()
    } finally {
      setBusy(false)
    }
  }

  function handleSelectProject(id: string) {
    projects.setSelectedProjectId(id)
    setSettingsOpen(false)
  }

  function handleSelectPipeline(epicId: string) {
    epics.setSelectedEpicId(epicId)
    setShowCreatePipeline(false)
  }

  const showRail = Boolean(selectedIterationId && !settingsOpen)
  const hasEpicColumn = Boolean(projects.selectedProject)
  const selectedIteration = iterations.find((item) => item.id === selectedIterationId) ?? null

  return (
    <div className={`app ${hasEpicColumn ? 'with-epic-sidebar' : ''} ${showRail ? '' : 'no-rail'}`}>
      <ProjectSidebar
        projects={projects.projects}
        selectedProjectId={projects.selectedProjectId}
        onSelectProject={handleSelectProject}
        onOpenCreateModal={() => setCreateProjectOpen(true)}
        settingsOpen={settingsOpen}
        onToggleSettings={() => setSettingsOpen((value) => !value)}
      />

      <CreateProjectModal
        open={createProjectOpen}
        onClose={() => setCreateProjectOpen(false)}
        onCreate={handleAddProject}
      />

      {projects.selectedProject ? (
        <EpicPipelineSidebar
          epics={epics.epics}
          selectedEpicId={epics.selectedEpicId}
          iterations={iterations}
          onSelectPipeline={handleSelectPipeline}
          onDeletePipeline={handleDeletePipeline}
          onCreatePipeline={() => setShowCreatePipeline(true)}
        />
      ) : null}

      <main className="main workspace-main">
        {settingsOpen && projects.selectedProject ? (
          <div className="workspace-scroll">
            <div className="settings-view stack">
              <div className="section-row">
                <div>
                  <p className="eyebrow">项目设置</p>
                  <h1 className="workspace-title">{projects.selectedProject.name}</h1>
                  <p className="muted project-path-inline">{projects.selectedProject.root_path ?? '未绑定目录'}</p>
                </div>
                <button type="button" className="btn btn-ghost" onClick={() => setSettingsOpen(false)}>
                  返回工作台
                </button>
              </div>
              <ProjectConfigPanel
                project={projects.selectedProject}
                busy={busy}
                onSave={handleSaveProject}
                onBindFolder={handleBindFolder}
                onDelete={handleDeleteProject}
              />
            </div>
          </div>
        ) : (
          <>
            {projects.selectedProject ? (
              <ContextHeader
                project={projects.selectedProject}
                selectedEpic={epics.selectedEpic}
                selectedIteration={selectedIteration}
                liveDetail={live.detail}
                isLoading={live.isLoading}
                onCreatePipeline={() => setShowCreatePipeline(true)}
                onOpenSettings={() => setSettingsOpen(true)}
              />
            ) : null}

            <div className={`workspace-body ${!selectedIterationId ? 'workspace-body-stage' : ''}`}>
              <WorkspaceShell
                project={projects.selectedProject}
                epics={epics.epics}
                selectedEpicId={epics.selectedEpicId}
                selectedIterationId={selectedIterationId}
                busy={busy}
                showCreatePipeline={showCreatePipeline}
                onStartPipeline={() => setShowCreatePipeline(true)}
                onCreatePipeline={handleCreatePipeline}
              >
                <StageFocusPanel
                  detail={live.detail}
                  docText={live.docText}
                  reviewStepKey={reviewStepKey}
                  onSelectStep={setReviewStepKey}
                  isLoading={live.isLoading}
                  busy={busy}
                  onLoadDocument={live.loadDocument}
                  onApproveVerify={handleApproveVerify}
                  onStop={handleStop}
                  onResume={handleResume}
                  onRuntimeNoteSubmitted={() => live.loadDetail().catch(console.error)}
                />
              </WorkspaceShell>
            </div>
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
