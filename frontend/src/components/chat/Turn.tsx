import type { ReactNode } from 'react'
import type { TimelineInterpretation, TimelineTurn, TimelineVersion } from '../../api/types'
import { INTERP_LABEL, pLabel, slotLabel, vLabel } from '../../lib/labels'
import { EVENT_TEXT } from '../../lib/progress'
import type { DrawerTarget } from '../../state/nav'
import { Tag } from '../Tag'
import { AnswerOptions } from './AnswerOptions'
import { FileCard, ImageCard, PdpCard } from './ArtifactCards'
import { FollowUps } from './FollowUps'
import { HumanInputPanel } from './HumanInputPanel'
import { TodoList } from './TodoList'
import { ToolCard, announcedCalls, toolCards } from './ToolCard'
import { Working } from './Working'

// Re-exported so existing imports keep working; the vocabulary itself lives in lib/progress.
export { EVENT_TEXT }

export function UserMsg({ text, children }: { text: string; children?: ReactNode }) {
  return (
    <article className="msg msg-user">
      <div className="msg-avatar user">你</div>
      <div className="msg-bubble"><p className="msg-text">{text}</p>{children}</div>
    </article>
  )
}

export function AiMsg({ children }: { children: ReactNode }) {
  return (
    <article className="msg">
      <div className="msg-avatar ai">AI</div>
      <div className="msg-bubble">{children}</div>
    </article>
  )
}

const clip = (s: string, n = 56) => (s.length > n ? `${s.slice(0, n)}…` : s)

/** Applied parameter_patch rows are routing metadata; repeating the user sentence reads like a bug. */
function visibleInterpretations(turn: TimelineTurn): TimelineInterpretation[] {
  return turn.interpretations.filter(
    (i) => !(i.kind === 'parameter_patch' && i.status === 'applied' && i.text.trim() === turn.user.text.trim()),
  )
}

/** Rows under an interpretation card: what changed, from the recorded versions. */
function changeRows(i: TimelineInterpretation, versions: TimelineVersion[]): [string, string, string][] {
  const v = versions.find((x) => x.slot === i.slot && x.kind !== 'pdp' && x.parent_content)
  if (!v || !i.slot) return []
  const a = v.parent_content?.items
  const b = v.content.items
  if (a && b) {
    const k = b.findIndex((t, n) => a[n] !== t)
    return k >= 0 ? [[`${slotLabel(i.slot)} 第 ${k + 1} 条`, clip(a[k] ?? ''), clip(b[k] ?? '')]] : []
  }
  if (v.parent_content?.text !== undefined && v.content.text !== undefined) {
    return [[slotLabel(i.slot), clip(v.parent_content.text), clip(v.content.text)]]
  }
  const op = v.params.operation
  return typeof op === 'string' ? [['operation', '—', op]] : []
}

function Interp({ i, versions, onConfirm, onIgnore }: {
  i: TimelineInterpretation; versions: TimelineVersion[]
  onConfirm: (constraintId: string) => void; onIgnore: (constraintId: string) => void
}) {
  const rows = i.kind === 'parameter_patch' ? changeRows(i, versions) : []
  return (
    <div className={`x-interp ${i.kind}`}>
      <div className="x-ih">
        <span className="x-ik">{INTERP_LABEL[i.kind]}</span>
        <span>{i.text}{i.slot ? ` · ${slotLabel(i.slot)}` : ''}{i.region ? ' · 圈选区域' : ''}</span>
      </div>
      {rows.length > 0 && (
        <ul className="x-irows">
          {rows.map(([k, from, to]) => (
            <li key={k}><span className="mono">{k}</span> {from} <i>→</i> <b>{to}</b></li>
          ))}
        </ul>
      )}
      {i.status === 'declined' && <div className="x-sub" style={{ marginTop: 6 }}>未执行：{i.note}</div>}
      {i.kind === 'new_constraint' && i.constraint_id && (
        <div className="x-ia">
          {i.constraint_status === 'pending' ? (
            <>
              <span className="x-sub">确认前不生效，当前版本不受影响</span>
              <span className="x-btns">
                <button type="button" className="btn btn-teal btn-sm" onClick={() => onConfirm(i.constraint_id as string)}>确认</button>
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => onIgnore(i.constraint_id as string)}>忽略</button>
              </span>
            </>
          ) : (
            <Tag cls={i.constraint_status === 'effective' ? 'ok' : ''}>{i.constraint_status === 'effective' ? '已生效' : '已忽略'}</Tag>
          )}
        </div>
      )}
    </div>
  )
}

