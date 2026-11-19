// Shapes of docs/07 responses used by the UI. Slots come from the server (/api/slots).

export type SlotKey = string
export type NormRect = { x: number; y: number; w: number; h: number } // 0..1, relative to image

export interface AgentInfo {
  key: string
  title: string
  description: string
  tool_names: string[]
  skill_ids: string[]
  artifact_kinds: string[]
  workbench: 'pdp' | 'image' | 'general' | 'canvas'
  task_kind: 'pdp' | 'image' | 'file' | 'canvas' | null
}

export interface SlotInfo {
  key: SlotKey
  value_type: string
  artifact_kind: string
  max_items: number
  description: string
}

export interface Evaluation {
  evaluator_id: string
  passed: boolean
  can_reject: boolean
  details: Record<string, unknown>
}

export interface VersionView {
  id: string
  artifact_id: string
  task_id: string
  slot: SlotKey | null
  seq: number
  parent_version_id: string | null
  origin: 'generated' | 'edited' | 'imported' | 'cloned' | 'user'
  created_by: 'agent' | 'user'
  content: {
    text?: string
    items?: string[]
    url?: string
    urls?: string[]
    width?: number
    height?: number
    filename?: string
    mime?: string
    media?: 'html' | 'markdown' | 'table' | 'iframe' | 'download'
  }
  params: Record<string, unknown>
  manifest: Record<SlotKey, string>
  status: 'candidate' | 'ok' | 'rejected'
  user_signal: string | null
  run_id: string | null
  created_at: string
  evaluations: Evaluation[]
}

export interface ArtifactView {
  artifact_id: string
  kind: 'pdp' | 'text' | 'image' | 'file' | 'canvas'
  slot: SlotKey | null
  current_version_id: string | null
  versions: VersionView[]
}

/** A canvas theme. Colours and fonts are tokens: modules reference them by name, never by value. */
export interface CanvasTheme {
  colors: Record<string, string>
  fonts: Record<string, string>
  radius: number
}

export interface CanvasStyle {
  size?: number
  weight?: number
  align?: 'left' | 'center' | 'right'
  /** A token from `theme.colors`. */
  color?: string
  /** A token from `theme.fonts`. */
  font?: string
  fit?: 'contain' | 'cover'
  background?: 'white' | 'transparent'
}

/** One canvas module. `rect` is a fraction of ITS screen, so moving a screen never rewrites it. */
export interface CanvasModule {
  id: string
  kind: 'text' | 'image'
  name: string
  rect: NormRect
  style: CanvasStyle
  text?: string
  slot?: SlotKey
  /** The prompt that produced a picture. Part of the board, so an outside agent can read it. */
  prompt?: string
  /** Another image module whose picture was the reference for this one. */
  ref?: string
  version_id?: string | null
  url?: string | null
  width?: number | null
  height?: number | null
  /** A newer picture exists in the slot but the page does not point at it yet. */
  newer_version?: { version_id: string; seq: number; url: string; status: string } | null
}

/** One screen on the board. `pos` is world pixels, so screens keep their spacing at any zoom. */
export interface CanvasScreen {
  id: string
  name: string
  pos: { x: number; y: number }
  frame: { width: number; height: number }
  modules: CanvasModule[]
  /** Set on a copy: the screen it branched from. */
  variant_of?: string
  variant_label?: string
}

/** An edge of the clickable flow. */
export interface CanvasEdge {
  from: string
  to: string
  label: string
}

export interface CanvasVersionSummary {
  id: string
  seq: number
  status: 'candidate' | 'ok' | 'rejected'
  created_by: 'agent' | 'user'
  origin: string
  created_at: string
  is_current: boolean
}

/** `GET /api/tasks/:id/canvas`. No version yet: `version_id` is null, screens are empty. */
export interface CanvasView {
  task_id: string
  artifact_id?: string
  version_id: string | null
  seq?: number
  theme: CanvasTheme | null
  screens: CanvasScreen[]
  edges: CanvasEdge[]
  /** The world box of all screens: the frontend frames the board without measuring. */
  bounds: { x: number; y: number; width: number; height: number } | null
  versions: CanvasVersionSummary[]
  notes: string[]
}

