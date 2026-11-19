import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TASK, fakeApi, renderApp, turn, version } from './test-utils'
import type { ApiClient } from './api/client'
import type { CanvasModule, CanvasView, UtteranceBody } from './api/types'

afterEach(() => vi.restoreAllMocks())

describe('shell', () => {
  it('has the prototype entries and the registry pages', async () => {
    renderApp(fakeApi(), { view: 'home' })
    for (const name of ['通用 Agent', 'PDP Agent', '图片 Agent', '任务列表', 'Artifact', '商品与事实', 'Tool 登记', 'Skill 登记', '控制台']) {
      expect(screen.getByRole('button', { name })).toBeTruthy()
    }
    fireEvent.click(screen.getByRole('button', { name: 'Tool 登记' }))
    expect(await screen.findByText('edit_listing')).toBeTruthy()
    expect(screen.getByText(/登记表/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Skill 登记' }))
    expect(await screen.findByText('listing-first-draft')).toBeTruthy()
  })

  it('shows automation and the canvas agent as later placeholders', () => {
    renderApp(fakeApi(), { view: 'automation' })
    expect(screen.getByText(/后期能力，MVP 不做/)).toBeTruthy()
  })
})

describe('agent home', () => {
  it('starts from a centered chat box and lists PDP and image', async () => {
    renderApp(fakeApi(), { view: 'chat', taskId: null, agent: 'general' })
    expect(await screen.findByLabelText('消息输入')).toBeTruthy()
    expect(screen.queryByRole('button', { name: '开始' })).toBeNull()
    expect(screen.getByRole('button', { name: /白底主图/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /换成白底/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /从零写一套 PDP/ })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /亚马逊 PDP、商品图/ }))
    expect(await screen.findByRole('button', { name: /亚马逊 PDP 详情/ })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /主图、场景图、特写/ }))
    expect(await screen.findByRole('heading', { name: '纯提示词' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: '需要参考图' })).toBeTruthy()
  })
})

