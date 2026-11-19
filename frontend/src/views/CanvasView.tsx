import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import type { CanvasView as CanvasData } from '../api/types'
import { CanvasWorkbench } from '../components/canvas/CanvasWorkbench'
import { AnswerOptions } from '../components/chat/AnswerOptions'
import { EVENT_TEXT } from '../components/chat/Turn'
import { claimBoot } from '../lib/boot'
import { slotLabel, vLabel } from '../lib/labels'
import { useApi } from '../state/api-context'
import { useNav } from '../state/nav'
import { useToast } from '../state/toast'
import { useRunTracker } from '../state/useRunTracker'
import { useRefreshTask, useTaskData } from '../state/useTaskData'

/**
 * Canvas Agent workspace (docs/architecture/data-and-contracts.md, 0031), the stage you enter after picking a project.
 * Modelled on stitch_demo/workspace.html, coloured with the app theme: the board fills the
 * stage, a glass top bar floats over it, the prompt sits in a dock at the bottom, and the
 * conversation is a glass card at the top left. The inspector stays on the right, so the two
 * never share a corner.
 *
 * This is not the Image Agent preview. That page is a single picture beside a chat column.
 */
export function CanvasView() {
  const api = useApi()
  const toast = useToast()
  const { nav, go } = useNav()
  const taskId = nav.canvasTaskId
  const { task, timeline } = useTaskData(taskId)
  const refresh = useRefreshTask(taskId)
  const tracker = useRunTracker(taskId, task.data?.agent_key ?? 'canvas')
  const [text, setText] = useState('')
  const [reasoning, setReasoning] = useState(false)
  const [threadOpen, setThreadOpen] = useState(true)
  const thread = useRef<HTMLDivElement>(null)

  const canvas = useQuery({
    queryKey: ['canvas', taskId],
    queryFn: () => api.canvas(taskId!),
    enabled: Boolean(taskId),
  })

  useEffect(() => {
    const boot = nav.bootText
    if (!taskId || !boot) return
    if (!task.data) return
    if (!claimBoot(`canvas:${taskId}:${boot}`)) return
    go({ bootText: null })
    void tracker.send({ text: boot, target_slot: 'canvas' })
  }, [go, nav.bootText, task.data, taskId, tracker])

  useEffect(() => { thread.current?.scrollTo?.({ top: thread.current.scrollHeight }) }, [timeline.data?.length])

  const turns = timeline.data ?? []
  const running = tracker.running || turns.some((t) => t.status === 'queued' || t.status === 'running')
  const data = canvas.data
  const hasCanvas = Boolean(data?.version_id)

  const send = () => {
    const t = text.trim()
    if (!t || running) return
    void tracker.send({ text: t, target_slot: 'canvas', reasoning })
    setText('')
    setThreadOpen(true)
  }

  /** Same path as typing: an offered reply is just a prewritten sentence. */
  const pick = (t: string) => {
    if (running) return
    void tracker.send({ text: t, target_slot: 'canvas', reasoning })
    setThreadOpen(true)
  }

  const patch = async (ops: Parameters<typeof api.canvasPatch>[1]) => {
    const vid = data?.version_id
    if (!vid) return
    await api.canvasPatch(vid, ops)
    await canvas.refetch()
    await refresh()
  }

  const backToProjects = () =>
    go({ view: 'canvas', agent: 'canvas', canvasTaskId: null, bootText: null })

  if (!taskId) return null

  return (
    <section className="view canvas-page is-active is-docked">
      {data && (
        <CanvasWorkbench
          canvas={data as CanvasData}
          busy={running}
          onPatch={patch}
          onSelectVersion={(id) => {
            void api.makeCurrent(id)
              .then(() => canvas.refetch())
              .catch((e: unknown) => toast(e instanceof Error ? e.message : '不能切到这一版'))
          }}
          onAskAboutModule={(id) => {
            const m = data.screens.flatMap((s) => s.modules).find((x) => x.id === id)
            setText(`${m?.name || '这一块'}：`)
            setThreadOpen(true)
          }}
          onKeepVariant={(screenId) => patch([{ op: 'keep_variant', id: screenId }])}
          topRight={
            <>
              <span className="canvas-wb-tag">{task.data?.goal || '未命名画布'}</span>
              <button type="button" className="canvas-float-btn" onClick={backToProjects}>项目</button>
            </>
          }
        />
      )}

      {/* Conversation: a glass card at the top left of the board, never a column. */}
      <aside className={`canvas-chat${threadOpen ? ' is-open' : ''}`} aria-label="对话上下文">
        <button type="button" className="canvas-chat-head" aria-expanded={threadOpen}
          onClick={() => setThreadOpen((o) => !o)}>
          <span className="canvas-chat-title">对话{turns.length > 0 ? ` · ${turns.length}` : ''}</span>
          {running && <span className="canvas-chat-live" aria-label="进行中" />}
          <span className="canvas-chat-caret" aria-hidden="true">{threadOpen ? '−' : '+'}</span>
        </button>
        {threadOpen && (
          <div className="canvas-chat-body" ref={thread}>
            {turns.length === 0 && (
              <p className="canvas-chat-empty">
                说一句要做什么。比如「一张深色极简风格的咖啡店海报」或「把标题换成这个」。
              </p>
            )}
            {turns.map((t) => {
              const made = t.versions.filter((v) => v.slot === 'canvas')
              const pending = t.status === 'queued' || t.status === 'running'
              return (
                <div key={t.run_id} className="canvas-turn">
                  <div className="msg-user">{t.user.text}</div>
                  {pending && (
                    <p className="canvas-turn-line is-live">
                      {tracker.events.at(-1) ? EVENT_TEXT[tracker.events.at(-1)?.type ?? ''] : '处理中…'}
                    </p>
                  )}
                  {t.status === 'failed' && <p className="canvas-turn-line is-fail">失败：{t.error}</p>}
                  {t.interpretations.map((i) => (
                    <p className="canvas-turn-line" key={i.feedback_id}>
                      {i.status === 'declined' ? `未执行：${i.note}` : i.text}
                    </p>
                  ))}
                  {t.answers.map((a, n) => (
                    <div key={n}>
                      <p className="canvas-turn-line">{a}</p>
                      <AnswerOptions options={t.answer_options?.[n] ?? []} disabled={running} onPick={(v) => pick(v)} />
                    </div>
                  ))}
                  {made.map((v) => (
                    <p className="canvas-turn-line is-done" key={v.id}>
                      {v.status === 'rejected'
                        ? `${vLabel(v.seq)} 被拒绝：${v.evaluations.flatMap((e) => e.problems).join('；')}`
                        : `${slotLabel(v.slot ?? 'canvas')} ${vLabel(v.seq)} ${v.is_current ? '已成为当前版本' : '已生成'}`}
                      <span className="canvas-turn-cost">{t.steps.at(-1)?.tool ?? ''} · {t.cost} 积分</span>
                    </p>
                  ))}
                </div>
              )
            })}
          </div>
        )}
      </aside>

      <div className="canvas-dock">
        <Composer
          text={text} setText={setText} onSend={send} running={running} onStop={() => void tracker.cancel()}
          reasoning={reasoning} setReasoning={setReasoning}
          label={data?.seq ? `画布 · v${data.seq}` : '画布 · 第一版'}
          hint={hasCanvas ? '说出要改的地方，或直接拖动画布。' : '描述你要的画面。第一张图会先以占位卡片出现。'} />
      </div>
    </section>
  )
}

