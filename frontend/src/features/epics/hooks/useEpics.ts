import { useCallback, useEffect, useState } from 'react'
import { createEpic, listEpicsForProject, updateEpic } from '../api'
import type { CreateEpicInput, EpicSummary, UpdateEpicInput } from '../types'

export function useEpics(projectId: string | null) {
  const [epics, setEpics] = useState<EpicSummary[]>([])
  const [selectedEpicId, setSelectedEpicId] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const refreshEpics = useCallback(
    async (preferredEpicId?: string) => {
      if (!projectId) {
        setEpics([])
        setSelectedEpicId(null)
        return
      }
      setLoading(true)
      try {
        const items = await listEpicsForProject(projectId)
        setEpics(items)
        setSelectedEpicId((current) => {
          if (preferredEpicId && items.some((item) => item.id === preferredEpicId)) return preferredEpicId
          if (current && items.some((item) => item.id === current)) return current
          return null
        })
      } finally {
        setLoading(false)
      }
    },
    [projectId],
  )

  const addEpic = useCallback(
    async (input: Omit<CreateEpicInput, 'project_id'>) => {
      if (!projectId) return null
      const epic = await createEpic({ ...input, project_id: projectId })
      await refreshEpics(epic.id)
      return epic
    },
    [projectId, refreshEpics],
  )

  const saveEpic = useCallback(
    async (epicId: string, input: UpdateEpicInput) => {
      const epic = await updateEpic(epicId, input)
      await refreshEpics(epic.id)
      return epic
    },
    [refreshEpics],
  )

  useEffect(() => {
    refreshEpics().catch(console.error)
  }, [refreshEpics])

  return {
    epics,
    selectedEpicId,
    selectedEpic: epics.find((epic) => epic.id === selectedEpicId) ?? null,
    loading,
    setSelectedEpicId,
    refreshEpics,
    addEpic,
    saveEpic,
  }
}
