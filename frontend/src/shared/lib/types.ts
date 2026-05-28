export type IterationStatus =
  | 'created'
  | 'queued'
  | 'planning'
  | 'awaiting_design_approval'
  | 'coding'
  | 'retrying'
  | 'testing'
  | 'awaiting_verify_approval'
  | 'delivered'
  | 'blocked'
  | 'blocked_user'
  | 'failed'
  | 'stopped'

export type NodeName = 'planner' | 'coder' | 'coder_retry' | 'integrity_check' | 'tester' | 'planner_clarification' | 'planner_verify'
export type Mode = 'dry-run' | 'real-cli'

export interface IterationSummary {
  id: string
  project_id: string | null
  epic_id: string | null
  project_name: string
  goal: string
  mode: Mode
  status: IterationStatus
  current_node: NodeName | null
  retry_counts: Record<string, number>
  last_error: string | null
  created_at: string
  updated_at: string
}

export type EpicStatus = 'draft' | 'active' | 'blocked' | 'delivered'

export interface EpicSummary {
  id: string
  project_id: string
  title: string
  description: string
  acceptance_criteria: string
  status: EpicStatus
  iteration_count: number
  active_count: number
  blocked_count: number
  delivered_count: number
  created_at: string
  updated_at: string
}

export interface EpicDetail extends EpicSummary {
  iterations: IterationSummary[]
}

export interface ProjectSummary {
  id: string
  name: string
  root_path: string | null
  description: string | null
  default_mode: Mode
  default_test_command: string | null
  planner_model: string | null
  coder_model: string | null
  tester_model: string | null
  max_coder_tester_retries: number
  max_clarifications: number
  max_verify_rejects: number
  created_at: string
  updated_at: string
  iteration_count: number
  active_count: number
  delivered_count: number
}

export interface DocumentRecord {
  name: string
  path: string
  checksum: string
  created_at: string
  updated_at: string
}

export interface EventRecord {
  id: string
  type: string
  payload: Record<string, unknown>
  created_at: string
}

export type EventSeverity = 'info' | 'success' | 'warning' | 'error'

export interface SemanticEvent {
  id: string
  type: string
  node: string
  title: string
  message: string
  severity: EventSeverity
  created_at: string
  run_id?: string
  document?: string
  action_hint?: string
  raw: EventRecord
}

export interface AgentActivityItem extends SemanticEvent {}

export interface ReadableError {
  title: string
  message: string
  action_hint: string
  severity: EventSeverity
}

export interface NodeRunRecord {
  id: string
  node: NodeName
  status: string
  command: string
  stdout: string
  stderr: string
  exit_code: number | null
  started_at: string
  finished_at: string | null
}

export interface UIArtifactLink {
  label: string
  path: string
}

export type UITestStatus = 'passed' | 'failed' | 'skipped' | 'warning'
export type UIDriverStatus = UITestStatus

export interface UITestResult {
  id: string
  title: string
  kind: 'web' | 'native'
  status: UITestStatus
  target: string
  error: string | null
  observations: string[]
  artifacts: UIArtifactLink[]
}

export interface IterationDetail extends IterationSummary {
  test_command: string | null
  graph_next: string[]
  documents: DocumentRecord[]
  events: EventRecord[]
  runs: NodeRunRecord[]
  ui_results: UITestResult[]
}

export interface LiveMessage {
  type: 'snapshot' | 'event'
  event?: EventRecord
  snapshot?: IterationDetail
}

export type LiveConnectionStatus = 'idle' | 'connecting' | 'connected' | 'reconnecting' | 'disconnected'
export type TimelineFilter = 'all' | 'decisions' | 'failures' | 'tests' | 'runs'

export interface UpdateProjectInput {
  name?: string
  description?: string | null
  root_path?: string
  create_if_missing?: boolean
  default_mode?: Mode
  default_test_command?: string | null
  max_coder_tester_retries?: number
  max_clarifications?: number
  max_verify_rejects?: number
}

export interface CreateProjectInput {
  root_path: string
  create_if_missing: boolean
  name?: string
  description?: string | null
  default_mode?: Mode
  default_test_command?: string | null
  max_coder_tester_retries?: number
  max_clarifications?: number
  max_verify_rejects?: number
}

export interface ValidateProjectPathResult {
  ok: boolean
  resolved_path: string
  message: string
}

export interface BrowseDirectoryEntry {
  name: string
  path: string
}

export interface BrowseQuickRoot {
  label: string
  path: string
}

export interface BrowseDirectoryResult {
  path: string
  parent: string | null
  entries: BrowseDirectoryEntry[]
  quick_roots: BrowseQuickRoot[]
}

export interface PickFolderResult {
  cancelled: boolean
  path: string
}

export interface CreateEpicInput {
  project_id: string
  title: string
  description?: string
  acceptance_criteria?: string
}

export interface UpdateEpicInput {
  title?: string
  description?: string
  acceptance_criteria?: string
}
