export type IterationStatus =
  | 'created'
  | 'queued'
  | 'planning'
  | 'awaiting_requirements_input'
  | 'coding'
  | 'retrying'
  | 'testing'
  | 'awaiting_verify_approval'
  | 'delivered'
  | 'blocked'
  | 'blocked_user'
  | 'failed'
  | 'stopped'

export type NodeName =
  | 'prd_planner'
  | 'test_planner'
  | 'planner_discovery'
  | 'coder'
  | 'coder_retry'
  | 'integrity_check'
  | 'code_tester'
  | 'ui_tester'
  | 'ui_driver'
  | 'planner_clarification'
  | 'planner_verify'
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
  stopped_at_node: string | null
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

export type CliBindingProvider = 'claude' | 'codex'

export interface CliBindings {
  prd_planner: CliBindingProvider
  test_planner: CliBindingProvider
  planner_discovery: CliBindingProvider
  planner_clarification: CliBindingProvider
  coder: CliBindingProvider
  code_tester: CliBindingProvider
  ui_tester: CliBindingProvider
}

export const DEFAULT_CLI_BINDINGS: CliBindings = {
  prd_planner: 'claude',
  test_planner: 'claude',
  planner_discovery: 'claude',
  planner_clarification: 'claude',
  coder: 'claude',
  code_tester: 'claude',
  ui_tester: 'claude',
}

export interface ProjectSummary {
  id: string
  name: string
  root_path: string | null
  description: string | null
  default_mode: Mode
  default_test_command: string | null
  cli_bindings: CliBindings | null
  coder_model: string | null
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
export type CliProvider = 'claude_code' | 'codex'
export type CliPhase = 'session' | 'thinking' | 'text' | 'tool' | 'command' | 'file_change' | 'mcp' | 'todo' | 'hook' | 'retry' | 'result' | 'error'

export interface CliDisplayPayload {
  provider: CliProvider
  node: string
  phase: CliPhase
  title: string
  message: string
  severity: EventSeverity
  item_id?: string
  status?: string
  command?: string
  paths?: string[]
  tool?: string
  preview?: string
  raw_event?: Record<string, unknown>
}

export interface SemanticEvent {
  id: string
  type: string
  node: string
  title: string
  message: string
  severity: EventSeverity
  created_at: string
  provider?: CliProvider
  phase?: CliPhase
  status?: string
  command?: string
  paths?: string[]
  tool?: string
  preview?: string
  item_id?: string
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
  stdout?: string | null
  stderr?: string | null
  exit_code: number | null
  started_at: string
  finished_at: string | null
  duration_ms?: number | null
  stdout_bytes: number
  stderr_bytes: number
  logs_url?: string | null
  raw_log_url?: string | null
  provider?: 'claude' | 'codex' | null
  session_id?: string | null
  session_mode?: 'new' | 'continue' | string | null
  prompt_hash?: string | null
  prompt_url?: string | null
  worker_ref_url?: string | null
  context_package_url?: string | null
  supports_continue?: boolean
  timed_out?: boolean
}

export interface RunLogLine {
  stream: 'stdout' | 'stderr' | string
  line: number
  text: string
  node?: string | null
  created_at?: string | null
}

export interface RunLogPage {
  items: RunLogLine[]
  offset: number
  limit: number
  total: number
  has_more: boolean
  stdout?: string
  stderr?: string
}

export interface PromptBundlePayload {
  version?: string
  system_prompt?: string
  user_prompt?: string
  output_schema?: string
  metadata?: Record<string, unknown>
  prompt_hash?: string
}

export interface WorkerRefPayload {
  version?: string
  provider?: string
  mode?: string
  supportsOpenSession?: boolean
  supportsContinueSession?: boolean
  continueRef?: Record<string, unknown> | null
  openCommand?: string | null
}

export type StageProfileBindings = Partial<Record<keyof CliBindings, string | null>>

export interface ProjectProfile {
  id: string
  name: string
  summary: string
  stage: keyof CliBindings | string
  content: string
  created_at: string
  updated_at: string
  path: string
}

export interface ProfileBindingsResponse {
  bindings: StageProfileBindings
}

export interface WorkflowSnapshotNode {
  id: string
  label: string
  provider?: CliBindingProvider | null
  session_policy: string
  retry_budget?: Record<string, number> | null
  profile?: ProjectProfile | null
}

export interface WorkflowSnapshot {
  version: string
  kind: string
  iteration_id?: string | null
  project_id?: string | null
  nodes: WorkflowSnapshotNode[]
  edges: Array<Record<string, unknown>>
  retry_budget: Record<string, number>
  profile_bindings: StageProfileBindings
}

export interface ContextPackagePayload {
  version: string
  run_id: string
  node: string
  profile?: ProjectProfile | null
  hot_docs: Array<Record<string, unknown>>
  cold_manifest: Array<Record<string, unknown>>
  runtime_notes: Array<Record<string, unknown>>
  previous_feedback: Array<Record<string, unknown>>
  iteration_root: string
  docs_root: string
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
  driver?: 'cua' | 'playwright' | null
  error: string | null
  observations: string[]
  artifacts: UIArtifactLink[]
}

export interface LiveCliOutput {
  node: string
  stdout: string
  stderr: string
}

export interface CliOutputPayload {
  node: string
  stream: 'stdout' | 'stderr'
  chunk: string
}

export interface PendingDiscovery {
  round: number
  question: string
  options: string[]
  assumptions: string[]
}

export interface DiscoveryHistoryEntry {
  round: number
  question: string
  answer: string
}

export interface IterationDetail extends IterationSummary {
  test_command: string | null
  graph_next: string[]
  pending_discovery?: PendingDiscovery | null
  discovery_history?: DiscoveryHistoryEntry[]
  documents: DocumentRecord[]
  events: EventRecord[]
  runs: NodeRunRecord[]
  ui_results: UITestResult[]
  live_cli?: LiveCliOutput | null
}

export interface LiveMessage {
  type: 'snapshot' | 'event' | 'cli.output' | 'pong'
  event?: EventRecord | { type: 'cli.output'; payload: CliOutputPayload }
  snapshot?: IterationDetail | null
}

export type LiveConnectionStatus = 'idle' | 'connecting' | 'connected' | 'reconnecting' | 'disconnected'
export type TimelineFilter = 'all' | 'decisions' | 'failures' | 'tests' | 'runs'
export type EnvironmentCheckStatus = 'ok' | 'warning' | 'error'

export interface EnvironmentCheckItem {
  id: string
  label: string
  status: EnvironmentCheckStatus
  message: string
  detail: string | null
  hint: string | null
  provider?: 'claude' | 'codex'
  version?: string | null
  capabilities?: Record<string, boolean>
}

export interface EnvironmentChecksResult {
  status: EnvironmentCheckStatus
  checked_at: string
  checks: EnvironmentCheckItem[]
}

export interface UpdateProjectInput {
  name?: string
  description?: string | null
  root_path?: string
  create_if_missing?: boolean
  default_mode?: Mode
  default_test_command?: string | null
  cli_bindings?: CliBindings | null
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
