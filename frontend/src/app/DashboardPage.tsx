import { useEffect, useState } from 'react'
import {
  answerRequirements,
  approveVerify,
  createIteration,
  listIterationsForProject,
  manualSkipIteration,
  resumeIteration,
  skipDiscovery,
  stopIteration,
} from '../shared/lib/api'
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
import { TaskLogSummaryPanel } from '../features/iteration/RunLogPanel'
import { useProjects } from '../features/projects/hooks/useProjects'
import { ContextHeader } from '../features/workspace/ContextHeader'
import { WorkspaceShell } from '../features/workspace/WorkspaceShell'
import type { CreateProjectInput, IterationSummary, UpdateProjectInput } from '../shared/lib/types'

const SELECTED_ITERATION_KEY = 'specforge:selected-iteration'

type WorkspaceTaskView = 'stage' | 'log_summary'

function buildIterationGoal(title: string, description: string, acceptanceCriteria: string) {
  return [description, acceptanceCriteria ? `验收标准:\n${acceptanceCriteria}` : ''].filter(Boolean).join('\n\n') || title
}

function readStoredIterationId() {
  return window.localStorage.getItem(SELECTED_ITERATION_KEY)
}

function rememberIterationId(iterationId: string | null) {
  if (iterationId) {
    window.localStorage.setItem(SELECTED_ITERATION_KEY, iterationId)
  } else {
    window.localStorage.removeItem(SELECTED_ITERATION_KEY)
  }
}

function preferredIteration(items: IterationSummary[]) {
  return items.find((item) => !['delivered', 'blocked', 'stopped', 'failed'].includes(item.status)) ?? items[0] ?? null
}

