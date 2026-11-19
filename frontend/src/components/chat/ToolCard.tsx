import type { TimelineStep, ToolStarted } from '../../api/types'
import { slotLabel } from '../../lib/labels'

/**
 * What has been merged for one Tool call: what it was asked to do, and what happened.
 *
 * A card is identified by `tool_call_id`, and it is built from two sources that arrive at
 * different times: `tool_started` (SSE, while the Tool is running — the Tool's own row is
 * only written when it returns) and the finished record in `steps` (timeline). They are one
 * card, never two rows, which is why the running and finished states share this shape.
 */
export interface ToolCardModel {
  id: string
  tool: string
  slot: string | null
  /** `running` has no result yet: `tool_started` arrived and the record has not. */
  state: 'running' | 'ok' | 'error'
  cost: number
  durationMs: number | null
  error: string | null
  args: Record<string, unknown>
  output: Record<string, unknown> | null
  versionId: string | null
}

/** The question has its own interactive panel; a card too would show it twice. */
const ASK_TOOL = 'ask_question'

/** Tools whose name alone does not say what happened to the user. */
const RUNNING_TEXT: Record<string, string> = {
  generate_product_image: '正在生成图片',
  edit_product_image: '正在修改图片',
  generate_variants: '正在生成几个版本',
  edit_listing: '正在写文案',
  write_file: '正在写文件',
  read_file: '正在读取文件',
  web_search: '正在搜索网页',
  web_fetch: '正在读取网页',
  compose_canvas: '正在编辑画布',
  read_canvas: '正在读取画布',
}

export function runningText(tool: string): string {
  return RUNNING_TEXT[tool] ?? `正在调用 ${tool}`
}

const clip = (s: string, n = 60) => (s.length > n ? `${s.slice(0, n)}…` : s)

/** One line under the tool name: the slot when there is one, else the path or the prompt. */
function detailOf(m: ToolCardModel): string {
  if (m.slot) return slotLabel(m.slot)
  const path = m.args.path
  if (typeof path === 'string' && path) return path
  const query = m.args.query
  if (typeof query === 'string' && query) return clip(query)
  const url = m.args.url
  if (typeof url === 'string' && url) return clip(url)
  return ''
}

/** A field the card shows as a readable summary instead of a wall of JSON. */
interface Preview {
  label: string
  text: string
  /** True when `text` is the whole value, so there is nothing more to expand. */
  whole: boolean
}

/**
 * The one thing a reader wants from each Tool's arguments, without opening the disclosure.
 *
 * A `write_file` is "what did it write", an image edit is "what did it change", a search is
 * "what did it look for". Showing the raw JSON of any of those in the thread is unreadable —
 * the parameters belong behind the fold, and this is the sentence that goes in front of it.
 */
function previewOf(m: ToolCardModel): Preview | null {
  const a = m.args
  const text = (v: unknown): string | null =>
    typeof v === 'string' && v.trim() ? v.trim() : null
  const prompt = text(a.prompt) ?? text(a.instruction)
  if (prompt) return { label: '指令', text: clip(prompt, 120), whole: prompt.length <= 120 }
  const content = text(a.content)
  if (content) {
    const firstLine = content.split('\n').find((l) => l.trim()) ?? content
    return { label: '内容', text: clip(firstLine.trim(), 120), whole: content.length <= 120 }
  }
  return null
}

/**
 * Merge the announced calls with the recorded ones, in the order they happened.
 *
 * A recorded row wins over an announcement for the same id: it carries the real duration,
 * cost and output. An announcement with no row yet is a Tool still running (or one whose
 * worker died before it could record anything — either way the card should not vanish).
 *
 * `ask_question` is excluded on purpose: it has its own interactive panel (options the user
 * clicks), and drawing a card for it too would show the same question twice.
 */
export function toolCards(
  started: ToolStarted[],
  steps: TimelineStep[],
): ToolCardModel[] {
  const byId = new Map<string, ToolCardModel>()
  const order: string[] = []

  for (const s of started) {
    if (!s?.tool_call_id) continue
    if (s.tool === ASK_TOOL) continue
    if (byId.has(s.tool_call_id)) continue
    order.push(s.tool_call_id)
    byId.set(s.tool_call_id, {
      id: s.tool_call_id,
      tool: s.tool,
      slot: s.slot ?? null,
      state: 'running',
      cost: s.cost ?? 0,
      durationMs: null,
      error: null,
      args: s.args ?? {},
      output: null,
      versionId: null,
    })
  }

  for (const step of steps) {
    if (step.tool === ASK_TOOL) continue
    const id = step.tool_call_id
    const known = id ? byId.get(id) : undefined
    // A recorded call the timeline has but nothing announced (ask_question, or a Run from
    // before this event existed) still gets a card: the record is the authority.
    const key = id ?? `${step.tool}:${step.slot ?? ''}:${order.length}`
    if (!id || !known) order.push(key)
    const versionId = step.output?.version_id
    byId.set(key, {
      id: key,
      tool: step.tool,
      slot: step.slot ?? known?.slot ?? null,
      state: step.ok ? 'ok' : 'error',
      cost: step.cost ?? known?.cost ?? 0,
      durationMs: step.duration_ms,
      error: step.error,
      args: step.input ?? known?.args ?? {},
      output: step.output ?? null,
      versionId: typeof versionId === 'string' ? versionId : null,
    })
  }

  return order.map((id) => byId.get(id)).filter((x): x is ToolCardModel => x !== undefined)
}

