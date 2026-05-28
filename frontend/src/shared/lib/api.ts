import type {
  CreateEpicInput,
  CreateProjectInput,
  EpicDetail,
  EpicSummary,
  IterationDetail,
  IterationSummary,
  Mode,
  ProjectSummary,
  UpdateEpicInput,
  UpdateProjectInput,
  ValidateProjectPathResult,
  BrowseDirectoryResult,
  PickFolderResult,
} from './types'

const API_BASE = 'http://127.0.0.1:8787'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    throw new Error(await readableHttpError(response))
  }
  return response.json() as Promise<T>
}

async function readableHttpError(response: Response): Promise<string> {
  let detail: unknown
  try {
    const payload = await response.json()
    detail = payload?.detail
  } catch {
    detail = undefined
  }
  const message = typeof detail === 'string'
    ? detail
    : detail && typeof detail === 'object' && 'message' in detail && typeof detail.message === 'string'
      ? detail.message
      : undefined
  if (response.status === 404) return message ?? '没有找到对应的项目、需求或迭代。'
  if (response.status === 409) return message ?? '当前状态不允许执行这个操作，请刷新后确认流水线状态。'
  if (response.status === 422) return message ?? '输入内容不完整或格式不正确，请检查表单。'
  if (response.status >= 500) return message ?? '后端执行出错，请查看事件流和运行日志。'
  return message ?? `请求失败，状态码 ${response.status}。`
}

export function listIterations(): Promise<IterationSummary[]> {
  return request('/api/iterations')
}

export function listIterationsForProject(projectId: string): Promise<IterationSummary[]> {
  return request(`/api/iterations?project_id=${encodeURIComponent(projectId)}`)
}

export function listIterationsForEpic(epicId: string): Promise<IterationSummary[]> {
  return request(`/api/iterations?epic_id=${encodeURIComponent(epicId)}`)
}

export function listProjects(): Promise<ProjectSummary[]> {
  return request('/api/projects')
}

export function validateProjectPath(input: { root_path: string; create_if_missing: boolean }): Promise<ValidateProjectPathResult> {
  return request('/api/projects/validate-path', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function browseProjectDirectory(path?: string | null): Promise<BrowseDirectoryResult> {
  const query = path ? `?path=${encodeURIComponent(path)}` : ''
  return request(`/api/projects/browse${query}`)
}

export function pickProjectFolder(): Promise<PickFolderResult> {
  return request('/api/projects/pick-folder', { method: 'POST' })
}

export function createProject(input: CreateProjectInput): Promise<ProjectSummary> {
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

export function deleteProject(id: string): Promise<{ ok: boolean }> {
  return request(`/api/projects/${id}`, {
    method: 'DELETE',
  })
}

export function listEpicsForProject(projectId: string): Promise<EpicSummary[]> {
  return request(`/api/epics?project_id=${encodeURIComponent(projectId)}`)
}

export function createEpic(input: CreateEpicInput): Promise<EpicSummary> {
  return request('/api/epics', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function getEpic(id: string): Promise<EpicDetail> {
  return request(`/api/epics/${id}`)
}

export function updateEpic(id: string, input: UpdateEpicInput): Promise<EpicSummary> {
  return request(`/api/epics/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
}

export function deleteEpic(id: string): Promise<{ ok: boolean }> {
  return request(`/api/epics/${id}`, {
    method: 'DELETE',
  })
}

export function createIteration(input: {
  project_name?: string
  project_id?: string
  epic_id?: string | null
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

export function artifactUrl(iterationId: string, path: string): string {
  return `${API_BASE}/api/iterations/${encodeURIComponent(iterationId)}/artifacts/${path.split('/').map(encodeURIComponent).join('/')}`
}

export function deleteIteration(id: string): Promise<{ ok: boolean }> {
  return request(`/api/iterations/${id}`, {
    method: 'DELETE',
  })
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

export function resumeIteration(id: string, note?: string): Promise<IterationSummary> {
  return request(`/api/iterations/${id}/resume`, {
    method: 'POST',
    body: JSON.stringify({ note }),
  })
}