function Steps({ turn }: { turn: TimelineTurn }) {
  const slotVersions = turn.versions.filter((v) => v.kind !== 'pdp')
  const evals = slotVersions.flatMap((v) => v.evaluations)
  if (turn.steps.length === 0 && evals.length === 0) return null
  const passed = evals.filter((e) => e.passed).length
  return (
    <details className="x-steps">
      <summary>{turn.run_id.slice(-6)} · 规则检查{evals.length > 0 ? ` ${passed}/${evals.length} 通过` : ''}</summary>
      <ul>
        {evals.length > 0 && (
          <li>
            <span className="x-s-ok">{passed === evals.length ? '✓' : '✕'}</span>
            <span className="x-s-name">规则评估（自动）</span>
            <span className="x-s-meta">{passed}/{evals.length} 项通过</span>
          </li>
        )}
      </ul>
    </details>
  )
}

/** One Run as the Runtime recorded it: interpretations, steps, rejections, resulting versions. */
export function Turn({ turn, activeEvent, liveEvents, drawer, onOpen, onConfirm, onIgnore, onOpenCanvas, onAnswer, onUpload, pendingHumanRequestId = null, answersEnabled = true }: {
  turn: TimelineTurn
  activeEvent: string | null
  /** SSE events for this Run while it is still going; empty for a finished one. */
  liveEvents?: { type: string; data: unknown }[]
  drawer: DrawerTarget | null
  onOpen: (d: DrawerTarget) => void
  onConfirm: (constraintId: string) => void
  onIgnore: (constraintId: string) => void
  onOpenCanvas?: () => void
  /** Sends one of the offered replies as the next turn. */
  onAnswer: (text: string) => void
  /** A picture the Agent asked for via `request_upload`. */
  onUpload?: (file: File) => void
  /** When set, this turn shows the interactive ask_question card for that request. */
  pendingHumanRequestId?: string | null
  /** False while another Run is live: the follow-up chips stay visible but not clickable. */
  answersEnabled?: boolean
}) {
  const pending = turn.status === 'queued' || turn.status === 'running' || turn.status === 'cancel_requested'
  const slotVersions = turn.versions.filter((v) => v.kind !== 'pdp')
  const rejected = slotVersions.filter((v) => v.status === 'rejected')
  const pdp = turn.versions.filter((v) => v.kind === 'pdp').at(-1)
  const images = slotVersions.filter((v) => v.kind === 'image' && v.status !== 'rejected')
  const files = slotVersions.filter((v) => v.kind === 'file' && v.status !== 'rejected')
  const canvases = slotVersions.filter((v) => v.kind === 'canvas' && v.status !== 'rejected')
  const followUps = turn.follow_ups ?? []
  const target = turn.user.target_slot
  // A card is keyed by tool_call_id, so a call announced while it runs and the record that
  // arrives when it returns are the same card (never two rows for one call).
  const cards = toolCards(
    announcedCalls(turn.tool_started, liveEvents),
    turn.steps,
  )
  const lede = pending ? null
    : turn.status === 'failed' ? null
    : turn.status === 'cancelled' ? '已取消。'
    : slotVersions.length > 0 ? `完成：产生了 ${slotVersions.length} 个新版本${rejected.length ? `，其中 ${rejected.length} 个被规则拒绝` : ''}。`
    : turn.answers.length === 0 && turn.interpretations.every((i) => i.kind === 'new_constraint') ? null
    : turn.interpretations.some((i) => i.status === 'declined') ? '这一轮没有产生新版本。'
    : null

  return (
    <>
      <UserMsg text={turn.user.text}>
        {target && <div className="x-sub" style={{ marginTop: 6 }}>目标：{slotLabel(target)}{turn.user.target_region ? ' · 圈选区域' : ''}</div>}
      </UserMsg>
      <AiMsg>
        {pending && (
          turn.status === 'queued'
            ? <p className="x-queued">{activeEvent ?? '已排队'}</p>
            : <Working events={liveEvents ?? []} />
        )}
        {lede && <p className="msg-text">{lede}</p>}
        {visibleInterpretations(turn).length > 1 && <p className="msg-text">一句话拆成了 {visibleInterpretations(turn).length} 条反馈：</p>}
        {visibleInterpretations(turn).map((i) => (
          <Interp key={i.feedback_id} i={i} versions={turn.versions} onConfirm={onConfirm} onIgnore={onIgnore} />
        ))}
        {turn.todos && turn.todos.length > 0 && <TodoList items={turn.todos} />}
        {turn.human_input_requests.map((req) => (
          pendingHumanRequestId === req.request_id ? (
            <HumanInputPanel
              key={req.request_id}
              request={req}
              disabled={pending}
              onPickOption={onAnswer}
              onSubmit={onAnswer}
              onUpload={onUpload}
            />
          ) : null
        ))}
        {turn.answers.map((a, n) => (
          <div key={n}>
            <p className="msg-text">{a}</p>
            {turn.human_input_requests.length === 0 && (
              <AnswerOptions
                options={turn.answer_options?.[n] ?? []}
                disabled={pending || turn.status !== 'succeeded'}
                onPick={onAnswer}
              />
            )}
          </div>
        ))}
        {followUps.length > 0 && (
          <FollowUps
            questions={followUps}
            disabled={pending || !answersEnabled}
            onPick={onAnswer}
          />
        )}
        {turn.preference_proposals.length > 0 && (
          <div className="x-interp"><div className="x-ih"><span className="x-ik">偏好提议</span><span>已提议一条偏好，你接受后才会写入偏好文档。</span></div></div>
        )}
        {cards.length > 0 && (
          <div className="tool-cards">
            {cards.map((card) => <ToolCard key={card.id} card={card} />)}
          </div>
        )}
        <Steps turn={turn} />
        {turn.steps.filter((s) => s.tool === 'write_file' && !s.ok && s.path).map((s) => (
          <p key={s.path}><button type="button" className="btn btn-secondary btn-sm" onClick={() => onOpen({ kind: 'file', slot: s.path ?? undefined })}>
            {s.path} 写入失败，查看源码
          </button></p>
        ))}
        {rejected.map((v) => (
          <div className="x-fail" key={v.id}>
            <b>{v.slot ? slotLabel(v.slot) : ''} {vLabel(v.seq)} 被拒绝</b>
            <p>{v.evaluations.filter((e) => !e.passed).flatMap((e) => e.problems).join('；') || '未通过规则检查'}。当前版本没有被替换。</p>
            <p className="x-sub">被拒绝的版本也产生了成本，本轮消耗 {turn.cost} 积分（冻结 {turn.held}，返还 {Math.max(0, turn.held - turn.cost)}）。</p>
          </div>
        ))}
        {turn.status === 'failed' && (
          <div className="x-fail"><b>这一轮失败了</b><p>{turn.error ?? '未知错误'}</p></div>
        )}
        {(pdp || images.length > 0 || files.length > 0 || canvases.length > 0) && (
          <div className="msg-artifacts">
            {pdp && (
              <PdpCard label={pLabel(pdp.seq)} title="PDP 预览" focused={drawer?.kind === 'pdp'}
                desc="每个槽位各自指向一个版本"
                onOpen={() => onOpen({ kind: 'pdp' })} />
            )}
            {images.map((v) => (
              <ImageCard key={v.id} thumb={v.content.url} typeLabel={v.slot ? slotLabel(v.slot) : '图片'}
                version={vLabel(v.seq)} title={`${v.slot ? slotLabel(v.slot) : '图片'} · ${vLabel(v.seq)}`}
                desc={typeof v.params.instruction === 'string' && v.params.instruction ? v.params.instruction : '规则检查已自动运行'}
                tags={v.is_current ? <Tag cls="ok">当前</Tag> : undefined}
                focused={drawer?.kind === 'image' && drawer.slot === v.slot}
                onOpen={() => onOpen({ kind: 'image', slot: v.slot ?? undefined })} />
            ))}
            {files.map((v) => (
              <FileCard key={v.id} name={v.content.filename ?? v.slot ?? '文件'} version={vLabel(v.seq)}
                title={v.content.filename ?? v.slot ?? '文件'}
                desc={v.content.media === 'html' ? 'HTML 预览' : v.content.media === 'table' ? '表格预览' : '文件预览'}
                focused={drawer?.kind === 'file' && drawer.slot === v.slot}
                onOpen={() => onOpen({ kind: 'file', slot: v.slot ?? undefined })} />
            ))}
            {canvases.map((v) => (
              <FileCard key={v.id} name="A+" version={vLabel(v.seq)}
                title={`画布 · ${vLabel(v.seq)}`}
                desc={v.is_current ? '当前版面' : '打开画布 Agent 看这一版'}
                onOpen={() => onOpenCanvas?.()} />
            ))}
          </div>
        )}
      </AiMsg>
    </>
  )
}