describe('chat thread', () => {
  const open = { view: 'chat' as const, taskId: 't1', agent: 'general' }

  it('rebuilds the conversation from the timeline: interpretations, rejection and cost', async () => {
    const t = turn({
      user: { text: '主图放大，再把颜色改成红色', target_slot: null, target_region: null, target_version_id: null },
      interpretations: [
        { feedback_id: 'f1', kind: 'parameter_patch', text: '主图放大', slot: 'main_image', region: null, status: 'applied', note: '', constraint_id: null, constraint_status: null },
        { feedback_id: 'f2', kind: 'new_constraint', text: '颜色不能改', slot: null, region: null, status: 'open', note: '', constraint_id: 'c1', constraint_status: 'pending' },
      ],
      versions: [{
        id: 'v3', slot: 'main_image', seq: 3, kind: 'image', status: 'rejected', is_current: false,
        content: { url: '/x.png' }, parent_content: null, params: {},
        evaluations: [{ evaluator_id: 'main_image.subject', passed: false, problems: ['主体被裁切'] }],
      }],
    })
    renderApp(fakeApi({ timeline: async () => [t] }), open)
    expect(await screen.findByText('一句话拆成了 2 条反馈：')).toBeTruthy()
    expect(screen.getByText(/v3 被拒绝/)).toBeTruthy()
    expect(screen.getByText(/主体被裁切/)).toBeTruthy()
    expect(screen.getByText(/冻结 20，返还 15/)).toBeTruthy()
    expect(screen.getByText(/确认前不生效/)).toBeTruthy()
  })

  it('offers the question options as buttons that send the reply', async () => {
    const utter = vi.fn(async () => ({ id: 'r9', task_id: 't1', agent_key: 'image', status: 'queued' as const, path: [], version_ids: [], error: null, cost: 0, held: 0 }))
    const t = turn({
      agent_key: 'image',
      human_input_requests: [{
        version: 1,
        kind: 'human_input_request',
        source: 'ask_question',
        request_id: 'run_x:ask',
        tool_call_id: 'run_x:ask',
        question: '这张图要呈现的具体商品是什么？',
        input_mode: 'single_choice',
        options: [
          { id: 'o0', label: '我先上传一张产品照', value: '我先上传一张产品照' },
          { id: 'o1', label: '用商品库里已保存的图', value: '用商品库里已保存的图' },
        ],
      }],
    })
    renderApp(fakeApi({
      timeline: async () => [t],
      utter,
      getTask: async () => ({ ...TASK, kind: 'image' as const, status: 'awaiting_user' as const, agent_key: 'image' }),
    }), { ...open, taskId: 't1', agent: 'image' })
    const btn = await screen.findByRole('button', { name: '我先上传一张产品照' })
    fireEvent.click(btn)
    await waitFor(() => expect(utter).toHaveBeenCalledWith('t1', expect.objectContaining({ text: '我先上传一张产品照' })))
  })

  it('shows a delivered version while the Run is still finishing', async () => {
    // The bug: a committed image plus a still-running Run rendered nothing but "正在思考",
    // so a finished picture looked like a hung job. A Version that exists is shown at once.
    const t = turn({
      agent_key: 'general',
      status: 'running',
      versions: [{
        id: 'v9', slot: 'main_image', seq: 1, kind: 'image', status: 'ok', is_current: true,
        content: { url: '/x.png', width: 400, height: 400 }, parent_content: null,
        params: {}, evaluations: [],
      }],
    })
    renderApp(fakeApi({ timeline: async () => [t] }), open)
    const card = await screen.findByRole('button', { name: /主图/ })
    expect(card.getAttribute('data-artifact')).toBe('image')
    expect(screen.queryByText(/正在思考/)).toBeNull()
  })

  it('renders follow-up chips that send the question as the next turn', async () => {
    // A follow-up is a new request the user did not type. It must be a different control from
    // `answer-option` (which answers the Agent's own question) and it must go through the same
    // send path, so the transcript stays the only record of the conversation.
    const utter = vi.fn(async () => ({ id: 'r10', task_id: 't1', agent_key: 'image', status: 'queued' as const, path: [], version_ids: [], error: null, cost: 0, held: 0 }))
    const t = turn({
      agent_key: 'image',
      answers: ['主图已生成，背景是纯白的。'],
      follow_ups: ['换成浅灰背景', '把商品放大一点'],
    })
    renderApp(fakeApi({ timeline: async () => [t], utter }), open)
    expect(await screen.findByText('接下来可以问')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '换成浅灰背景' }))
    await waitFor(() => expect(utter).toHaveBeenCalledWith('t1', expect.objectContaining({ text: '换成浅灰背景' })))
  })

  it('does not render follow-up chips on a turn that asked a question', async () => {
    // `ask_question` blocks the Run. Suggesting the next topic while a question is open would
    // invite the user to skip it, which is the confusion the two features are split to avoid.
    const t = turn({
      agent_key: 'image',
      follow_ups: [],
      human_input_requests: [{
        version: 1, kind: 'human_input_request', source: 'ask_question',
        request_id: 'r:ask', tool_call_id: 'r:ask',
        question: '这张图要呈现的具体商品是什么？',
        input_mode: 'single_choice',
        options: [{ id: 'o0', label: '我先上传一张产品照', value: '我先上传一张产品照' }],
      }],
    })
    renderApp(fakeApi({
      timeline: async () => [t],
      getTask: async () => ({ ...TASK, kind: 'image' as const, status: 'awaiting_user' as const, agent_key: 'image' }),
    }), { ...open, taskId: 't1', agent: 'image' })
    expect(await screen.findByText('这张图要呈现的具体商品是什么？')).toBeTruthy()
    expect(screen.queryByText('接下来可以问')).toBeNull()
  })

  it('confirming a pending constraint calls the API (it does not take effect by itself)', async () => {
    const confirm = vi.fn(async () => ({ id: 'c1', text: '', rule: {}, status: 'effective' as const }))
    const t = turn({
      interpretations: [{ feedback_id: 'f2', kind: 'new_constraint', text: '颜色不能改', slot: null, region: null, status: 'open', note: '', constraint_id: 'c1', constraint_status: 'pending' }],
    })
    renderApp(fakeApi({ timeline: async () => [t], confirmConstraint: confirm }), open)
    fireEvent.click(await screen.findByRole('button', { name: '确认' }))
    await waitFor(() => expect(confirm).toHaveBeenCalledWith('c1'))
  })

  it('sends the utterance bound to the clicked slot (target_slot)', async () => {
    const utter = vi.fn(async () => ({ id: 'r1', task_id: 't1', agent_key: 'general', status: 'queued' as const, path: [], version_ids: [], error: null, cost: 0, held: 0 }))
    renderApp(fakeApi({ utter }), { ...open, drawer: { kind: 'pdp' }, target: { slot: 'title', label: '标题' } })
    expect(await screen.findByText('目标：', { exact: false })).toBeTruthy()
    fireEvent.change(await screen.findByLabelText('消息输入'), { target: { value: '标题短一点' } })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))
    await waitFor(() => expect(utter).toHaveBeenCalled())
    const body = (utter.mock.calls[0] as unknown as [string, Record<string, unknown>])[1]
    expect(body).toMatchObject({ text: '标题短一点', target_slot: 'title', agent_id: 'general' })
  })

  it('opens the PDP drawer with the prototype tabs', async () => {
    renderApp(fakeApi(), { ...open, drawer: { kind: 'pdp' } })
    for (const tab of ['预览', '检查', '版本', '约束']) {
      expect(await screen.findByRole('tab', { name: tab }).catch(() => screen.getByText(tab))).toBeTruthy()
    }
    expect(screen.getAllByRole('button', { name: '接受当前 PDP', hidden: true }).length).toBeGreaterThan(0)
  })
})

