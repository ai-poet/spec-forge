import type { IterationDetail, IterationSummary, Mode, ProjectSummary, UpdateProjectInput } from './types'

const API_BASE = 'http://127.0.0.1:8787'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`)
  }
  return response.json() as Promise<T>
}

export function listIterations(): Promise<IterationSummary[]> {
  return request('/api/iterations')
}

export function listIterationsForProject(projectId: string): Promise<IterationSummary[]> {
  return request(`/api/iterations?project_id=${encodeURIComponent(projectId)}`)
}

export function listProjects(): Promise<ProjectSummary[]> {
  return request('/api/projects')
}

export function createProject(input: { name: string; description?: string | null }): Promise<ProjectSummary> {
  return request('/api/projects', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function getProject(id: string): Promise<ProjectSummary> {
  return request(`/api/projects/${id}`)
}

export function updateProject(id: string, input: UpdateProjectInput): Promise<ProjectSummary> {
  return request(`/api/projects/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
}

export function createIteration(input: {
  project_name?: string
  project_id?: string
  goal: string
  mode?: Mode | null
  test_command?: string | null
}): Promise<IterationSummary> {
  return request('/api/iterations', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function getIteration(id: string): Promise<IterationDetail> {
  return request(`/api/iterations/${id}`)
}

export function approveDesign(id: string, note?: string): Promise<IterationSummary> {
  return request(`/api/iterations/${id}/approve-design`, {
    method: 'POST',
    body: JSON.stringify({ note }),
  })
}

export function approveVerify(id: string, note?: string): Promise<IterationSummary> {
  return request(`/api/iterations/${id}/approve-verify`, {
    method: 'POST',
    body: JSON.stringify({ note }),
  })
}

export function stopIteration(id: string, note?: string): Promise<IterationSummary> {
  return request(`/api/iterations/${id}/stop`, {
    method: 'POST',
    body: JSON.stringify({ note }),
  })
}