/** Module ops name their `screen`; screen ops name the screen in `id`. */
export type CanvasOp =
  | { op: 'move_module'; screen?: string; id: string; dx: number; dy: number }
  | { op: 'resize_module'; screen?: string; id: string; rect: NormRect }
  | { op: 'set_text'; screen?: string; id: string; text: string }
  | { op: 'set_prompt'; screen?: string; id: string; prompt: string | null }
  | { op: 'set_style'; screen?: string; id: string; style: Record<string, unknown> }
  | { op: 'add_module'; screen: string; module: Omit<CanvasModule, 'version_id' | 'url'> }
  | { op: 'delete_module'; screen?: string; id: string }
  | { op: 'move_screen'; id: string; dx: number; dy: number }
  | { op: 'rename_screen'; id: string; name: string }
  | { op: 'resize_screen'; id: string; height: number }
  | { op: 'add_screen'; screen: Partial<CanvasScreen> }
  | { op: 'delete_screen'; id: string }
  | { op: 'keep_variant'; id: string }
  | { op: 'set_theme'; theme: Partial<CanvasTheme> }
  | { op: 'link_screens'; from: string; to: string; label?: string }
  | { op: 'unlink_screens'; from: string; to: string }

export interface TaskView {
  id: string
  kind: 'pdp' | 'image' | 'file' | 'general' | 'canvas'
  agent_key: string
  goal: string
  status: 'draft' | 'running' | 'awaiting_user' | 'accepted' | 'abandoned'
  meta: { product?: { id: string; name: string; brand: string }; profile?: string; [k: string]: unknown }
  product_id: string | null
  current: Record<SlotKey, string | null>
  pdp_version_id: string | null
  canvas_version_id?: string | null
  created_at: string
}

export interface RunView {
  id: string
  task_id: string
  agent_key: string
  status: 'queued' | 'running' | 'cancel_requested' | 'succeeded' | 'failed' | 'cancelled'
  path: string[]
  version_ids: string[]
  error: string | null
  held: number
  cost: number
  overrun?: number
}

// ---- accounts, session, money (docs/11) ------------------------------------
export interface SessionUser {
  id: string
  display_name: string
  role: 'user' | 'admin'
  /** Present on `/api/me` and after register/login. */
  balance?: number
  credits?: number
  registered?: boolean
}

export interface AuthStatus {
  authenticated: boolean
  dev_identity: boolean
  user?: SessionUser
}

export interface LedgerRow {
  id: number
  delta: number
  kind: 'grant' | 'topup' | 'hold' | 'settle' | 'refund' | 'adjust' | 'spend'
  run_id: string | null
  balance_after: number
  note: string
  created_at: string
}

export interface Pricing {
  credits_per_yuan: number
  min_topup_cents: number
  max_topup_cents: number
  topup_enabled: boolean
  price_multiplier: number
  budgets: Record<string, number>
}

export interface TopupOrder {
  id: string
  user_id: string
  amount_cents: number
  amount_yuan: number
  credits: number
  method: string
  status: 'pending' | 'paid' | 'cancelled' | 'failed'
  note: string
  created_at: string
  paid_at: string | null
  payment?: { provider: string; status: string; note: string }
  balance?: number
}

export interface AdminUser {
  id: string
  display_name: string
  role: 'user' | 'admin'
  status: 'active' | 'disabled'
  invite_id: string | null
  created_at: string
  last_login_at: string | null
  balance: number
}

export interface InviteView {
  id: string
  created_by: string
  max_uses: number
  used_count: number
  revoked: boolean
  note?: string
  expires_at: string | null
  created_at: string
}

export interface AuditRow {
  id: number
  actor_id: string
  action: string
  target_type: string
  target_id: string
  detail: Record<string, unknown>
  ip: string
  created_at: string
}