describe('artifacts', () => {
  it('lists projects and does not offer a second place to create one', async () => {
    renderApp(fakeApi(), { view: 'artifacts' })
    expect(await screen.findByRole('heading', { name: /NKTMXY/ })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /新建 PDP/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /新建图片/ })).toBeNull()
    expect(screen.getByText(/新的项目在对应 Agent 里开始/)).toBeTruthy()
  })

  it('opens the existing preview instead of an empty drawer', async () => {
    renderApp(fakeApi(), { view: 'artifacts' })
    const card = (await screen.findByRole('heading', { name: /NKTMXY/ })).closest('button')
    fireEvent.click(card as HTMLElement)
    expect(await screen.findByRole('button', { name: '打开 PDP 预览' })).toBeTruthy()
  })
})

describe('products', () => {
  it('sends the product page into the PDP entry, not the general one', async () => {
    const sample = {
      id: 'p1', name: 'NKTMXY 迷你电动剃须刀', brand: 'NKTMXY', marketplace: 'amazon.com',
      mode: 'optimize' as const, facts: { attributes: {} }, listing: {},
      main_url: null, gallery_urls: [], created_at: '2026-01-01T00:00:00Z',
    }
    renderApp(fakeApi({
      products: async () => [sample],
      product: async () => ({ ...sample, tasks: [] }),
    }), { view: 'products', productId: 'p1' })
    fireEvent.click(await screen.findByRole('button', { name: '导入优化' }))
    // the PDP entry shows its own templates; the general entry would show the 2x3 catalog
    expect(await screen.findByText(/选一个模板，或直接说要改哪一块/)).toBeTruthy()
  })
})

describe('image studio', () => {
  it('turns every circled region into one utterance with target_slot, region and version', async () => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(
      { x: 0, y: 0, left: 0, top: 0, right: 400, bottom: 400, width: 400, height: 400, toJSON: () => ({}) } as DOMRect,
    )
    const utter = vi.fn(async () => ({ id: 'r1', task_id: 't1', agent_key: 'general', status: 'queued' as const, path: [], version_ids: [], error: null, cost: 0, held: 0 }))
    renderApp(
      fakeApi({
        utter,
        artifacts: async () => [{ artifact_id: 'a1', kind: 'image', slot: 'main_image', current_version_id: 'v2', versions: [version({}), version({ id: 'v2', seq: 2, origin: 'edited' })] }],
      }),
      { view: 'image', imageTaskId: 't1', imageSlot: 'main_image' },
    )
    const surface = await screen.findByTestId('mark-surface')
    fireEvent.pointerDown(surface, { clientX: 100, clientY: 100, pointerId: 1 })
    fireEvent.pointerUp(surface, { clientX: 300, clientY: 300, pointerId: 1 })
    const input = await screen.findByPlaceholderText('这一块要怎么改')
    fireEvent.change(input, { target: { value: '这里再亮一点' } })
    const panel = input.closest('.task-panel') as HTMLElement
    fireEvent.click(within(panel).getByRole('button', { name: '作为反馈提交' }))
    await waitFor(() => expect(utter).toHaveBeenCalledTimes(1))
    const body = (utter.mock.calls[0] as unknown as [string, Record<string, unknown>])[1]
    expect(body).toMatchObject({
      text: '这里再亮一点', target_slot: 'main_image', target_version_id: 'v2',
      target_region: { x: 0.25, y: 0.25, w: 0.5, h: 0.5 },
    })
  })

  it('refuses to submit a circle without a sentence', async () => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(
      { x: 0, y: 0, left: 0, top: 0, right: 400, bottom: 400, width: 400, height: 400, toJSON: () => ({}) } as DOMRect,
    )
    const utter = vi.fn()
    renderApp(fakeApi({ utter }), { view: 'image', imageTaskId: 't1', imageSlot: 'main_image' })
    const surface = await screen.findByTestId('mark-surface')
    fireEvent.pointerDown(surface, { clientX: 10, clientY: 10, pointerId: 1 })
    fireEvent.pointerUp(surface, { clientX: 200, clientY: 200, pointerId: 1 })
    const input = await screen.findByPlaceholderText('这一块要怎么改')
    fireEvent.click(within(input.closest('.task-panel') as HTMLElement).getByRole('button', { name: '作为反馈提交' }))
    expect(await screen.findByText('每个圈选都要写一句话')).toBeTruthy()
    expect(utter).not.toHaveBeenCalled()
  })
})

describe('file preview', () => {
  it('opens a successful html version in the preview frame', async () => {
    const html = version({
      id: 'vh', artifact_id: 'af', slot: 'page.html',
      content: { text: '<h1>夏季促销</h1>', filename: 'page.html', mime: 'text/html', media: 'html' },
    })
    const fileTask = { ...TASK, kind: 'file' as const, goal: '活动页', pdp_version_id: null }
    renderApp(fakeApi({
      getTask: async () => fileTask,
      artifacts: async () => [{ artifact_id: 'af', kind: 'file', slot: 'page.html', current_version_id: 'vh', versions: [html] }],
      timeline: async () => [turn({
        user: { text: '写一个 HTML 页面', target_slot: null, target_region: null, target_version_id: null },
        versions: [{
          id: 'vh', slot: 'page.html', seq: 1, kind: 'file', status: 'ok', is_current: true,
          content: html.content, parent_content: null, params: {}, evaluations: [],
        }],
      })],
    }), { view: 'chat', taskId: 't1', agent: 'general' })
    fireEvent.click(await screen.findByRole('button', { name: /page\.html/ }))
    expect(await screen.findByTitle('page.html')).toBeTruthy()
  })
})

