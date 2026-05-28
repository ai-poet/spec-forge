import { useCallback, useEffect, useState } from 'react'
import { createProject, listProjects, updateProject } from '../api'
import type { ProjectSummary, UpdateProjectInput } from '../types'

export function useProjects() {
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const refreshProjects = useCallback(async () => {
    setLoading(true)
    try {
      const items = await listProjects()
      setProjects(items)
      setSelectedProjectId((current) => current ?? items[0]?.id ?? null)
    } finally {
      setLoading(false)
    }
  }, [])

  const addProject = useCallback(
    async (name: string, description?: string) => {
      const project = await createProject({ name, description })
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

  useEffect(() => {
    refreshProjects().catch(console.error)
  }, [refreshProjects])

  return {
    projects,
    selectedProjectId,
    selectedProject: projects.find((project) => project.id === selectedProjectId) ?? null,
    loading,
    setSelectedProjectId,
    refreshProjects,
    addProject,
    saveProject,
  }
}
