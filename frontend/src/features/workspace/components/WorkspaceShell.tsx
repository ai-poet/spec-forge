import type { ReactNode } from 'react'
import { CreateEpicPanel } from '../../epics/components/CreateEpicPanel'
import { CreateIterationPanel } from '../../iteration/components/CreateIterationPanel'
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
  showCreateEpic: boolean
  showCreateIteration: boolean
  onCreateEpic: (input: { title: string; description: string; acceptance_criteria: string }) => Promise<void>
  onCreateIteration: (goal: string, mode: Mode | null) => Promise<void>
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
  showCreateEpic,
  showCreateIteration,
  onCreateEpic,
  onCreateIteration,
  goalPlaceholder,
  children,
}: Props) {
  if (!project) {
    return (
      <StageContent>
        <EmptyWorkspace variant="no-project" />
      </StageContent>
    )
  }

  if (showCreateEpic) {
    return (
      <StageContent>
        <CreateEpicPanel disabled={busy} onCreate={onCreateEpic} />
        <EpicList epics={epics} selectedEpicId={selectedEpicId} onSelectEpic={onSelectEpic} compact />
      </StageContent>
    )
  }

  if (!selectedEpicId) {
    return (
      <StageContent>
        <EmptyWorkspace variant="no-epic" projectName={project.name} />
        <EpicList epics={epics} selectedEpicId={selectedEpicId} onSelectEpic={onSelectEpic} compact />
      </StageContent>
    )
  }

  if (showCreateIteration) {
    return (
      <StageContent>
        <CreateIterationPanel disabled={busy} goalPlaceholder={goalPlaceholder} onCreate={onCreateIteration} />
        <IterationList iterations={iterations} selectedIterationId={selectedIterationId} onSelectIteration={onSelectIteration} compact />
      </StageContent>
    )
  }

  if (!selectedIterationId) {
    return (
      <StageContent>
        <EmptyWorkspace variant="no-iteration" projectName={project.name} epicTitle={epics.find((e) => e.id === selectedEpicId)?.title} />
        <IterationList iterations={iterations} selectedIterationId={selectedIterationId} onSelectIteration={onSelectIteration} compact />
      </StageContent>
    )
  }

  return <div className="workspace-flow">{children}</div>
}