describe('image templates', () => {
  it('fills the composer instead of generating on a pure-prompt template', async () => {
    const createTask = vi.fn()
    renderApp(fakeApi({ createTask }), { view: 'image', agent: 'image', imageTaskId: null })
    fireEvent.click(await screen.findByRole('button', { name: /白底主图/ }))
    const box = (await screen.findByLabelText('消息输入')) as HTMLTextAreaElement
    expect(box.value).toContain('纯白背景')
    expect(createTask).not.toHaveBeenCalled()
  })

  it('opens a reference dialog with the default prompt and an upload', async () => {
    renderApp(fakeApi(), { view: 'image', agent: 'image', imageTaskId: null })
    fireEvent.click(await screen.findByRole('button', { name: /换成白底/ }))
    expect(await screen.findByLabelText('图片提示词')).toBeTruthy()
    expect(screen.getByLabelText('上传参考图')).toBeTruthy()
    expect(screen.getByRole('button', { name: /生成图片/ })).toBeTruthy()
  })
})

describe('composer', () => {
  it('switches the task entry from the picker, not from the sentence', async () => {
    const utter = vi.fn(async () => ({ id: 'r1', task_id: 't1', agent_key: 'general', status: 'queued' as const, path: [], version_ids: [], error: null, cost: 0, held: 0 }))
    renderApp(fakeApi({
      agents: async () => [
        { key: 'general', title: '通用 Agent', description: '全部能力', tool_names: [], skill_ids: [], artifact_kinds: ['pdp', 'file'], workbench: 'general', task_kind: null },
        { key: 'amazon_pdp', title: 'PDP Agent', description: '亚马逊详情页', tool_names: [], skill_ids: [], artifact_kinds: ['pdp'], workbench: 'pdp', task_kind: 'pdp' },
      ],
      utter,
    }), { view: 'chat', taskId: 't1', agent: 'general' })
    fireEvent.click(await screen.findByRole('button', { name: '切换任务' }))
    fireEvent.click(screen.getByRole('option', { name: /PDP Agent/ }))
    const box = await screen.findByLabelText('消息输入')
    fireEvent.change(box, { target: { value: '只改标题' } })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))
    await waitFor(() => expect(utter).toHaveBeenCalledWith('t1', expect.objectContaining({ agent_id: 'amazon_pdp' })))
  })

  it('sends the chosen file with the message and clears it after sending', async () => {
    const utter = vi.fn(async () => ({ id: 'r1', task_id: 't1', agent_key: 'general', status: 'queued' as const, path: [], version_ids: [], error: null, cost: 0, held: 0 }))
    renderApp(fakeApi({ utter }), { view: 'chat', taskId: 't1', agent: 'general' })
    const picker = await screen.findByLabelText('上传文件')
    fireEvent.change(picker, { target: { files: [new File(['# 简报'], 'brief.md', { type: 'text/markdown' })] } })
    expect(await screen.findByText('brief.md')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('消息输入'), { target: { value: '按简报写' } })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))
    await waitFor(() => expect(utter).toHaveBeenCalledWith('t1', expect.objectContaining({
      attachment_ids: ['files/x/brief.md'],
    })))
  })

  it('narrows the Run when a slash skill is typed', async () => {
    const utter = vi.fn(async () => ({ id: 'r1', task_id: 't1', agent_key: 'general', status: 'queued' as const, path: [], version_ids: [], error: null, cost: 0, held: 0 }))
    renderApp(fakeApi({ utter }), { view: 'chat', taskId: 't1', agent: 'general' })
    fireEvent.change(await screen.findByLabelText('消息输入'), { target: { value: '/image-local-edit 把这圈改成白底' } })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))
    await waitFor(() => expect(utter).toHaveBeenCalledWith('t1', expect.objectContaining({ skill_id: 'image-local-edit' })))
  })
})

