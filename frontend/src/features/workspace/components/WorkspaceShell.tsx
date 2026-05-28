import type { ReactNode } from 'react'
import { CreatePipelinePanel } from '../../pipeline/components/CreatePipelinePanel'
import { EmptyWorkspace } from './EmptyWorkspace'
import type { EpicSummary, ProjectSummary } from '../../../shared/lib/types'

interface Props {
  project: ProjectSummary | null
  selectedEpicId: string | null
  epics: EpicSummary[]
  selectedIterationId: string | null
  busy: boolean
  showCreatePipeline: boolean
  onStartPipeline: () => void
  onCreatePipeline: (input: { text: string; mode: 'new' | 'append' }) => Promise<void>
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
  selectedEpicId,
  epics,
  selectedIterationId,
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
      </StageContent>
    )
  }

  return <div className="workspace-flow">{children}</div>
}