export interface FeedbackView {
  id: string
  run_id: string
  text: string
  interpretation: 'parameter_patch' | 'new_constraint' | 'question' | 'strategy_switch'
  target_slot: SlotKey | null
  target_version_id: string | null
  target_region: NormRect | null
  status: 'open' | 'applied' | 'dismissed' | 'declined'
  note: string
}

export interface ConstraintView {
  id: string
  text: string
  rule: Record<string, unknown>
  status: 'pending' | 'effective' | 'revoked'
}

export interface UtteranceBody {
  text: string
  agent_id?: string
  target_slot?: SlotKey
  target_version_id?: string
  target_region?: NormRect
  client_hint?: 'constraint' | 'preference'
  reasoning?: boolean
  /** `/skill-name`: narrows this Run to one Skill the Agent may use. */
  skill_id?: string
  /** Composer `+` uploads; text ones are inlined for the planner. */
  attachment_ids?: string[]
  /**
   * The `ask_question` this sentence is answering. A Run is not resumed (there is no
   * `tool_result` channel); this is how the next Run knows which question it replies to, so
   * the answer does not arrive with the question missing.
   */
  answers_request_id?: string
}

export interface UploadedFile {
  upload_id: string
  name: string
  mime: string
  size: number
  readable: boolean
  kind: 'image' | 'file'
}

export interface CanvasTemplate {
  id: string
  title: string
  blurb: string
  goal: string
}

export type TaskCreate = {
  agent_id: string
  goal?: string
  kind?: 'pdp' | 'image' | 'file' | 'general' | 'canvas'
  profile?: string
  upload_id?: string
  product_id?: string
  import_product?: boolean
}

export interface ProductView {
  id: string
  name: string
  brand: string
  marketplace: string
  mode: 'generate' | 'optimize'
  facts: {
    attributes?: Record<string, string>
    rating?: { stars: number; ratings: number } | null
    price_text?: string | null
    category_path?: string[]
    observations?: string[]
  }
  listing: { title?: string | null; bullets?: string[] | null; description?: string | null; search_terms?: string | null }
  main_url: string | null
  gallery_urls: string[]
  created_at: string
  tasks?: TaskView[]
}

export interface ToolView {
  name: string
  version: string
  description: string
  side_effect: string
  cost_credits: number
  timeout_s: number
  idempotent: boolean
  agents: string[]
}
export interface ToolDetail extends ToolView {
  input_schema: { properties?: Record<string, { type?: string; description?: string; anyOf?: unknown }>; required?: string[] }
  output_schema: { properties?: Record<string, { type?: string; description?: string; anyOf?: unknown }>; required?: string[] }
}

export interface SkillView {
  id: string
  description: string
  hash: string
  agents: string[]
  tools: string[]
  /** `general` = any entry; `pdp` / `image` = that specialist only; `any` = both specialists. */
  audience: 'general' | 'pdp' | 'image' | 'any'
  revision: number
  source: 'file' | 'edited' | 'restored'
}
export interface SkillDetail extends SkillView {
  body: string
}
export interface SkillRevisionView {
  revision: number
  edited_by: string
  source: string
  created_at: string
  hash: string
}

export interface PlatformConstraints {
  pack_id: string
  version: string
  note: string
  items: { key: string; slot: SlotKey; hard: boolean; value: number; summary: string }[]
}

export interface TimelineStep {
  /** Stable id; a card is keyed by it so `tool_started` and the finished row are one card. */
  tool_call_id?: string
  tool: string
  slot: SlotKey | null
  ok: boolean
  error: string | null
  duration_ms: number
  cost: number
  base_version_id: string | null
  patch: Record<string, unknown> | null
  path?: string | null
  draft?: string | null
  /** Trimmed arguments, shown behind the card's disclosure. */
  input?: Record<string, unknown>
  /** What the Tool returned; `version_id` when it wrote one. */
  output?: Record<string, unknown>
}

/** A Tool call announced before it ran (SSE `tool_started`). Result arrives as a step. */
export interface ToolStarted {
  tool_call_id: string
  tool: string
  slot: SlotKey | null
  cost: number
  args: Record<string, unknown>
}

