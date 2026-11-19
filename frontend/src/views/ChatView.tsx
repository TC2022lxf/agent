import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { FilePanel } from '../components/file/FilePanel'
import type { StagedFile } from '../components/chat/attachments'
import { ImagePanel } from '../components/image/ImagePanel'
import { AgentHome } from '../components/chat/AgentHome'
import { Composer } from '../components/chat/Composer'
import { EVENT_TEXT, Turn } from '../components/chat/Turn'
import { PdpPanel } from '../components/pdp/PdpPanel'
import { claimBoot } from '../lib/boot'
import { lastHumanInput, parseHumanInputEvent } from '../lib/humanInput'
import { STATUS_LABEL, canHandle, slotLabel, taskKindLabel } from '../lib/labels'
import { progressOf } from '../lib/progress'
import { useApi } from '../state/api-context'
import { useNav } from '../state/nav'
import { useToast } from '../state/toast'
import { useRunTracker } from '../state/useRunTracker'
import { keys, useRefreshTask, useTaskData } from '../state/useTaskData'

const imageSlotOf = (arts: { kind: string; slot: string | null; current_version_id: string | null }[]) =>
  arts.find((a) => a.kind === 'image' && a.current_version_id && a.slot)?.slot ?? 'image'
const fileSlotOf = (arts: { kind: string; slot: string | null; current_version_id: string | null }[]) =>
  arts.find((a) => a.kind === 'file' && a.current_version_id && a.slot)?.slot ?? 'page.html'

