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
    return <EmptyWorkspace variant="no-project" />
  }

  if (showCreateEpic) {
    return (
      <div className="workspace-setup stack">
        <EmptyWorkspace variant="no-epic" projectName={project.name} />
        <EpicList epics={epics} selectedEpicId={selectedEpicId} onSelectEpic={onSelectEpic} />
        <CreateEpicPanel disabled={busy} onCreate={onCreateEpic} />
      </div>
    )
  }

  if (!selectedEpicId) {
    return (
      <div className="workspace-setup stack">
        <EmptyWorkspace variant="no-epic" projectName={project.name} />
        <EpicList epics={epics} selectedEpicId={selectedEpicId} onSelectEpic={onSelectEpic} />
      </div>
    )
  }

  if (showCreateIteration) {
    return (
      <div className="workspace-setup stack">
        <EmptyWorkspace variant="no-iteration" projectName={project.name} epicTitle={epics.find((e) => e.id === selectedEpicId)?.title} />
        <IterationList iterations={iterations} selectedIterationId={selectedIterationId} onSelectIteration={onSelectIteration} />
        <CreateIterationPanel disabled={busy} goalPlaceholder={goalPlaceholder} onCreate={onCreateIteration} />
      </div>
    )
  }

  if (!selectedIterationId) {
    return (
      <div className="workspace-setup stack">
        <EmptyWorkspace variant="no-iteration" projectName={project.name} epicTitle={epics.find((e) => e.id === selectedEpicId)?.title} />
        <IterationList iterations={iterations} selectedIterationId={selectedIterationId} onSelectIteration={onSelectIteration} />
      </div>
    )
  }

  return <>{children}</>
}
