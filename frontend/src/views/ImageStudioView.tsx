import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { humanSize, type StagedFile } from '../components/chat/attachments'
import { FollowUps } from '../components/chat/FollowUps'
import { Working } from '../components/chat/Working'
import { HumanInputPanel } from '../components/chat/HumanInputPanel'
import { ToolCard, announcedCalls, toolCards } from '../components/chat/ToolCard'
import type { UtteranceBody } from '../api/types'
import { ImageWorkbench } from '../components/image/ImageWorkbench'
import { buildImageUtterance } from '../components/image/utterance'
import { claimBoot } from '../lib/boot'
import { lastHumanInput, parseHumanInputEvent } from '../lib/humanInput'
import { currentVersion, problemsOf, slotLabel, vLabel } from '../lib/labels'
import { progressOf } from '../lib/progress'
import { useApi } from '../state/api-context'
import { useNav } from '../state/nav'
import { useToast } from '../state/toast'
import { useRunTracker } from '../state/useRunTracker'
import { keys, useTaskData } from '../state/useTaskData'

/**
 * Image Agent page (prototype image-design.html): agent column + canvas. Every circled region
 * becomes one utterance with target_slot, target_region and target_version_id (docs/architecture/system.md).
 * The page renders server state only; the new Version appears when the Run finishes.
 */
