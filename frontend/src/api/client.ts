// ApiClient: the ONLY place that talks to the backend (docs/08). Components never fetch.
//
// Two things about credentials, both deliberate:
//   credentials: 'include' so the HttpOnly session cookie travels (SSE and <img> rely on it).
//   X-CSRF-Token on writes, mirrored from the readable `ea_csrf` cookie (double submit).
import type {
  AgentInfo,
  ArtifactView,
  ConstraintView,
  FeedbackView,
  PlatformConstraints,
  ProductView,
  RunView,
  SkillDetail,
  SkillRevisionView,
  SkillView,
  SlotInfo,
  TaskCreate,
  TaskView,
  TimelineTurn,
  AdminConfig,
  AdminLogs,
  AgentConfig,
  ModelProfileView,
  SaveModelProfile,
  SaveRuntime,
  ToolDetail,
  ToolInvokeResult,
  ToolView,
  UploadedFile,
  UtteranceBody,
  VersionView,
  CanvasOp,
  CanvasTemplate,
  CanvasView,
  AuthStatus,
  LedgerRow,
  Pricing,
  TopupOrder,
  AdminUser,
  InviteView,
  AuditRow,
  SessionUser,
} from './types'

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message)
  }
}

export interface ApiClient {
  agents(): Promise<AgentInfo[]>
  agentSkills(agentId: string): Promise<{ id: string; description: string }[]>
  slots(): Promise<SlotInfo[]>
  me(): Promise<{
    user_id: string
    display_name?: string
    role?: string
    credits: number
    held?: number
    csrf_token?: string | null
  }>
  // ---- auth & money ----
  authStatus(): Promise<AuthStatus>
  register(body: { display_name: string; invite_code: string }): Promise<{
    access_key: string
    user: SessionUser
  }>
  login(body: { display_name: string; access_key: string }): Promise<{ user: SessionUser }>
  logout(): Promise<{ status: string }>
  ledger(): Promise<LedgerRow[]>
  pricing(): Promise<Pricing>
  topups(): Promise<TopupOrder[]>
  createTopup(amountCents: number): Promise<TopupOrder>
  // ---- admin ----
  adminUsers(): Promise<AdminUser[]>
  grantCredits(userId: string, credits: number, reason: string): Promise<{ balance: number }>
  adjustCredits(userId: string, delta: number, reason: string): Promise<{ balance: number }>
  setUserStatus(userId: string, status: 'active' | 'disabled'): Promise<AdminUser>
  rotateUserKey(userId: string): Promise<{ access_key: string }>
  adminInvites(): Promise<InviteView[]>
  createInvite(body: { max_uses: number; days?: number | null; note?: string }): Promise<{
    id: string
    code: string
    max_uses: number
    expires_at: string | null
  }>
  revokeInvite(id: string): Promise<{ status: string }>
  adminTopups(): Promise<TopupOrder[]>
  confirmTopup(id: string): Promise<TopupOrder>
  cancelTopup(id: string): Promise<TopupOrder>
  auditLogs(): Promise<AuditRow[]>
  // ---- workbench ----
  listTasks(): Promise<TaskView[]>
  getTask(id: string): Promise<TaskView>
  canvasTemplates(): Promise<CanvasTemplate[]>
  createCanvasFromTemplate(templateId: string): Promise<TaskView>
  createTask(body: TaskCreate): Promise<TaskView>
  timeline(taskId: string): Promise<TimelineTurn[]>
  artifacts(taskId: string): Promise<ArtifactView[]>
  feedback(taskId: string): Promise<FeedbackView[]>
  constraints(taskId: string): Promise<{ effective: ConstraintView[]; pending: ConstraintView[] }>
  platformConstraints(): Promise<PlatformConstraints>
  confirmConstraint(id: string): Promise<ConstraintView>
  revokeConstraint(id: string): Promise<ConstraintView>
  utter(taskId: string, body: UtteranceBody): Promise<RunView>
  compact(taskId: string): Promise<{ status: string; summary_id?: string; reason?: string }>
  getRun(id: string): Promise<RunView>
  cancelRun(id: string): Promise<RunView>
  makeCurrent(versionId: string): Promise<VersionView>
  /** The canvas page. `version_id` is null until the Agent writes a first one. */
  canvas(taskId: string): Promise<CanvasView>
  /** A drag/resize/text/delete becomes one new Version, made by the user. No Run. */
  canvasPatch(versionId: string, ops: CanvasOp[]): Promise<VersionView>
  signal(versionId: string, signal: 'accept' | 'reject'): Promise<VersionView>
  accept(taskId: string): Promise<TaskView>
  upload(file: File): Promise<{ upload_id: string }>
  uploadAny(file: File): Promise<UploadedFile>
  products(): Promise<ProductView[]>
  product(id: string): Promise<ProductView>
  loadSamples(): Promise<ProductView[]>
  tools(): Promise<ToolView[]>
  tool(name: string): Promise<ToolDetail>
  invokeTool(name: string, input: Record<string, unknown>): Promise<ToolInvokeResult>
  adminConfig(): Promise<AdminConfig>
  saveAgentConfig(key: string, body: { model: string; system_prompt: string }): Promise<AgentConfig>
  saveModelProfile(key: string, body: SaveModelProfile): Promise<ModelProfileView>
  saveImageProfile(key: string): Promise<AdminConfig>
  saveRuntime(body: SaveRuntime): Promise<AdminConfig>
  adminLogs(): Promise<AdminLogs>
  skills(): Promise<SkillView[]>
  skill(id: string): Promise<SkillDetail>
  saveSkill(id: string, body: string, baseRevision: number): Promise<SkillDetail>
  skillRevisions(id: string): Promise<SkillRevisionView[]>
  resetSkill(id: string): Promise<SkillDetail>
  getPreferences(agentId: string): Promise<{ body_md: string; revision: number }>
  putPreferences(agentId: string, body_md: string): Promise<{ body_md: string; revision: number }>
  /** Subscribe to a Run's SSE stream. Returns an unsubscribe function. */
  subscribeRun(runId: string, onEvent: (type: string, data: unknown) => void): () => void
}

