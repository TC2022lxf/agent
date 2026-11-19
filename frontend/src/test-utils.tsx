import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { vi } from 'vitest'
import { App } from './App'
import type { ApiClient } from './api/client'
import type { ArtifactView, AuthStatus, TaskView, TimelineTurn, VersionView } from './api/types'
import { ApiProvider } from './state/api-context'
import { AuthProvider } from './state/auth'
import { NavProvider, type NavState } from './state/nav'
import { ToastProvider } from './state/toast'

export const TASK: TaskView = {
  id: 't1', kind: 'pdp', agent_key: 'general', goal: 'NKTMXY 迷你电动剃须刀', status: 'awaiting_user',
  meta: { product: { id: 'p1', name: 'NKTMXY 迷你电动剃须刀', brand: 'NKTMXY' } },
  product_id: 'p1', current: {}, pdp_version_id: 'pv1', created_at: '2026-01-01T00:00:00Z',
}

export function version(over: Partial<VersionView>): VersionView {
  return {
    id: 'v1', artifact_id: 'a1', task_id: 't1', slot: 'main_image', seq: 1, parent_version_id: null,
    origin: 'imported', created_by: 'user', content: { url: '/img/main.png', width: 400, height: 400 },
    params: {}, manifest: {}, status: 'ok', user_signal: null, run_id: null, created_at: '2026-01-01T00:00:00Z',
    evaluations: [], ...over,
  }
}

export function artifacts(): ArtifactView[] {
  const main = version({})
  const title = version({ id: 'vt', artifact_id: 'a2', slot: 'title', content: { text: 'Electric Foil Shaver' } })
  const pdp = version({ id: 'pv1', artifact_id: 'a0', slot: null, manifest: { title: 'vt', main_image: 'v1' }, content: {} })
  return [
    { artifact_id: 'a0', kind: 'pdp', slot: null, current_version_id: 'pv1', versions: [pdp] },
    { artifact_id: 'a1', kind: 'image', slot: 'main_image', current_version_id: 'v1', versions: [main] },
    { artifact_id: 'a2', kind: 'text', slot: 'title', current_version_id: 'vt', versions: [title] },
  ]
}

export function turn(over: Partial<TimelineTurn>): TimelineTurn {
  return {
    run_id: 'run-abcdef', agent_key: 'general', status: 'succeeded', error: null, cost: 5, held: 20,
    created_at: '2026-01-01T00:00:00Z',
    user: { text: '改一下', target_slot: null, target_region: null, target_version_id: null },
    interpretations: [], answers: [], answer_options: [], human_input_requests: [], follow_ups: [], preference_proposals: [], declined: [], steps: [], versions: [], ...over,
  }
}

