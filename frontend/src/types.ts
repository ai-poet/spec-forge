export type IterationStatus =
  | 'created'
  | 'planning'
  | 'awaiting_design_approval'
  | 'coding'
  | 'testing'
  | 'awaiting_verify_approval'
  | 'delivered'
  | 'blocked'
  | 'failed'
  | 'stopped'

export type NodeName = 'planner' | 'coder' | 'tester'

export interface IterationSummary {
  id: string
  project_id: string | null
  project_name: string
  goal: string
  mode: 'dry-run' | 'real-cli'
  status: IterationStatus
  current_node: NodeName | null
  created_at: string
  updated_at: string
}

export interface ProjectSummary {
  id: string
  name: string
  description: string | null
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