describe('image agent page', () => {
  it('is just the conversation until a first version exists', async () => {
    renderApp(fakeApi({
      getTask: async () => ({ ...TASK, kind: 'image' as const }),
      artifacts: async () => [{ artifact_id: 'ai', kind: 'image', slot: 'image', current_version_id: null, versions: [] }],
      timeline: async () => [],
    }), { view: 'image', imageTaskId: 't1', imageSlot: 'image' })
    expect(await screen.findByLabelText('Agent 输入')).toBeTruthy()
    expect(screen.queryByTestId('mark-surface')).toBeNull()
    expect(screen.queryByText(/还没有图片/)).toBeNull()
  })

  it('shows the canvas once a version exists', async () => {
    renderApp(fakeApi(), { view: 'image', imageTaskId: 't1', imageSlot: 'main_image' })
    expect(await screen.findByTestId('mark-surface')).toBeTruthy()
    expect(await screen.findByTestId('version-strip')).toBeTruthy()
    // Lightweight single-image preview: labelled as such, and not the canvas workspace.
    expect(document.querySelector('.img-preview-mark')?.textContent).toBe('图片预览')
    expect(document.querySelector('.canvas-page')).toBeNull()
    expect(document.querySelector('.canvas-dock')).toBeNull()
  })

  it('sends target_version_id for the strip focus, not only artifact current', async () => {
    const v1 = version({ id: 'v1', seq: 1, content: { url: '/v1.png', width: 400, height: 400 } })
    const v2 = version({ id: 'v2', seq: 2, parent_version_id: 'v1', content: { url: '/v2.png', width: 400, height: 400 } })
    const utter = vi.fn(async () => ({
      id: 'r1', task_id: 't1', agent_key: 'image', status: 'queued' as const,
      path: [], version_ids: [], error: null, cost: 0, held: 0,
    }))
    renderApp(fakeApi({
      utter,
      getTask: async () => ({ ...TASK, kind: 'image' as const }),
      artifacts: async () => [{
        artifact_id: 'a1', kind: 'image', slot: 'main_image', current_version_id: 'v2', versions: [v1, v2],
      }],
    }), { view: 'image', imageTaskId: 't1', imageSlot: 'main_image' })

    fireEvent.click(await screen.findByTestId('version-thumb-v1'))
    const box = await screen.findByLabelText('Agent 输入')
    fireEvent.change(box, { target: { value: '从 v1 再改一版' } })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))
    await waitFor(() => expect(utter).toHaveBeenCalledWith('t1', expect.objectContaining({
      text: '从 v1 再改一版', target_slot: 'main_image', target_version_id: 'v1',
    })))
  })

  it('lets the first sentence through without a base version', async () => {
    const utter = vi.fn(async (_taskId: string, _body: UtteranceBody) => ({
      id: 'r1', task_id: 't1', agent_key: 'image', status: 'queued' as const,
      path: [], version_ids: [], error: null, cost: 0, held: 0,
    }))
    renderApp(fakeApi({
      utter,
      getTask: async () => ({ ...TASK, kind: 'image' as const }),
      artifacts: async () => [{ artifact_id: 'ai', kind: 'image', slot: 'image', current_version_id: null, versions: [] }],
      timeline: async () => [],
    }), { view: 'image', imageTaskId: 't1', imageSlot: 'image' })
    const box = await screen.findByLabelText('Agent 输入')
    fireEvent.change(box, { target: { value: '做一个纯白背景的主图' } })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))
    await waitFor(() => expect(utter).toHaveBeenCalledWith('t1', expect.objectContaining({
      text: '做一个纯白背景的主图', target_slot: 'image',
    })))
    expect(utter.mock.calls[0]?.[1]).not.toHaveProperty('target_version_id')
  })

  it('turns the send button into Stop while a Run is live, and shows the stage', async () => {
    // The reported gap: the button stayed a greyed-out Send, so the wait looked broken and
    // there was no way to cancel.
    const cancelRun = vi.fn(async () => ({
      id: 'r1', task_id: 't1', agent_key: 'image', status: 'cancelled' as const,
      path: [], version_ids: [], error: null, cost: 0, held: 0,
    }))
    let emit: (type: string, data: unknown) => void = () => {}
    const subscribeRun: ApiClient['subscribeRun'] = (_id, onEvent) => {
      emit = onEvent
      return () => {}
    }
    renderApp(fakeApi({
      cancelRun,
      subscribeRun,
      utter: async () => ({
        id: 'r1', task_id: 't1', agent_key: 'image', status: 'queued' as const,
        path: [], version_ids: [], error: null, cost: 0, held: 0,
      }),
    }), { view: 'image', imageTaskId: 't1', imageSlot: 'main_image' })

    const box = await screen.findByLabelText('Agent 输入')
    fireEvent.change(box, { target: { value: '再亮一点' } })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))

    // The same primary button, now stopping the Run.
    const stop = await screen.findByRole('button', { name: '停止生成' })
    fireEvent.click(stop)
    await waitFor(() => expect(cancelRun).toHaveBeenCalledWith('r1'))

    // A live step says which stage it is in, so the wait is legible.
    await act(async () => { emit('step', { stage: 'running', detail: 'generate_product_image:main_image' }) })
    expect(await screen.findByText(/正在生成图片|正在调用工具/)).toBeTruthy()
  })
})