/** Chat + artifact drawer. The same view serves the general agent and the PDP agent (decisions/0010). */
export function ChatView() {
  const api = useApi()
  const qc = useQueryClient()
  const toast = useToast()
  const { nav, go, openDrawer } = useNav()
  const { agent, taskId, drawer, target } = nav
  const agents = useQuery({ queryKey: ['agents'], queryFn: () => api.agents() })
  const info = agents.data?.find((a) => a.key === agent)
  const { task, timeline, artifacts } = useTaskData(taskId)
  const refresh = useRefreshTask(taskId)
  const tracker = useRunTracker(taskId, agent)
  const [reasoning, setReasoning] = useState(false)
  const skills = useQuery({ queryKey: ['skills', agent], queryFn: () => api.agentSkills(agent) })
  const products = useQuery({ queryKey: keys.products, queryFn: () => api.products(), enabled: !!nav.productId })
  const product = products.data?.find((p) => p.id === nav.productId)
  const [starting, setStarting] = useState(false)
  const end = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const boot = nav.bootText
    if (!taskId || !boot) return
    if (!claimBoot(`chat:${taskId}:${boot}`)) return
    go({ bootText: null })
    void tracker.send({ text: boot })
  }, [go, nav.bootText, taskId, tracker])

  const turns = timeline.data ?? []
  const pendingHuman = useMemo(() => {
    for (let i = tracker.events.length - 1; i >= 0; i -= 1) {
      const parsed = parseHumanInputEvent(tracker.events[i]?.data)
      if (parsed) return parsed
    }
    const last = turns.at(-1)
    return last ? lastHumanInput(last) : null
  }, [tracker.events, turns])
  useEffect(() => { end.current?.scrollIntoView?.({ block: 'end' }) }, [turns.length, tracker.events.length])

  const t = task.data
  const awaiting = t?.status === 'awaiting_user'
  const busy = tracker.running || turns.some((x) => x.status === 'queued' || x.status === 'running')
  const lastEvent = tracker.events.at(-1)?.type
  const drawerOpen = drawer !== null && !!t
  /** A drawer is a preview of something that exists. No version yet: nothing to preview. */
  const hasImage = (artifacts.data ?? []).some(
    (a) => a.kind === 'image' && a.current_version_id,
  )
  const hasFile = (artifacts.data ?? []).some(
    (a) => a.kind === 'file' && a.current_version_id,
  )
  const hasPdp = t?.kind === 'pdp'
    || (t?.kind === 'general' && (artifacts.data ?? []).some((a) => a.kind === 'pdp'))
  const imageSlot = drawer?.kind === 'image' && hasImage ? (drawer.slot ?? 'main_image') : null
  const hasCanvas = (artifacts.data ?? []).some((a) => a.kind === 'canvas' && a.current_version_id)

  const openCanvas = (id: string | null) => {
    if (!id) return
    go({ view: 'canvas', agent: 'canvas', canvasTaskId: id, bootText: null })
  }

  const accept = async () => {
    if (!taskId) return
    await api.accept(taskId)
    await refresh()
    toast('已接受当前 PDP')
  }
  const decide = (kind: 'confirm' | 'revoke') => async (id: string) => {
    await (kind === 'confirm' ? api.confirmConstraint(id) : api.revokeConstraint(id))
    await refresh()
  }

  const send = (text: string, hint?: 'constraint' | 'preference', skillId?: string, attachments?: string[], answersRequestId?: string) => {
    const cur = artifacts.data?.find((a) => a.slot === target?.slot)?.current_version_id ?? undefined
    void tracker.send({
      text,
      reasoning,
      ...(target ? { target_slot: target.slot, target_version_id: target.versionId ?? cur } : {}),
      ...(hint ? { client_hint: hint } : {}),
      ...(skillId ? { skill_id: skillId } : {}),
      ...(attachments && attachments.length > 0 ? { attachment_ids: attachments } : {}),
      ...(answersRequestId ? { answers_request_id: answersRequestId } : {}),
    })
    go({ target: null })
  }

  const attachFiles = async (files: File[]): Promise<StagedFile[]> => {
    const staged: StagedFile[] = []
    for (const file of files) {
      try {
        const up = await api.uploadAny(file)
        staged.push({
          upload_id: up.upload_id, name: up.name, mime: up.mime,
          size: up.size, readable: up.readable, kind: up.kind,
        })
      } catch (e) {
        toast(e instanceof Error ? e.message : `${file.name} 上传失败`)
      }
    }
    return staged
  }

  /** Switch the entry for this Task. The next Run records the new Agent key; the Task stays. */
  const switchAgent = (key: string) => {
    if (key === agent) return
    go({ agent: key })
    if (key === 'image' && t?.kind === 'image') {
      go({ view: 'image', agent: 'image', imageTaskId: taskId, imageSlot: 'image', bootText: null })
      return
    }
    toast(`下一轮由 ${agents.data?.find((a) => a.key === key)?.title ?? key} 处理`)
  }

  /** Only entries that can work on this Task's kind; the backend would answer 400 otherwise. */
  const usableAgents = (agents.data ?? []).filter((a) => {
    if (!t) return true
    return canHandle(a.artifact_kinds, t.kind)
  })

  /** Same conversation, different output: bind the next message to the image slot. */
  const intent = (slot: 'image') => {
    go({ target: { slot, label: slot === 'image' ? '图片' : slot } })
    toast('下一句会生成或修改图片，上下文不变')
  }

  const start = async (text: string, kind: 'pdp' | 'image' | 'file' | 'general', file?: File | null) => {
    setStarting(true)
    try {
      const upload = file ? await api.upload(file) : null
      if (kind === 'image') {
        const created = await api.createTask({
          agent_id: agent === 'image' ? 'image' : 'general',
          kind: 'image',
          goal: text.slice(0, 80),
          upload_id: upload?.upload_id,
          product_id: product?.id,
        })
        await qc.invalidateQueries({ queryKey: keys.tasks })
        go({ view: 'image', agent: 'image', imageTaskId: created.id, imageSlot: 'image', taskId: null, bootText: text })
        return
      }
      const created = await api.createTask({
        agent_id: agent,
        kind: kind === 'file' ? 'file' : kind === 'general' ? 'general' : 'pdp',
        goal: text.slice(0, 80),
        product_id: product?.id,
        import_product: product?.mode === 'optimize' ? true : undefined,
      })
      await qc.invalidateQueries({ queryKey: keys.tasks })
      // No drawer yet: there is nothing to preview until the Agent writes a first version.
      go({ view: 'chat', agent, taskId: created.id, target: null, bootText: text, drawer: null })
    } catch (e) {
      toast(e instanceof Error ? e.message : '创建失败')
      setStarting(false)
    }
  }

  if (!taskId) {
    const mode = agent === 'amazon_pdp' ? 'pdp' : 'general'
    const title = mode === 'pdp' ? 'PDP Agent' : (info?.title ?? '通用 Agent')
    return (
      <section className="view is-active">
        <AgentHome mode={mode} title={title}
          lede={mode === 'pdp' ? '选一个模板，或直接说要改哪一块。' : '选一件要做的事，或直接说。'}
          placeholder={mode === 'pdp' ? '例如：把标题改短，五点保持不变' : '例如：给这把剃须刀做一套 PDP'}
          productLine={product ? `将使用商品「${product.name}」${product.mode === 'optimize' ? '，并导入已有 Listing' : ''}` : undefined}
          pending={starting}
          onText={(text) => void start(text, mode === 'general' ? 'general' : 'pdp')}
          onPdp={(text) => void start(text, 'pdp')}
          onFile={mode === 'general' ? (text) => void start(text, 'general') : undefined}
          onImage={(text, file) => void start(text, 'image', file)} />
      </section>
    )
  }

  const drawerTitle = drawer?.kind === 'image'
    ? `${imageSlot ? slotLabel(imageSlot) : '图片'} · 图像工作台`
    : drawer?.kind === 'file' ? `${drawer.slot ?? '文件'} · 预览` : 'PDP 预览'
  const drawerPurpose = drawer?.kind === 'image'
    ? '看当前版本和参数，检查规则；圈选局部请进入图片页。'
    : drawer?.kind === 'file'
      ? 'HTML、Markdown 和表格在这里预览。PDF、图片和音视频用浏览器打开。其余文件只下载。HTML 写入失败时停在源码。'
      : '点预览里的区域，下一句话只会改那个槽位。'

  return (
    <section className={`view chat-view is-active${drawerOpen ? ' drawer-open' : ''}`}>
      <div className="chat-column">
        <div className="x-taskbar">
          {t ? (
            <>
              <div className="x-tb-l">
                <b>{t.goal || '未命名任务'}</b>
                {t.meta.product && <span className="x-chip-s">{t.meta.product.brand} · {t.meta.product.name}</span>}
                <span className="x-chip-s">{taskKindLabel(t.kind)}</span>
                <span className={`x-state${awaiting ? ' wait' : t.status === 'accepted' ? ' done' : ''}`}>{STATUS_LABEL[t.status] ?? t.status}</span>
              </div>
              <div className="x-tb-r">
                {t.kind !== 'image' && canHandle(info?.artifact_kinds ?? [], 'general') && (
                  <button type="button" className="btn btn-secondary btn-sm" onClick={() => intent('image')}>生成图片</button>
                )}
                {hasPdp && (
                  <button type="button" className="btn btn-secondary btn-sm" onClick={() => openDrawer(drawerOpen ? null : { kind: 'pdp' })}>
                    {drawerOpen ? '收起预览' : '打开 PDP 预览'}
                  </button>
                )}
                {hasPdp && awaiting && <button type="button" className="btn btn-teal btn-sm" onClick={() => void accept()}>接受当前 PDP</button>}
              </div>
            </>
          ) : (
            <div className="x-tb-l"><b>新会话</b><span className="x-chip-s">{info?.title ?? agent}</span></div>
          )}
        </div>
        <div className="artifact-focus-bar" aria-live="polite">
          <span className="focus-pulse" aria-hidden="true" />
          <span className="artifact-focus-label">目标：<strong>{target ? target.label : '整个任务'}</strong></span>
          <span className="artifact-focus-hint">下一句话只会改这个槽位（target_slot）</span>
        </div>
        <div className="chat-scroll">
          <div className="chat-thread">
            {turns.length === 0 && !timeline.isLoading ? (
              <article className="msg">
                <div className="msg-avatar ai">AI</div>
                <div className="msg-bubble">
                  <p className="msg-text">任务已创建。{t?.meta.product ? '导入的内容已作为第一版，可以直接说意见。' : '告诉我你想做什么。'}</p>
                  {hasPdp && <p><button type="button" className="btn btn-secondary btn-sm" onClick={() => openDrawer({ kind: 'pdp' })}>打开 PDP 预览</button></p>}
                  {hasCanvas && <p><button type="button" className="btn btn-secondary btn-sm" onClick={() => openCanvas(taskId)}>打开画布</button></p>}
                  {hasImage && <p><button type="button" className="btn btn-secondary btn-sm" onClick={() => openDrawer({ kind: 'image', slot: imageSlotOf(artifacts.data ?? []) })}>打开图像工作台</button></p>}
                  {hasFile && <p><button type="button" className="btn btn-secondary btn-sm" onClick={() => openDrawer({ kind: 'file', slot: fileSlotOf(artifacts.data ?? []) })}>打开文件预览</button></p>}
                  {t?.kind === 'general' && <p className="x-sub">这是一个通用任务：写文件和生成图片都在同一段对话里，成果各自成为版本。</p>}
                </div>
              </article>
            ) : null}
            {turns.map((turn) => (
              <Turn key={turn.run_id} turn={turn} drawer={drawer}
                activeEvent={tracker.running && turn === turns.at(-1) && lastEvent ? EVENT_TEXT[lastEvent] ?? lastEvent : null}
                liveEvents={tracker.running && turn === turns.at(-1) ? tracker.events : []}
                pendingHumanRequestId={
                  awaiting && pendingHuman && turn === turns.at(-1) ? pendingHuman.request_id : null
                }
                answersEnabled={!busy && turn === turns.at(-1)}
                onOpen={openDrawer} onConfirm={(id) => void decide('confirm')(id)} onIgnore={(id) => void decide('revoke')(id)}
                onAnswer={(text) => send(text, undefined, undefined, undefined, pendingHuman?.request_id)}
                onUpload={(file) => void (async () => {
                  // A picture the Agent asked for: upload it, then send it as the reply to that
                  // request, so the next Run continues the work instead of starting over.
                  const staged = await attachFiles([file])
                  const ids = staged.map((s) => s.upload_id)
                  if (ids.length > 0) send('这是你要的图片', undefined, undefined, ids, pendingHuman?.request_id)
                })()}
                onOpenCanvas={() => go({
                  view: 'canvas', agent: 'canvas', canvasTaskId: taskId, bootText: null,
                })} />
            ))}
            {tracker.error && <p className="x-fail">{tracker.error}</p>}
            <div ref={end} />
          </div>
        </div>
        {t && (
          <Composer running={tracker.running} disabled={busy || t.status === 'accepted'} target={target}
            progress={tracker.running ? progressOf(tracker.events).text : undefined}
            skills={skills.data ?? []} onClearTarget={() => go({ target: null })}
            agents={usableAgents} agentKey={agent} onAgent={switchAgent}
            onAttach={attachFiles}
            onSend={send}
            reasoning={reasoning} onReasoning={setReasoning}
            onCompact={() => {
              if (!taskId) return
              void api.compact(taskId).then((r) => toast(r.status === 'ok' ? '已总结到这里' : '对话还太短'))
                .catch((e: unknown) => toast(e instanceof Error ? e.message : '暂时不能总结'))
            }}
            onCancel={() => void tracker.cancel()} />
        )}
      </div>
      <aside className="artifact-drawer" aria-hidden={!drawerOpen} aria-label="Artifact 编辑工作台">
        <header className="drawer-header">
          <div className="drawer-header-top">
            <h2 className="drawer-title">{drawerTitle}</h2>
            <button type="button" className="btn btn-ghost btn-sm" aria-label="关闭工作台" onClick={() => openDrawer(null)}>关闭</button>
          </div>
          <p className="drawer-purpose">{drawerPurpose}</p>
        </header>
        <div className="drawer-body">
          {drawerOpen && taskId && drawer?.kind === 'pdp' && hasPdp && (
            <div className="drawer-panel is-visible"><PdpPanel taskId={taskId} /></div>
          )}
          {drawerOpen && taskId && drawer?.kind === 'file' && hasFile && (
            <div className="drawer-panel is-visible">
              <FilePanel taskId={taskId} slot={drawer.slot ?? fileSlotOf(artifacts.data ?? [])} />
            </div>
          )}
          {drawerOpen && taskId && imageSlot && hasImage && (
            <div className="drawer-panel is-visible">
              <ImagePanel taskId={taskId} slot={imageSlot} reasoning={reasoning}
                onFeedback={(body) => tracker.send(body)} />
            </div>
          )}
        </div>
        <footer className="drawer-footer">
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => openDrawer(null)}>收起工作台</button>
          {t?.kind === 'pdp' && awaiting && <button type="button" className="btn btn-teal btn-sm" onClick={() => void accept()}>接受当前 PDP</button>}
        </footer>
      </aside>
    </section>
  )
}