const SSE_EVENTS = [
  'run_queued', 'run_started', 'context_loaded', 'feedback_interpreted', 'answer',
  'answer_delta', 'followups', 'human_input_request', 'tool_started',
  'strategy_switch', 'constraint_pending', 'preference_proposed', 'tool_declined',
  'scope_rejected', 'step', 'version_created', 'run_succeeded', 'run_failed',
  'run_cancelled', 'todos', 'variants_created',
]
export const TERMINAL_EVENTS = ['run_succeeded', 'run_failed', 'run_cancelled']

/** Reads the double-submit token the server set. Absent in dev header mode. */
function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null
  const hit = document.cookie.split('; ').find((c) => c.startsWith(`${name}=`))
  return hit ? decodeURIComponent(hit.slice(name.length + 1)) : null
}

export function createApiClient(opts: { baseUrl?: string; userId?: string } = {}): ApiClient {
  const base = opts.baseUrl ?? ''

  /** One place where headers are assembled, so CSRF can never be forgotten on a write. */
  const headers = (method: string, extra?: Record<string, string>): Record<string, string> => ({
    ...(opts.userId ? { 'X-User-Id': opts.userId } : {}),
    ...(method === 'GET' || method === 'HEAD' ? {} : csrfHeader()),
    ...extra,
  })

  function csrfHeader(): Record<string, string> {
    const token = readCookie('ea_csrf')
    return token ? { 'X-CSRF-Token': token } : {}
  }

  async function call<T>(
    method: string,
    path: string,
    body?: unknown,
    extra?: Record<string, string>,
  ): Promise<T> {
    const res = await fetch(base + path, {
      method,
      credentials: 'include',
      headers: headers(method, {
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...extra,
      }),
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
    return parse<T>(res)
  }

  async function parse<T>(res: Response): Promise<T> {
    if (!res.ok) {
      let code = 'HTTP_ERROR'
      let message = res.statusText
      try {
        const j = await res.json()
        code = j.error?.code ?? code
        message = j.error?.message ?? message
      } catch {
        /* not json */
      }
      throw new ApiError(res.status, code, message)
    }
    if (res.status === 204) return undefined as T
    return (await res.json()) as T
  }

  async function uploadTo(path: string, file: File): Promise<Response> {
    const fd = new FormData()
    fd.append('file', file)
    return fetch(base + path, {
      method: 'POST',
      credentials: 'include',
      headers: headers('POST'),
      body: fd,
    })
  }

  return {
    agents: () => call('GET', '/api/agents'),
    agentSkills: (a) => call('GET', `/api/agents/${a}/skills`),
    slots: () => call('GET', '/api/slots'),
    me: () => call('GET', '/api/me'),

    authStatus: () => call('GET', '/api/auth/status'),
    register: (b) => call('POST', '/api/auth/register', b),
    login: (b) => call('POST', '/api/auth/login', b),
    logout: () => call('POST', '/api/auth/logout'),
    ledger: () => call('GET', '/api/me/credits'),
    pricing: () => call('GET', '/api/billing/pricing'),
    topups: () => call('GET', '/api/billing/topups'),
    createTopup: (amountCents) => call('POST', '/api/billing/topups', { amount_cents: amountCents }),

    adminUsers: () => call('GET', '/api/admin/users'),
    grantCredits: (userId, credits, reason) =>
      call('POST', `/api/admin/users/${userId}/grant`, { user_id: userId, credits, reason }),
    adjustCredits: (userId, delta, reason) =>
      call('POST', `/api/admin/users/${userId}/adjust`, { user_id: userId, delta, reason }),
    setUserStatus: (userId, status) =>
      call('POST', `/api/admin/users/${userId}/status`, { status }),
    rotateUserKey: (userId) => call('POST', `/api/admin/users/${userId}/rotate-key`),
    adminInvites: () => call('GET', '/api/admin/invites'),
    createInvite: (b) => call('POST', '/api/admin/invites', b),
    revokeInvite: (id) => call('POST', `/api/admin/invites/${id}/revoke`),
    adminTopups: () => call('GET', '/api/admin/topups'),
    confirmTopup: (id) => call('POST', `/api/admin/topups/${id}/confirm`),
    cancelTopup: (id) => call('POST', `/api/admin/topups/${id}/cancel`),
    auditLogs: () => call('GET', '/api/admin/audit'),

    listTasks: () => call('GET', '/api/tasks'),
    getTask: (id) => call('GET', `/api/tasks/${id}`),
    canvasTemplates: () => call('GET', '/api/canvas-templates'),
    createCanvasFromTemplate: (templateId) =>
      call('POST', `/api/canvas-templates/${encodeURIComponent(templateId)}`),
    createTask: (b) => call('POST', '/api/tasks', b),
    timeline: (id) => call('GET', `/api/tasks/${id}/timeline`),
    artifacts: (id) => call('GET', `/api/tasks/${id}/artifacts`),
    feedback: (id) => call('GET', `/api/tasks/${id}/feedback`),
    constraints: (id) => call('GET', `/api/tasks/${id}/constraints`),
    platformConstraints: () => call('GET', '/api/constraints/platform'),
    confirmConstraint: (id) => call('POST', `/api/constraints/${id}/confirm`),
    revokeConstraint: (id) => call('POST', `/api/constraints/${id}/revoke`),
    utter: (taskId, b) =>
      call('POST', `/api/tasks/${taskId}/utterances`, b, { 'Idempotency-Key': crypto.randomUUID() }),
    compact: (taskId) => call('POST', `/api/tasks/${taskId}/compact`),
    getRun: (id) => call('GET', `/api/runs/${id}`),
    cancelRun: (id) => call('POST', `/api/runs/${id}/cancel`),
    makeCurrent: (id) => call('POST', `/api/versions/${id}/make-current`),
    canvas: (taskId) => call('GET', `/api/tasks/${taskId}/canvas`),
    canvasPatch: (id, ops) => call('POST', `/api/versions/${id}/canvas-patches`, { ops }),
    signal: (id, signal) => call('POST', `/api/versions/${id}/signal`, { signal }),
    accept: (id) => call('POST', `/api/tasks/${id}/accept`),
    upload: async (file) => {
      const res = await uploadTo('/api/uploads', file)
      return parse<{ upload_id: string }>(res)
    },
    uploadAny: async (file) => parse<UploadedFile>(await uploadTo('/api/files', file)),
    products: () => call('GET', '/api/products'),
    product: (id) => call('GET', `/api/products/${id}`),
    loadSamples: () => call('POST', '/api/products/samples'),
    tools: () => call('GET', '/api/tools'),
    tool: (n) => call('GET', `/api/tools/${n}`),
    invokeTool: (n, input) => call('POST', `/api/tools/${n}/invoke`, { input }),
    adminConfig: () => call('GET', '/api/admin/config'),
    saveAgentConfig: (key, body) => call('PUT', `/api/admin/config/${key}`, body),
    saveModelProfile: (key, body) => call('PUT', `/api/admin/model-profiles/${key}`, body),
    saveImageProfile: (key) => call('PUT', '/api/admin/image-profile', { key }),
    saveRuntime: (body) => call('PUT', '/api/admin/runtime', body),
    adminLogs: () => call('GET', '/api/admin/logs'),
    skills: () => call('GET', '/api/skills'),
    skill: (id) => call('GET', `/api/skills/${id}`),
    saveSkill: (id, body, baseRevision) =>
      call('PUT', `/api/skills/${id}`, { body, base_revision: baseRevision }),
    skillRevisions: (id) => call('GET', `/api/skills/${id}/revisions`),
    resetSkill: (id) => call('POST', `/api/skills/${id}/reset`),
    getPreferences: (a) => call('GET', `/api/agents/${a}/preferences`),
    putPreferences: (a, body_md) => call('PUT', `/api/agents/${a}/preferences`, { body_md }),
    subscribeRun: (runId, onEvent) => {
      // Same-origin cookies travel on EventSource, so a logged-in session works here.
      const es = new EventSource(`${base}/api/runs/${runId}/events`, { withCredentials: true })
      for (const type of SSE_EVENTS) {
        es.addEventListener(type, (e) => {
          onEvent(type, JSON.parse((e as MessageEvent).data))
          if (TERMINAL_EVENTS.includes(type)) es.close()
        })
      }
      es.onerror = () => es.close()
      return () => es.close()
    },
  }
}