export function ImageStudioView() {
  const api = useApi()
  const qc = useQueryClient()
  const toast = useToast()
  const { nav, go, openTask, openDrawer } = useNav()
  const taskId = nav.imageTaskId
  const slot = nav.imageSlot ?? 'main_image'
  const { task, timeline, artifacts } = useTaskData(taskId)
  const tracker = useRunTracker(taskId, task.data?.agent_key ?? 'image')
  const tasks = useQuery({ queryKey: keys.tasks, queryFn: () => api.listTasks() })

  const art = artifacts.data?.find((a) => a.slot === slot)
  const cur = currentVersion(art)
  const okVersions = (art?.versions ?? []).filter((v) => v.status !== 'rejected')
  const [focusVersionId, setFocusVersionId] = useState<string | null>(null)
  const focus = okVersions.find((v) => v.id === focusVersionId) ?? cur
  const parent = focus?.parent_version_id
    ? okVersions.find((v) => v.id === focus.parent_version_id)
    : undefined
  const stripVersions = [...okVersions]
    .sort((a, b) => b.seq - a.seq)
    .map((v) => ({
      id: v.id,
      seq: v.seq,
      url: v.content.url ?? '',
      status: v.status,
      isArtifactCurrent: v.id === art?.current_version_id,
    }))

  useEffect(() => {
    const ok = (art?.versions ?? []).filter((v) => v.status !== 'rejected')
    if (!ok.length) {
      setFocusVersionId(null)
      return
    }
    setFocusVersionId((prev) => {
      if (prev && ok.some((v) => v.id === prev)) return prev
      const cid = art?.current_version_id
      if (cid && ok.some((v) => v.id === cid)) return cid
      return ok[ok.length - 1]?.id ?? null
    })
  }, [art?.artifact_id, art?.current_version_id, art?.versions])
  const [text, setText] = useState('')
  const [reasoning, setReasoning] = useState(false)
  const [attachments, setAttachments] = useState<StagedFile[]>([])
  const [uploading, setUploading] = useState(false)
  const thread = useRef<HTMLDivElement>(null)
  /** Header「上传图片…」：新建任务并导入首图。 */
  const headerFileInput = useRef<HTMLInputElement>(null)
  /** 对话区 + 选项「上传」：作为本条发言的 attachment 交给 Agent。 */
  const attachFileInput = useRef<HTMLInputElement>(null)
  /** Set when ask_question option «上传» was chosen — file pick should send immediately. */
  const uploadThenSend = useRef(false)

  useEffect(() => {
    const boot = nav.bootText
    if (!taskId || !boot) return
    // Wait for the Task so the Run records the Agent that owns it, not a guessed default.
    if (!task.data) return
    if (!claimBoot(`image:${taskId}:${boot}`)) return
    go({ bootText: null })
    void tracker.send({ text: boot, target_slot: slot, ...(focus ? { target_version_id: focus.id } : {}) })
  }, [focus, go, nav.bootText, slot, task.data, taskId, tracker])
  useEffect(() => { thread.current?.scrollTo?.({ top: thread.current.scrollHeight }) }, [timeline.data?.length])

  const turns = (timeline.data ?? []).filter((t) => t.user.target_slot === slot || t.versions.some((v) => v.slot === slot && v.kind === 'image'))
  const busy = tracker.running || (timeline.data ?? []).some((t) => t.status === 'queued' || t.status === 'running')
  const pendingHuman = useMemo(() => {
    for (let i = tracker.events.length - 1; i >= 0; i -= 1) {
      const parsed = parseHumanInputEvent(tracker.events[i]?.data)
      if (parsed) return parsed
    }
    const last = turns.at(-1)
    return last ? lastHumanInput(last) : null
  }, [tracker.events, turns])
  /** Who actually ran: a Task started from the general entry keeps `agent_key = general`. */
  const agentLabel = task.data?.agent_key === 'amazon_pdp'
    ? 'PDP Agent'
    : task.data?.agent_key === 'general' ? '通用 Agent' : '图片 Agent'
  const closeStudio = () => {
    if (taskId) { openTask(taskId, task.data?.agent_key); openDrawer({ kind: 'image', slot }) }
    else go({ view: 'chat' })
  }

  const wantsUploadPick = (label: string) => /上传|传.*图|商品照|产品照|参考图/.test(label)

  const openAttachPicker = () => {
    if (!busy) attachFileInput.current?.click()
  }

  const buildUtterance = (raw: string): UtteranceBody => {
    const text = raw.trim() || (attachments.length > 0 ? '附上商品参考图' : '')
    const ids = attachments.map((a) => a.upload_id)
    const extra = ids.length > 0 ? { attachment_ids: ids } : {}
    if (focus) {
      return { ...buildImageUtterance({ text, slot, versionId: focus.id, reasoning }), ...extra }
    }
    return { text, target_slot: slot, reasoning, ...extra }
  }

  const postUtterance = (body: UtteranceBody) => {
    void tracker.send(body)
    setText('')
    setAttachments([])
  }

  const sendText = () => {
    if (busy) return
    const t = text.trim()
    if (!t && attachments.length === 0) return
    postUtterance(buildUtterance(t))
  }

  /**
   * Sends one of the offered replies, tagged with the question it answers.
   *
   * A Run is not resumed: answering starts a new one. Without the `request_id` the next Run
   * saw "一个电动剃须刀" as a fresh brief with no question attached (docs/architecture/system.md).
   */
  const sendPick = (t: string) => {
    if (!t || busy) return
    if (wantsUploadPick(t)) {
      uploadThenSend.current = true
      openAttachPicker()
      return
    }
    const rid = pendingHuman?.request_id
    postUtterance({ ...buildUtterance(t), ...(rid ? { answers_request_id: rid } : {}) })
  }

  const stageImage = async (file: File) => {
    setUploading(true)
    try {
      const u = await api.upload(file)
      const staged: StagedFile = {
        upload_id: u.upload_id,
        name: file.name,
        mime: file.type || 'image/png',
        size: file.size,
        kind: 'image',
        readable: false,
      }
      if (uploadThenSend.current) {
        uploadThenSend.current = false
        postUtterance({ ...buildUtterance('附上商品参考图'), attachment_ids: [u.upload_id] })
        return
      }
      setAttachments((prev) => [...prev, staged])
    } catch (e) {
      uploadThenSend.current = false
      toast(e instanceof Error ? e.message : '上传失败')
    } finally {
      setUploading(false)
    }
  }

  const pickSource = async (value: string) => {
    if (value === '__upload') { headerFileInput.current?.click(); return }
    const [id, s] = value.split('|')
    go({ imageTaskId: id, imageSlot: s ?? 'main_image' })
  }
  const upload = async (file: File) => {
    try {
      const u = await api.upload(file)
      const t = await api.createTask({ agent_id: 'general', kind: 'image', goal: file.name, upload_id: u.upload_id })
      await qc.invalidateQueries({ queryKey: keys.tasks })
      go({ imageTaskId: t.id, imageSlot: 'main_image' })
    } catch (e) { toast(e instanceof Error ? e.message : '上传失败') }
  }

  const sources = (tasks.data ?? []).filter((t) => t.status !== 'abandoned')
  const product = task.data?.meta.product

  return (
    <>
      <div className={`design-stage${cur ? '' : ' is-empty'}`}>
        <section className="agent-column" aria-label="Agent 对话">
          <header className="agent-col-head">
            <div className="agent-model" style={{ cursor: 'default' }}><span>{product?.name ?? task.data?.goal ?? '选择图片'}</span></div>
            <div className="agent-head-actions">
              <select aria-label="图片来源" value={taskId ? `${taskId}|${slot}` : ''} onChange={(e) => void pickSource(e.target.value)}
                style={{ fontSize: 11, border: '1px solid var(--border)', borderRadius: 8, padding: '2px 6px', background: '#fff' }}>
                <option value="" disabled>选择图片来源</option>
                {sources.flatMap((t) => [
                  <option key={`${t.id}|main_image`} value={`${t.id}|main_image`}>{(t.meta.product?.name ?? t.goal) || '任务'} · 主图</option>,
                  ...(t.kind === 'pdp' ? [<option key={`${t.id}|secondary_image`} value={`${t.id}|secondary_image`}>{(t.meta.product?.name ?? t.goal) || '任务'} · 副图</option>] : []),
                ])}
                <option value="__upload">上传图片…</option>
              </select>
              <input ref={headerFileInput} type="file" accept="image/*" hidden aria-label="上传图片并新建任务"
                onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); e.target.value = '' }} />
              {cur && <span className="file-chip" style={{ maxWidth: 'none', fontFamily: 'var(--font-mono)', fontSize: 11 }}>{slot}</span>}
            </div>
          </header>
          <div className="agent-chat-shell">
          <div className="agent-thread" ref={thread}>
            <div className="agent-thread-inner">
            <div className="agent-thread-hint">
              <b>图片预览</b> 是轻量画布：一次只看一张图，圈选改这一张。多屏设计板在画布 Agent。
            </div>
            {!taskId && <div className="msg-assistant"><p className="assistant-lede">先在右上角选一张图，或上传一张图片。</p></div>}
            {turns.map((t) => {
              const made = t.versions.filter((v) => v.kind === 'image')
              const pending = t.status === 'queued' || t.status === 'running'
              const userLine = t.user.text.trim()
              return (
                <div className="thread-turn" key={t.run_id}>
                  <div className="msg-user">{t.user.text}{t.user.target_region ? '（圈选区域）' : ''}</div>
                  <div className="msg-assistant">
                    <div className="agent-identity"><span className="agent-avatar" aria-hidden="true">AI</span><span>{agentLabel}</span></div>
                    <div className="msg-assistant-body">
                    {/* While the Run is live this shows the reply as it streams, then the stage
                        line. The delivery bar and any answer already recorded are NOT gated on
                        `pending`: a committed Version plus a blank panel is what read as a hung
                        job after the picture had in fact been made (docs/architecture/system.md). */}
                    {pending && t === turns.at(-1) && <Working events={tracker.running ? tracker.events : []} />}
                    {t.status === 'failed' && <p className="assistant-lede">失败：{t.error}</p>}
                    {t.interpretations
                      .filter((i) => !(i.kind === 'parameter_patch' && i.text.trim() === userLine))
                      .map((i) => (
                      <p className="assistant-lede" key={i.feedback_id}>{i.status === 'declined' ? `未执行：${i.note}` : i.text}</p>
                    ))}
                    {t.answers.map((a, n) => (
                      <p className="assistant-lede" key={n}>{a}</p>
                    ))}
                    {toolCards(announcedCalls(t.tool_started, tracker.events), t.steps).map((card) => (
                      <ToolCard key={card.id} card={card} />
                    ))}
                    {!pending && pendingHuman && t.run_id === turns.at(-1)?.run_id && task.data?.status === 'awaiting_user' && (
                      <HumanInputPanel
                        request={pendingHuman}
                        disabled={busy}
                        onPickOption={(v) => sendPick(v)}
                        onSubmit={(v) => sendPick(v)}
                      />
                    )}
                    {!pending && (t.follow_ups ?? []).length > 0 && (
                      <FollowUps
                        questions={t.follow_ups ?? []}
                        disabled={busy}
                        onPick={(v) => postUtterance(buildUtterance(v))}
                      />
                    )}
                    {made.map((v) => (
                      <div className="delivery-bar" key={v.id}>
                        <span className="done"><span className="delivery-check">{v.status === 'rejected' ? '✕' : '✓'}</span>
                          {slotLabel(v.slot ?? slot)} {vLabel(v.seq)} {v.status === 'rejected' ? `被拒绝：${v.evaluations.flatMap((e) => e.problems).join('；')}` : v.is_current ? '已成为当前版本' : '已生成'}</span>
                        <span className="delivery-steps">{t.steps.at(-1)?.tool ?? ''} · {t.cost} 积分</span>
                      </div>
                    ))}
                    </div>
                  </div>
                </div>
              )
            })}
            </div>
          </div>
          <footer className="agent-composer">
            <input
              ref={attachFileInput}
              type="file"
              accept="image/*"
              hidden
              aria-label="上传商品图"
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) void stageImage(f)
                e.target.value = ''
              }}
            />
            <div className="composer-pill">
              {attachments.length > 0 && (
                <div className="composer-attach-row">
                  {attachments.map((f) => (
                    <span key={f.upload_id} className="attach-chip">
                      <b>{f.name}</b>
                      <span>{humanSize(f.size)} · 参考图</span>
                      <button
                        type="button"
                        aria-label={`移除 ${f.name}`}
                        onClick={() => setAttachments((prev) => prev.filter((x) => x.upload_id !== f.upload_id))}
                      >×</button>
                    </span>
                  ))}
                </div>
              )}
              <div className="composer-chips">
                <span className="file-chip">目标：{slotLabel(slot)}{focus
                  ? ` · 编辑 ${vLabel(focus.seq)}${cur && focus.id !== cur.id ? ` · 交付 ${vLabel(cur.seq)}` : ' · 当前'}`
                  : ' · 第一版'}</span>
                <button type="button" className="x-chip" aria-pressed={reasoning} onClick={() => setReasoning((v) => !v)}>推理{reasoning ? '开' : '关'}</button>
              </div>
              <textarea rows={1} value={text} aria-label="Agent 输入"
                placeholder={cur ? '描述想要的改动，或直接在图上圈选局部。点 + 可上传参考图。' : '描述你要的图片，或点 + 上传商品照片。'}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); sendText() } }} />
              <div className="composer-toolbar">
                <div className="composer-tools-left">
                  <button
                    type="button"
                    className="composer-attach"
                    aria-label="上传图片"
                    disabled={uploading || busy}
                    onClick={openAttachPicker}
                  >{uploading ? '…' : '+'}</button>
                </div>
                {busy ? (
                  // While a Run is live the same button becomes Stop: one primary action, and
                  // the label says what is happening. A greyed-out Send left the user waiting
                  // with no way to cancel and no sign the click had registered (docs/architecture/system.md).
                  <button type="button" className="composer-send is-stop" aria-label="停止生成" onClick={() => void tracker.cancel()}>
                    <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor" stroke="none" /></svg>
                  </button>
                ) : (
                  <button type="button" className="composer-send" aria-label="发送" disabled={!text.trim() && attachments.length === 0} onClick={sendText}>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 19V5M5 12l7-7 7 7" /></svg>
                  </button>
                )}
              </div>
              {busy && <p className="composer-status" role="status" aria-live="polite">{progressOf(tracker.events).text}…</p>}
            </div>
          </footer>
          </div>
        </section>

        {focus && (
          <div className="design-column">
            <ImageWorkbench
              variant="page"
              imageUrl={focus.content.url ?? ''}
              alt={`${slotLabel(slot)} ${vLabel(focus.seq)}`}
              versionId={focus.id}
              slot={slot}
              label={`${slot} · ${vLabel(focus.seq)} · 编辑基底${cur && focus.id === cur.id ? ' · 当前' : ''}`}
              prevUrl={parent?.content.url}
              prevLabel={parent ? `${slot} · ${vLabel(parent.seq)} · 对照` : undefined}
              width={focus.content.width ?? cur?.content.width}
              height={focus.content.height ?? cur?.content.height}
              reasoning={reasoning}
              busy={busy}
              stripVersions={stripVersions}
              focusVersionId={focus.id}
              onFocusVersion={setFocusVersionId}
              onClose={closeStudio}
              onUpload={openAttachPicker}
              onFeedback={(body) => tracker.send(body)}
            />
          </div>
        )}
      </div>
      {focus && problemsOf(focus).length > 0 && <p className="sr-only">基线问题：{problemsOf(focus).join('；')}</p>}
    </>
  )
}