describe('canvas agent page', () => {
  const THEME = {
    colors: { bg: '#FFFFFF', fg: '#0D0D0D', accent: '#10A37F' },
    fonts: { display: 'Georgia, serif', body: 'Inter, sans-serif' },
    radius: 12,
  }
  const empty = async () => ({
    task_id: 't1', version_id: null, theme: null, screens: [], edges: [], bounds: null,
    versions: [], notes: [],
  })
  const one = async (): Promise<CanvasView> => ({
    task_id: 't1',
    artifact_id: 'ca1',
    version_id: 'cv1',
    seq: 1,
    theme: THEME,
    screens: [{
      id: 's1', name: '首屏', pos: { x: 0, y: 0 }, frame: { width: 1464, height: 600 },
      modules: [
        {
          id: 'm1', kind: 'text' as const, name: '首屏标题',
          rect: { x: 0.04, y: 0.1, w: 0.4, h: 0.2 },
          style: { size: 44, weight: 600, align: 'left' as const, color: 'fg', font: 'display' },
          text: 'Close shave',
        },
        {
          id: 'm2', kind: 'image' as const, name: '产品主图',
          rect: { x: 0.5, y: 0.1, w: 0.4, h: 0.8 },
          style: { fit: 'contain' as const, background: 'white' as const },
          slot: 'canvas_image_1', version_id: null, url: null,
        },
      ],
    }],
    edges: [],
    bounds: { x: 0, y: 0, width: 1464, height: 600 },
    versions: [{ id: 'cv1', seq: 1, status: 'ok' as const, created_by: 'agent' as const, origin: 'generated', created_at: '2026-01-01T00:00:00Z', is_current: true }],
    notes: [],
  })
  const variant = async () => {
    const base = await one()
    const first = base.screens[0]!
    const copies = [1, 2].map((i) => ({
      id: `s1-v${i}`, name: `首屏 · 变体 ${i}`, pos: { x: 1560 * i, y: 0 },
      frame: { width: 1464, height: 600 },
      modules: first.modules.map((m) => ({ ...m, id: `s1-v${i}-${m.id}` })),
      variant_of: 's1', variant_label: `变体 ${i}`,
    }))
    return {
      ...base,
      screens: [...base.screens, ...copies],
      bounds: { x: 0, y: 0, width: 1464 * 3 + 192, height: 600 },
    }
  }
  const canvasTask = { ...TASK, kind: 'canvas' as const, agent_key: 'canvas' }

  it('opens on a project list: existing canvases, or a new blank one', async () => {
    const createTask = vi.fn(async () => ({ ...canvasTask, id: 'c-new', goal: '未命名画布' }))
    renderApp(fakeApi({
      listTasks: async () => [{ ...canvasTask, id: 'c9', goal: '咖啡店海报' }],
      createTask,
    }), { view: 'canvas', agent: 'canvas', canvasTaskId: null })
    const home = await screen.findByTestId('canvas-home')
    expect(await within(home).findByRole('button', { name: /咖啡店海报/ })).toBeTruthy()
    expect(within(home).getByRole('button', { name: /新建画布/ })).toBeTruthy()
    // The workspace is not open yet: no board, no prompt dock.
    expect(screen.queryByTestId('canvas-surface')).toBeNull()
    expect(screen.queryByLabelText('Agent 输入')).toBeNull()

    fireEvent.click(within(home).getByRole('button', { name: /新建画布/ }))
    await waitFor(() => expect(createTask).toHaveBeenCalledWith(expect.objectContaining({
      agent_id: 'canvas', kind: 'canvas',
    })))
  })

  it('opens a template whose pictures already show their prompts and a reference line', async () => {
    const createCanvasFromTemplate = vi.fn(async () => ({
      ...canvasTask, id: 'c-tpl', goal: '静物与夜景',
    }))
    const board = async () => ({
      ...(await one()),
      screens: [{
        id: 's1', name: '静物', pos: { x: 0, y: 0 },
        frame: { width: 1280, height: 900 },
        modules: [
          {
            id: 'm-morning', kind: 'image' as const, name: '晨光静物',
            rect: { x: 0.04, y: 0.06, w: 0.44, h: 0.56 },
            style: { fit: 'cover' as const, background: 'white' as const },
            slot: 'canvas_image_1', prompt: '深色木桌上一杯拿铁',
            version_id: 'iv1', url: '/api/blobs/a.png', width: 768, height: 768,
          },
          {
            id: 'm-night', kind: 'image' as const, name: '夜景',
            rect: { x: 0.52, y: 0.06, w: 0.44, h: 0.56 },
            style: { fit: 'cover' as const, background: 'white' as const },
            slot: 'canvas_image_2', prompt: '改成夜晚暖光', ref: 'm-morning',
            version_id: 'iv2', url: '/api/blobs/b.png', width: 768, height: 768,
          },
        ],
      }],
    })
    renderApp(fakeApi({
      listTasks: async () => [],
      canvasTemplates: async () => [{
        id: 'morning-night', title: '静物与夜景', blurb: '晨光已经画好', goal: '静物与夜景',
      }],
      createCanvasFromTemplate,
      getTask: async () => ({ ...canvasTask, id: 'c-tpl', goal: '静物与夜景' }),
      canvas: board,
    }), { view: 'canvas', agent: 'canvas', canvasTaskId: null })
    const home = await screen.findByTestId('canvas-home')
    fireEvent.click(await within(home).findByRole('button', { name: /静物与夜景/ }))
    expect(await screen.findByTestId('canvas-ref-m-morning-m-night')).toBeTruthy()
    expect(screen.getByText('深色木桌上一杯拿铁')).toBeTruthy()
    expect(screen.getByText('改成夜晚暖光')).toBeTruthy()
    await waitFor(() => expect(createCanvasFromTemplate).toHaveBeenCalledWith('morning-night'))
  })

  it('opens an existing canvas project into the workspace', async () => {
    renderApp(fakeApi({
      listTasks: async () => [{ ...canvasTask, goal: '咖啡店海报' }],
      getTask: async () => ({ ...canvasTask, goal: '咖啡店海报' }),
      canvas: one,
    }), { view: 'canvas', agent: 'canvas', canvasTaskId: null })
    const home = await screen.findByTestId('canvas-home')
    fireEvent.click(await within(home).findByRole('button', { name: /咖啡店海报/ }))
    expect(await screen.findByTestId('canvas-screen-s1')).toBeTruthy()
    expect(document.querySelector('.canvas-app')).toBeTruthy()
    expect(document.querySelector('.imgpage')).toBeNull()
  })

  it('shows the workspace, including a blank board, as soon as a canvas is open', async () => {
    renderApp(fakeApi({ getTask: async () => canvasTask, canvas: empty }), {
      view: 'canvas', agent: 'canvas', canvasTaskId: 't1',
    })
    expect(await screen.findByTestId('canvas-surface')).toBeTruthy()
    expect(screen.getByLabelText('Agent 输入')).toBeTruthy()
    expect(screen.getByText(/空白画板/)).toBeTruthy()
    expect(screen.queryByTestId('canvas-screen-s1')).toBeNull()
  })

  it('renders screens and their modules once the board exists', async () => {
    renderApp(fakeApi({ getTask: async () => canvasTask, canvas: one }), {
      view: 'canvas', agent: 'canvas', canvasTaskId: 't1',
    })
    expect(await screen.findByTestId('canvas-screen-s1')).toBeTruthy()
    expect(screen.getByText('Close shave')).toBeTruthy()
    expect(screen.getByTestId('canvas-module-m2')).toBeTruthy()
    // No picture yet: a placeholder card that says so, not a borrowed image.
    expect(within(screen.getByTestId('canvas-module-m2')).getByText('待生成')).toBeTruthy()
  })

  it('puts the composer in a dock over the board, and lets the thread collapse', async () => {
    const t = turn({
      user: { text: '做一版商品首屏', target_slot: null, target_region: null, target_version_id: null },
      versions: [{
        id: 'cv1', slot: 'canvas', seq: 1, kind: 'canvas', status: 'ok', is_current: true,
        content: {}, parent_content: null, params: {}, evaluations: [],
      }],
    })
    renderApp(fakeApi({
      getTask: async () => canvasTask, canvas: one, timeline: async () => [t],
    }), { view: 'canvas', agent: 'canvas', canvasTaskId: 't1' })

    // The board is the page. Conversation is a glass card, not a column beside the board.
    expect(await screen.findByTestId('canvas-surface')).toBeTruthy()
    expect(document.querySelector('.canvas-page.is-docked')).toBeTruthy()
    const chat = document.querySelector('.canvas-chat')
    expect(chat).toBeTruthy()
    expect(chat?.classList.contains('is-open')).toBe(true)
    // The composer lives in the bottom dock, not in the conversation panel.
    const input = screen.getByLabelText('Agent 输入')
    expect(input.closest('.canvas-dock')).toBeTruthy()
    expect(input.closest('.canvas-chat')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: /对话/ }))
    await waitFor(() => {
      expect(document.querySelector('.canvas-chat')?.classList.contains('is-open')).toBe(false)
    })
    // Collapsing hides the history only: the composer is still there to type into.
    expect(screen.getByLabelText('Agent 输入')).toBeTruthy()
  })

  it('opens the inspector as a floating card, not a column that narrows the board', async () => {
    renderApp(fakeApi({ getTask: async () => canvasTask, canvas: one }), {
      view: 'canvas', agent: 'canvas', canvasTaskId: 't1',
    })
    const mod = await screen.findByTestId('canvas-module-m1')
    fireEvent.pointerDown(mod, { clientX: 10, clientY: 10, pointerId: 1 })
    fireEvent.pointerUp(mod, { clientX: 10, clientY: 10, pointerId: 1 })
    const inspector = await waitFor(() => {
      const el = document.querySelector('.canvas-wb-inspector')
      expect(el).toBeTruthy()
      return el as HTMLElement
    })
    expect(inspector.getAttribute('data-open')).toBe('true')
    // It sits inside the board body, so it overlays the surface instead of taking width.
    expect(inspector.closest('.canvas-wb-body')).toBeTruthy()
    expect(await screen.findByLabelText('文案')).toBeTruthy()
  })

  it('shows the module inspector and submits a text change as one patch', async () => {
    const canvasPatch = vi.fn(async () => version({}))
    renderApp(fakeApi({ getTask: async () => canvasTask, canvas: one, canvasPatch }), {
      view: 'canvas', agent: 'canvas', canvasTaskId: 't1',
    })
    const mod = await screen.findByTestId('canvas-module-m1')
    fireEvent.pointerDown(mod, { clientX: 10, clientY: 10, pointerId: 1 })
    fireEvent.pointerUp(mod, { clientX: 10, clientY: 10, pointerId: 1 })
    const box = await screen.findByLabelText('文案')
    fireEvent.change(box, { target: { value: 'New headline' } })
    fireEvent.blur(box)
    await waitFor(() => expect(canvasPatch).toHaveBeenCalledWith('cv1', [
      { op: 'set_text', screen: 's1', id: 'm1', text: 'New headline' },
    ]))
  })

  it('offers to keep one variant and drops the others through one patch', async () => {
    const canvasPatch = vi.fn(async () => version({}))
    renderApp(fakeApi({ getTask: async () => canvasTask, canvas: variant, canvasPatch }), {
      view: 'canvas', agent: 'canvas', canvasTaskId: 't1',
    })
    expect(await screen.findByTestId('canvas-screen-s1-v1')).toBeTruthy()
    expect(screen.getByTestId('canvas-screen-s1-v2')).toBeTruthy()
    const keep = within(screen.getByTestId('canvas-screen-s1-v2'))
      .getByRole('button', { name: '保留这个' })
    fireEvent.click(keep)
    await waitFor(() => expect(canvasPatch).toHaveBeenCalledWith('cv1', [
      { op: 'keep_variant', id: 's1-v2' },
    ]))
  })

  it('lets the user read and change a picture module prompt', async () => {
    const canvasPatch = vi.fn(async () => version({}))
    const board = await one()
    const picture: CanvasModule = { ...board.screens[0]!.modules[1]!, prompt: '白底，居中' }
    board.screens[0]!.modules[1] = picture
    renderApp(fakeApi({
      getTask: async () => canvasTask,
      canvas: async () => board,
      canvasPatch,
    }), { view: 'canvas', agent: 'canvas', canvasTaskId: 't1' })

    const mod = await screen.findByTestId('canvas-module-m2')
    fireEvent.pointerDown(mod, { clientX: 10, clientY: 10, pointerId: 1 })
    fireEvent.pointerUp(mod, { clientX: 10, clientY: 10, pointerId: 1 })
    const box = await screen.findByLabelText('提示词')
    expect((box as HTMLTextAreaElement).value).toBe('白底，居中')
    fireEvent.change(box, { target: { value: '纯白无缝背景' } })
    fireEvent.blur(box)
    await waitFor(() => expect(canvasPatch).toHaveBeenCalledWith('cv1', [
      { op: 'set_prompt', screen: 's1', id: 'm2', prompt: '纯白无缝背景' },
    ]))
  })

  it('sends a sentence bound to the canvas, not the whole task', async () => {
    const utter = vi.fn(async (_taskId: string, _body: UtteranceBody) => ({
      id: 'r1', task_id: 't1', agent_key: 'canvas', status: 'queued' as const,
      path: [], version_ids: [], error: null, cost: 0, held: 0,
    }))
    renderApp(fakeApi({ getTask: async () => canvasTask, canvas: one, utter }), {
      view: 'canvas', agent: 'canvas', canvasTaskId: 't1',
    })
    const box = await screen.findByLabelText('Agent 输入')
    fireEvent.change(box, { target: { value: '标题再大一点' } })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))
    await waitFor(() => expect(utter).toHaveBeenCalledWith('t1', expect.objectContaining({
      text: '标题再大一点', target_slot: 'canvas', agent_id: 'canvas',
    })))
  })
})