/** The one composer: Enter to send, and while a Run is live the same button means Stop. */
function Composer({
  text, setText, onSend, running, onStop, reasoning, setReasoning, label, hint,
}: {
  text: string
  setText: (v: string) => void
  onSend: () => void
  running: boolean
  onStop: () => void
  reasoning: boolean
  setReasoning: (fn: (v: boolean) => boolean) => void
  label: string
  hint: string
}) {
  return (
    <div className="composer-pill canvas-composer">
      <div className="composer-chips">
        <span className="file-chip">{label}</span>
        <button type="button" className="x-chip" aria-pressed={reasoning}
          onClick={() => setReasoning((v) => !v)}>推理{reasoning ? '开' : '关'}</button>
      </div>
      <textarea rows={1} value={text} aria-label="Agent 输入" placeholder={hint}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault()
            onSend()
          }
        }} />
      <div className="composer-toolbar">
        <div className="composer-tools-left" />
        {running ? (
          // One primary action, and the label says what it does: while the board is being
          // built the same button stops the Run instead of greying out (docs/architecture/system.md).
          <button type="button" className="composer-send is-stop" aria-label="停止生成" onClick={onStop}>停止</button>
        ) : (
          <button type="button" className="composer-send" aria-label="发送" disabled={!text.trim()} onClick={onSend}>发送</button>
        )}
      </div>
    </div>
  )
}