/**
 * Every call this turn announced, from the stored turn and from the live SSE stream.
 *
 * A finished turn replays them from the timeline; a running one has them only in the events.
 * Both are the same shape, and `toolCards` dedupes by id, so passing both is safe and means a
 * card does not flicker out at the moment the Run ends.
 */
export function announcedCalls(
  stored: ToolStarted[] | undefined,
  liveEvents: { type: string; data: unknown }[] | undefined,
): ToolStarted[] {
  const out: ToolStarted[] = [...(stored ?? [])]
  for (const e of liveEvents ?? []) {
    if (e.type !== 'tool_started') continue
    const d = e.data as Partial<ToolStarted> | null
    if (!d || typeof d.tool_call_id !== 'string' || typeof d.tool !== 'string') continue
    out.push({
      tool_call_id: d.tool_call_id,
      tool: d.tool,
      slot: d.slot ?? null,
      cost: typeof d.cost === 'number' ? d.cost : 0,
      args: d.args ?? {},
    })
  }
  return out
}

const STATE_LABEL: Record<ToolCardModel['state'], string> = {
  running: '进行中',
  ok: '完成',
  error: '失败',
}

/**
 * One Tool call, as a card that is present from the moment it starts.
 *
 * This replaces a line that only appeared after the Run had already finished: a picture took
 * three minutes to draw and the thread showed one frozen sentence the whole time, so there
 * was nothing to tell a working call from a hung one. The card keeps the call in the record
 * afterwards — a finished turn should say which Tools ran, in what order, at what cost.
 *
 * `details` holds the trimmed input and output. It is collapsed by default: the body of a
 * `write_file` is not something anyone reads in a chat thread, but it must stay one click
 * away, because "what exactly did it send" is the first question when a result looks wrong.
 */
export function ToolCard({ card }: { card: ToolCardModel }) {
  const detail = detailOf(card)
  const preview = previewOf(card)
  const hasDetails = Object.keys(card.args).length > 0 || card.output !== null
  const version = card.versionId ? card.versionId.slice(-6) : ''
  return (
    <div
      className={`tool-card is-${card.state}`}
      data-tool={card.tool}
      data-state={card.state}
      data-testid="tool-card"
    >
      <div className="tool-card-head">
        <span className="tool-card-icon" aria-hidden="true">
          {card.state === 'running' ? <span className="tool-card-spin" /> : null}
          {card.state === 'ok' ? '✓' : null}
          {card.state === 'error' ? '✕' : null}
        </span>
        <span className="tool-card-name">{card.tool}</span>
        {detail && <span className="tool-card-detail">{detail}</span>}
        <span className="tool-card-meta">
          {card.state === 'running' ? runningText(card.tool).replace(/^正在/, '') : STATE_LABEL[card.state]}
          {card.durationMs !== null && card.durationMs >= 1000
            ? ` · ${(card.durationMs / 1000).toFixed(1)}s`
            : ''}
          {card.cost > 0 ? ` · ${card.cost} 积分` : ''}
        </span>
      </div>
      {preview && (
        <p className="tool-card-preview">
          <span className="tool-card-label-inline">{preview.label}</span>
          {preview.text}
        </p>
      )}
      {card.error && <p className="tool-card-error">{card.error}</p>}
      {version && <p className="tool-card-version">产生版本 · {version}</p>}
      {hasDetails && (
        <details className="tool-card-details">
          <summary>参数与返回</summary>
          {Object.keys(card.args).length > 0 && (
            <>
              <span className="tool-card-label">入参</span>
              <pre>{JSON.stringify(card.args, null, 2)}</pre>
            </>
          )}
          {card.output !== null && (
            <>
              <span className="tool-card-label">返回</span>
              <pre>{JSON.stringify(card.output, null, 2)}</pre>
            </>
          )}
        </details>
      )}
    </div>
  )
}