describe('skills', () => {
  it('lists skills with their audience and opens an editable body', async () => {
    renderApp(fakeApi(), { view: 'skills' })
    fireEvent.click(await screen.findByText('listing-first-draft'))
    expect(await screen.findByLabelText('Skill 正文')).toBeTruthy()
    expect(screen.getByText(/保存写入数据库修订/)).toBeTruthy()
  })

  it('saves a new revision and shows it', async () => {
    const saveSkill = vi.fn(async (_id: string, body: string, base: number) => ({
      id: 'listing-first-draft', description: '文案第一版', hash: 'new', agents: [],
      tools: ['edit_listing'], audience: 'pdp' as const, revision: base + 1,
      source: 'edited' as const, body,
    }))
    renderApp(fakeApi({ saveSkill }), { view: 'skills', skillId: 'listing-first-draft' })
    const editor = await screen.findByLabelText('Skill 正文')
    fireEvent.change(editor, { target: { value: '---\ndescription: 文案第一版\n---\n\n改过\n' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => expect(saveSkill).toHaveBeenCalledWith('listing-first-draft', expect.stringContaining('改过'), 0))
    expect(await screen.findByText('r1 · edited')).toBeTruthy()
  })

  it('reloads instead of overwriting when someone else saved first', async () => {
    const stale = vi.fn(async () => { throw new Error('这个 Skill 已被改过（当前修订 2），重新加载后再保存') })
    renderApp(fakeApi({ saveSkill: stale }), { view: 'skills', skillId: 'listing-first-draft' })
    const editor = await screen.findByLabelText('Skill 正文')
    fireEvent.change(editor, { target: { value: '---\ndescription: x\n---\n\n我的改动\n' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    expect(await screen.findByText('保存被拒绝')).toBeTruthy()
    expect(screen.getByRole('button', { name: '放弃我的改动，加载最新' })).toBeTruthy()
  })
})