export interface TimelineVersion {
  id: string
  slot: SlotKey | null
  seq: number
  kind: 'pdp' | 'image' | 'text' | 'file' | 'canvas'
  status: 'candidate' | 'ok' | 'rejected'
  is_current: boolean
  content: VersionView['content']
  parent_content: VersionView['content'] | null
  params: Record<string, unknown>
  evaluations: { evaluator_id: string; passed: boolean; problems: string[] }[]
}

export interface TimelineInterpretation {
  feedback_id: string
  kind: FeedbackView['interpretation']
  text: string
  slot: SlotKey | null
  region: NormRect | null
  status: FeedbackView['status']
  note: string
  constraint_id: string | null
  constraint_status: ConstraintView['status'] | null
}

export interface ToolInvokeResult {
  status: 'ok' | 'error'
  output: Record<string, unknown>
  error: string | null
  cost: number
  duration_ms: number
}

export interface AgentConfig {
  key: string
  title: string
  model: string
  system_prompt: string
  preview: string
  variables: string[]
}

export interface ModelProfileView {
  key: string
  upstream_model: string
  kind: string
  enabled: boolean
  context_window_tokens: number
  capabilities: string[]
}

/** Fields the console may change on one model profile. Omitted fields keep their value. */
export interface SaveModelProfile {
  upstream_model?: string
  context_window_tokens?: number
  enabled?: boolean
}

export interface SaveRuntime {
  summary_fraction?: number
  summary_keep?: number
  max_tool_calls?: number
}

export interface AdminConfig {
  env: { key: string; value: string; editable: boolean }[]
  agents: AgentConfig[]
  note: string
  profiles?: ModelProfileView[]
  image_profile?: string
  runtime?: { summary_fraction: number; summary_keep: number; max_tool_calls: number }
}

export interface AdminLogs {
  tool_calls: { id: number; run_id: string; tool: string; agent: string; status: string; error: string | null; duration_ms: number; cost: number; input: Record<string, unknown>; output: Record<string, unknown> }[]
  llm_calls: { id: number; run_id: string | null; alias: string; kind: string; model: string; status: string; duration_ms: number; purpose?: string; profile_key?: string }[]
}

export interface HumanInputOption {
  id: string
  label: string
  value: string
}

/** Run event + timeline payload for ask_question (deer-flow shape). */
export interface HumanInputRequest {
  version: 1
  kind: 'human_input_request'
  source: string
  request_id: string
  tool_call_id: string
  question: string
  /**
   * `upload` means the Agent wants a picture, not words: the panel offers the file picker
   * instead of a text box (the `request_upload` tool).
   */
  input_mode: 'text' | 'single_choice' | 'upload'
  options: HumanInputOption[]
  /** Set by `request_upload`: the slot the picture would go into. */
  for_slot?: string
}

/** The visible plan from `write_todos`. The newest list replaces the previous one. */
export interface TodoItem {
  text: string
  status: 'pending' | 'in_progress' | 'done'
}

export interface TimelineTurn {
  run_id: string
  agent_key: string
  status: RunView['status']
  error: string | null
  cost: number
  held: number
  created_at: string
  user: {
    text: string
    target_slot: SlotKey | null
    target_region: NormRect | null
    target_version_id: string | null
  }
  interpretations: TimelineInterpretation[]
  answers: string[]
  /** Index-aligned with `answers`: replies the user may send with one click, best first. */
  answer_options: string[][]
  /** Structured asks from `ask_question` (deer-flow `human_input_request`). */
  human_input_requests: HumanInputRequest[]
  /** The last plan the Agent showed through `write_todos`, if any. */
  todos?: TodoItem[]
  /** Calls announced before they ran; the finished record is in `steps`, same id. */
  tool_started?: ToolStarted[]
  /**
   * One-click next questions for the turn that just finished. A UI hint, not an answer:
   * `ask_question` blocks the Run, these never do.
   */
  follow_ups: string[]
  preference_proposals: string[]
  declined: { tool?: string; code?: string; reason?: string }[]
  steps: TimelineStep[]
  versions: TimelineVersion[]
}