/** A fake ApiClient: every method resolves with small fixtures; override per test. */
export function fakeApi(over: Partial<ApiClient> = {}): ApiClient {
  const subscribeRun: ApiClient['subscribeRun'] = (_id, onEvent) => {
    queueMicrotask(() => onEvent('run_succeeded', {}))
    return () => {}
  }
  const api: ApiClient = {
    agents: async () => [
      { key: 'general', title: '通用 Agent', description: '', tool_names: [], skill_ids: [], artifact_kinds: [], workbench: 'general', task_kind: null },
      { key: 'image', title: '图片 Agent', description: '', tool_names: [], skill_ids: [], artifact_kinds: [], workbench: 'image', task_kind: 'image' },
    ],
    agentSkills: async () => [{ id: 'image-local-edit', description: '局部改图' }],
    slots: async () => [],
    me: async () => ({ user_id: 'u', display_name: 'u', role: 'admin', credits: 1000, held: 0 }),
    authStatus: async () => ({
      authenticated: true,
      dev_identity: true,
      user: { id: 'u', display_name: 'u', role: 'admin' as const, balance: 1000 },
    }),
    register: async () => ({
      access_key: 'ek_test',
      user: { id: 'u', display_name: 'u', role: 'user' as const },
    }),
    login: async () => ({ user: { id: 'u', display_name: 'u', role: 'user' as const } }),
    logout: async () => ({ status: 'logged_out' }),
    ledger: async () => [],
    pricing: async () => ({
      credits_per_yuan: 100,
      min_topup_cents: 100,
      max_topup_cents: 100_000,
      topup_enabled: true,
      price_multiplier: 1,
      budgets: { pdp: 120, image: 80, general: 120, file: 60, canvas: 100 },
    }),
    topups: async () => [],
    createTopup: async (amountCents) => ({
      id: 'top1', user_id: 'u', amount_cents: amountCents, amount_yuan: amountCents / 100,
      credits: amountCents, method: 'manual', status: 'pending' as const, note: '',
      created_at: '2026-01-01T00:00:00Z', paid_at: null,
      payment: { provider: 'manual', status: 'awaiting_confirmation', note: '' },
    }),
    adminUsers: async () => [],
    grantCredits: async () => ({ balance: 1000 }),
    adjustCredits: async () => ({ balance: 1000 }),
    setUserStatus: async (_id, status) => ({
      id: 'u', display_name: 'u', role: 'user' as const, status,
      invite_id: null, created_at: '2026-01-01T00:00:00Z', last_login_at: null, balance: 1000,
    }),
    rotateUserKey: async () => ({ access_key: 'ek_new' }),
    adminInvites: async () => [],
    createInvite: async () => ({ id: 'inv1', code: 'iv_test', max_uses: 3, expires_at: null }),
    revokeInvite: async () => ({ status: 'revoked' }),
    adminTopups: async () => [],
    confirmTopup: async () => ({
      id: 'top1', user_id: 'u', amount_cents: 1000, amount_yuan: 10, credits: 1000,
      method: 'manual', status: 'paid' as const, note: '', created_at: '2026-01-01T00:00:00Z',
      paid_at: '2026-01-01T00:00:00Z', balance: 2000,
    }),
    cancelTopup: async () => ({
      id: 'top1', user_id: 'u', amount_cents: 1000, amount_yuan: 10, credits: 1000,
      method: 'manual', status: 'cancelled' as const, note: '', created_at: '2026-01-01T00:00:00Z',
      paid_at: null,
    }),
    auditLogs: async () => [],
    listTasks: async () => [TASK],
    getTask: async () => TASK,
    canvasTemplates: async () => [],
    createCanvasFromTemplate: async () => TASK,
    createTask: async () => TASK,
    timeline: async () => [],
    artifacts: async () => artifacts(),
    feedback: async () => [],
    constraints: async () => ({ effective: [], pending: [] }),
    platformConstraints: async () => ({ pack_id: 'amazon', version: '1', note: '', items: [] }),
    confirmConstraint: vi.fn(async () => ({ id: 'c1', text: '', rule: {}, status: 'effective' as const })),
    revokeConstraint: vi.fn(async () => ({ id: 'c1', text: '', rule: {}, status: 'revoked' as const })),
    utter: vi.fn(async () => ({ id: 'r1', task_id: 't1', agent_key: 'general', status: 'queued' as const, path: [], version_ids: [], error: null, cost: 0, held: 0 })),
    compact: async () => ({ status: 'skipped', reason: 'history_too_short' }),
    getRun: async () => { throw new Error('unused') },
    cancelRun: async () => { throw new Error('unused') },
    makeCurrent: async () => version({}),
    canvas: async () => ({
      task_id: 't1', version_id: null, theme: null, screens: [], edges: [], bounds: null,
      versions: [], notes: [],
    }),
    canvasPatch: vi.fn(async () => version({})),
    signal: async () => version({}),
    accept: async () => TASK,
    upload: async () => ({ upload_id: 'up1' }),
    uploadAny: async (file: File) => ({
      upload_id: `files/x/${file.name}`, name: file.name, mime: 'text/plain',
      size: file.size, readable: true, kind: 'file' as const,
    }),
    products: async () => [],
    product: async () => { throw new Error('unused') },
    loadSamples: async () => [],
    tools: async () => [{ name: 'edit_listing', version: '1', description: '按指示修改文案', side_effect: 'none', cost_credits: 5, timeout_s: 60, idempotent: true, agents: ['general'] }],
    tool: async () => { throw new Error('unused') },
    invokeTool: async () => ({ status: 'ok' as const, output: {}, error: null, cost: 0, duration_ms: 1 }),
    adminConfig: async () => ({ env: [], agents: [], note: '预览' }),
    saveAgentConfig: async () => ({ key: 'general', title: '通用 Agent', model: 'fake', system_prompt: '', preview: '', variables: [] }),
    saveModelProfile: async (key, body) => ({
      key, upstream_model: body.upstream_model ?? key, kind: 'planner',
      enabled: true, context_window_tokens: body.context_window_tokens ?? 0, capabilities: [],
    }),
    saveImageProfile: async () => ({ env: [], agents: [], note: '预览' }),
    saveRuntime: async () => ({ env: [], agents: [], note: '预览' }),
    adminLogs: async () => ({ tool_calls: [], llm_calls: [] }),
    skills: async () => [{
      id: 'listing-first-draft', description: '文案第一版', hash: 'abcdef0123456789', agents: [],
      tools: ['edit_listing'], audience: 'pdp' as const, revision: 0, source: 'file' as const,
    }],
    skill: async () => ({
      id: 'listing-first-draft', description: '文案第一版', hash: 'abcdef0123456789', agents: [],
      tools: ['edit_listing'], audience: 'pdp' as const, revision: 0, source: 'file' as const,
      body: '---\ndescription: 文案第一版\naudience: pdp\n---\n\n# 文案第一版\n',
    }),
    saveSkill: async (_id, body, baseRevision) => ({
      id: 'listing-first-draft', description: '文案第一版', hash: 'fedcba9876543210', agents: [],
      tools: ['edit_listing'], audience: 'pdp' as const, revision: baseRevision + 1,
      source: 'edited' as const, body,
    }),
    skillRevisions: async () => [],
    resetSkill: async () => ({
      id: 'listing-first-draft', description: '文案第一版', hash: 'abcdef0123456789', agents: [],
      tools: ['edit_listing'], audience: 'pdp' as const, revision: 1,
      source: 'restored' as const, body: '---\ndescription: 文案第一版\n---\n',
    }),
    getPreferences: async () => ({ body_md: '', revision: 0 }),
    putPreferences: async () => ({ body_md: '', revision: 1 }),
    subscribeRun,
  }
  return { ...api, ...over }
}

