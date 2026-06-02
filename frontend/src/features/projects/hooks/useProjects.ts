import { useCallback, useEffect, useState } from 'react'
import { createProject, deleteProject, listProjects, updateProject } from '../../../shared/lib/api'
import type { CreateProjectInput, ProjectSummary, UpdateProjectInput } from '../../../shared/lib/types'

const SELECTED_PROJECT_KEY = 'specforge:selected-project'

function readStoredProjectId() {
  return window.localStorage.getItem(SELECTED_PROJECT_KEY)
}

function rememberProjectId(projectId: string | null) {
  if (projectId) {
    window.localStorage.setItem(SELECTED_PROJECT_KEY, projectId)
  } else {
    window.localStorage.removeItem(SELECTED_PROJECT_KEY)
  }
}

export function useProjects() {
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(() => readStoredProjectId())
  const [loading, setLoading] = useState(false)

  const refreshProjects = useCallback(async () => {
    setLoading(true)
    try {
      const items = await listProjects()
      setProjects(items)
      setSelectedProjectId((current) => (current && items.some((item) => item.id === current) ? current : null))
    } finally {
      setLoading(false)
    }
  }, [])

  const addProject = useCallback(
    async (input: CreateProjectInput) => {
      const project = await createProject(input)
      await refreshProjects()
      setSelectedProjectId(project.id)
      return project
    },
    [refreshProjects],
  )

  const saveProject = useCallback(
    async (projectId: string, input: UpdateProjectInput) => {
      const project = await updateProject(projectId, input)
      await refreshProjects()
      setSelectedProjectId(project.id)
      return project
    },
    [refreshProjects],
  )

  const removeProject = useCallback(
    async (projectId: string) => {
      await deleteProject(projectId)
      setSelectedProjectId((current) => (current === projectId ? null : current))
      await refreshProjects()
    },
    [refreshProjects],
  )

  useEffect(() => {
    refreshProjects().catch(console.error)
  }, [refreshProjects])

  useEffect(() => {
    rememberProjectId(selectedProjectId)
  }, [selectedProjectId])

  return {
    projects,
    selectedProjectId,
    selectedProject: projects.find((project) => project.id === selectedProjectId) ?? null,
    loading,
    setSelectedProjectId,
    refreshProjects,
    addProject,
    saveProject,
    removeProject,
  }
}
