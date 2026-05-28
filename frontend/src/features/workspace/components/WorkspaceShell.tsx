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
  onCreatePipeline: (input: { text: string }) => Promise<void>
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
  children,
}: Props) {
  const selectedEpic = epics.find((epic) => epic.id === selectedEpicId) ?? null

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
        <CreatePipelinePanel disabled={busy} onCreate={onCreatePipeline} />
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