/** The auth gate resolves through a query; tests seed it so the shell renders on first paint. */
export const AUTH_OK: AuthStatus = {
  authenticated: true,
  dev_identity: true,
  user: { id: 'u', display_name: 'u', role: 'admin', balance: 1000 },
}

export const AUTH_ANON: AuthStatus = { authenticated: false, dev_identity: false }

/**
 * A client that reports "not signed in", matching `renderApp(..., {auth: AUTH_ANON})`.
 *
 * Seeding the query cache alone is not enough: the query refetches on mount, so the fake
 * client has to agree with the seed or the shell flashes back in mid-test.
 */
export function anonApi(over: Partial<ApiClient> = {}): ApiClient {
  return fakeApi({ authStatus: async () => AUTH_ANON, ...over })
}

export function renderApp(
  api: ApiClient,
  initial: Partial<NavState> = {},
  opts: { auth?: AuthStatus } = {},
) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 } } })
  qc.setQueryData(['auth', 'status'], opts.auth ?? AUTH_OK)
  return render(
    <ApiProvider client={api}>
      <QueryClientProvider client={qc}>
        <AuthProvider>
          <NavProvider initial={initial}>
            <ToastProvider>
              <App />
            </ToastProvider>
          </NavProvider>
        </AuthProvider>
      </QueryClientProvider>
    </ApiProvider>,
  )
}
