import type { ReactNode } from 'react'
import { CreatePipelinePanel } from '../../pipeline/components/CreatePipelinePanel'
import { EmptyWorkspace } from './EmptyWorkspace'
import { EpicList } from '../../epics/components/EpicList'
import { IterationList } from '../../iteration/components/IterationList'
import type { EpicSummary, IterationSummary, Mode, ProjectSummary } from '../../../shared/lib/types'

interface Props {
  project: ProjectSummary | null
  epics: EpicSummary[]
  selectedEpicId: string | null
  onSelectEpic: (id: string) => void
  iterations: IterationSummary[]
  selectedIterationId: string | null
  onSelectIteration: (id: string) => void
  busy: boolean
  showCreatePipeline: boolean
  onStartPipeline: () => void
  onCreatePipeline: (input: { text: string; runMode: Mode | null; mode: 'new' | 'append' }) => Promise<void>
  goalPlaceholder?: string
  children: ReactNode
}

function StageContent({ children }: { children: ReactNode }) {
  return (
    <div className="workspace-stage">
      <div className="workspace-stage-inner stack">{children}</div>
    </div>
  )
}

export function WorkspaceShell({
  project,
  epics,
  selectedEpicId,
  onSelectEpic,
  iterations,
  selectedIterationId,
  onSelectIteration,
  busy,
  showCreatePipeline,
  onStartPipeline,
  onCreatePipeline,
  goalPlaceholder,
  children,
}: Props) {
  const selectedEpic = epics.find((epic) => epic.id === selectedEpicId) ?? null
  const pipelineMode = selectedEpicId ? 'append' : 'new'

  if (!project) {
    return (
      <StageContent>
        <EmptyWorkspace variant="no-project" />
      </StageContent>
    )
  }

  if (showCreatePipeline) {
    return (
      <StageContent>
        <CreatePipelinePanel
          mode={pipelineMode}
          epicTitle={selectedEpic?.title}
          goalPlaceholder={goalPlaceholder}
          disabled={busy}
          onCreate={(input) => onCreatePipeline({ ...input, mode: pipelineMode })}
        />
        {pipelineMode === 'new' ? (
          <EpicList epics={epics} selectedEpicId={selectedEpicId} onSelectEpic={onSelectEpic} compact />
        ) : (
          <IterationList iterations={iterations} selectedIterationId={selectedIterationId} onSelectIteration={onSelectIteration} compact />
        )}
      </StageContent>
    )
  }

  if (!selectedIterationId) {
    return (
      <StageContent>
        <EmptyWorkspace
          variant="ready"
          projectName={project.name}
          epicTitle={selectedEpic?.title}
          onStartPipeline={onStartPipeline}
        />
        {!selectedEpicId ? (
          <EpicList epics={epics} selectedEpicId={selectedEpicId} onSelectEpic={onSelectEpic} compact />
        ) : (
          <IterationList iterations={iterations} selectedIterationId={selectedIterationId} onSelectIteration={onSelectIteration} compact />
        )}
      </StageContent>
    )
  }

  return <div className="workspace-flow">{children}</div>
}
