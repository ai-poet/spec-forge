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

export interface ProjectSummary {
  id: string
  name: string
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

export interface IterationDetail extends IterationSummary {
  test_command: string | null
  graph_next: string[]
  documents: DocumentRecord[]
  events: EventRecord[]
  runs: NodeRunRecord[]
}

export interface LiveMessage {
  type: 'snapshot' | 'event'
  event?: EventRecord
  snapshot?: IterationDetail
}

export interface UpdateProjectInput {
  name?: string
  description?: string | null
  default_mode?: Mode
  default_test_command?: string | null
  planner_model?: string | null
  coder_model?: string | null
  tester_model?: string | null
  max_coder_tester_retries?: number
  max_clarifications?: number
  max_verify_rejects?: number
}