export function DashboardPage() {
  const projects = useProjects()
  const epics = useEpics(projects.selectedProjectId)
  const [iterations, setIterations] = useState<IterationSummary[]>([])
  const [selectedIterationId, setSelectedIterationId] = useState<string | null>(() => readStoredIterationId())
  const [reviewStepKey, setReviewStepKey] = useState<PipelineStepKey | null>(null)
  const [busy, setBusy] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [showCreatePipeline, setShowCreatePipeline] = useState(false)
  const [createProjectOpen, setCreateProjectOpen] = useState(false)
  const [taskView, setTaskView] = useState<WorkspaceTaskView>('stage')
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
      return
    }
    const currentItem = selectedIterationId ? items.find((item) => item.id === selectedIterationId) : null
    const stored = readStoredIterationId()
    const storedItem = stored ? items.find((item) => item.id === stored) : null
    const nextIteration = currentItem ?? storedItem ?? preferredIteration(items)
    setSelectedIterationId(nextIteration?.id ?? null)
    if (nextIteration?.epic_id && !epics.selectedEpicId) {
      epics.setSelectedEpicId(nextIteration.epic_id)
    }
  }

  useEffect(() => {
    setReviewStepKey(null)
    setShowCreatePipeline(false)
    setTaskView('stage')
    refreshIterations().catch(console.error)
  }, [projects.selectedProjectId])

  useEffect(() => {
    setReviewStepKey(null)
    setShowCreatePipeline(false)
    setSettingsOpen(false)
    setTaskView('stage')
  }, [projects.selectedProjectId])

  useEffect(() => {
    if (!epics.selectedEpicId) {
      return
    }
    const iteration = iterationForEpic(iterations, epics.selectedEpicId)
    setSelectedIterationId(iteration?.id ?? null)
    setReviewStepKey(null)
    setShowCreatePipeline(false)
    setTaskView('stage')
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

  useEffect(() => {
    rememberIterationId(selectedIterationId)
    setTaskView('stage')
  }, [selectedIterationId])

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

  async function handleAnswerRequirements(answer: string) {
    if (!selectedIterationId) return
    setBusy(true)
    try {
      await answerRequirements(selectedIterationId, answer)
      await live.loadDetail()
      await refreshIterations(epics.selectedEpicId ?? undefined, selectedIterationId)
    } finally {
      setBusy(false)
    }
  }

  async function handleSkipDiscovery() {
    if (!selectedIterationId) return
    setBusy(true)
    try {
      await skipDiscovery(selectedIterationId, '按当前假设继续')
      await live.loadDetail()
      await refreshIterations(epics.selectedEpicId ?? undefined, selectedIterationId)
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

  async function handleResume(note?: string) {
    if (!selectedIterationId) return
    setBusy(true)
    try {
      await resumeIteration(selectedIterationId, note?.trim() || '用户恢复')
      await live.loadDetail()
      await refreshIterations(epics.selectedEpicId ?? undefined, selectedIterationId)
      await epics.refreshEpics(epics.selectedEpicId ?? undefined)
      await projects.refreshProjects()
    } finally {
      setBusy(false)
    }
  }

  async function handleManualSkip(node?: string | null) {
    if (!selectedIterationId) return
    setBusy(true)
    try {
      await manualSkipIteration(selectedIterationId, node, '人工调试跳过')
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
    setTaskView('stage')
  }

  function handleSelectPipeline(epicId: string) {
    epics.setSelectedEpicId(epicId)
    setShowCreatePipeline(false)
    setTaskView('stage')
  }

  const showTaskTabs = Boolean(selectedIterationId && !settingsOpen && !showCreatePipeline && projects.selectedProject)
  const showRail = Boolean(selectedIterationId && !settingsOpen && !showCreatePipeline && taskView === 'stage')
  const hasEpicColumn = Boolean(projects.selectedProject)
  const selectedIteration = iterations.find((item) => item.id === selectedIterationId) ?? null

  return (
    <div className={`app ${hasEpicColumn ? 'with-epic-sidebar' : ''}`}>
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

            {showTaskTabs ? (
              <div className="task-view-nav" role="tablist" aria-label="任务视图">
                <button
                  type="button"
                  role="tab"
                  aria-selected={taskView === 'stage'}
                  className={`task-view-tab ${taskView === 'stage' ? 'task-view-tab-active' : ''}`}
                  onClick={() => setTaskView('stage')}
                >
                  阶段执行
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={taskView === 'log_summary'}
                  className={`task-view-tab ${taskView === 'log_summary' ? 'task-view-tab-active' : ''}`}
                  onClick={() => {
                    setReviewStepKey(null)
                    setTaskView('log_summary')
                  }}
                >
                  日志总结
                </button>
              </div>
            ) : null}

            <div className={`task-workspace ${showRail ? 'task-workspace-with-rail' : ''}`}>
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
                  {taskView === 'log_summary' ? (
                    <div className="task-log-summary-view stack">
                      <div>
                        <p className="eyebrow">任务级日志</p>
                        <h2 className="section-title">日志总结</h2>
                        <p className="muted">全局汇总本任务所有阶段、run、事件、文档与验收点；可从阶段行进入对应 run 原始日志。</p>
                      </div>
                      <TaskLogSummaryPanel detail={live.detail} />
                    </div>
                  ) : (
                    <StageFocusPanel
                      detail={live.detail}
                      docText={live.docText}
                      reviewStepKey={reviewStepKey}
                      onSelectStep={setReviewStepKey}
                      isLoading={live.isLoading}
                      busy={busy}
                      onLoadDocument={live.loadDocument}
                      onAnswerRequirements={handleAnswerRequirements}
                      onSkipDiscovery={handleSkipDiscovery}
                      onApproveVerify={handleApproveVerify}
                      onStop={handleStop}
                      onResume={handleResume}
                      onManualSkip={handleManualSkip}
                      onRuntimeNoteSubmitted={() => live.loadDetail().catch(console.error)}
                    />
                  )}
                </WorkspaceShell>
              </div>
              {showRail ? (
                <PipelineRail
                  detail={live.detail}
                  epic={epics.selectedEpic}
                  liveError={live.liveError}
                  connectionStatus={live.connectionStatus}
                  lastMessageAt={live.lastMessageAt}
                  reviewStepKey={reviewStepKey}
                  onSelectStep={setReviewStepKey}
                  onManualSkip={handleManualSkip}
                  manualSkipBusy={busy}
                />
              ) : null}
            </div>
          </>
        )}
      </main>
    </div>
  )
}
