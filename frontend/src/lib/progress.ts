/**
 * What the waiting user reads. A Run reports coarse stages (`step` events, plus the older
 * named events); this module turns them into one short Chinese line.
 *
 * It lives alone because three surfaces show the same wait: the chat thread, the image
 * studio column and the drawer. They must not drift into three different vocabularies.
 */
import { stepName } from './labels'
import type { TimelineStep } from '../api/types'

/** Old named events still carry meaning for the first moment of a Run. */
export const EVENT_TEXT: Record<string, string> = {
  run_queued: '已排队',
  run_started: '开始处理',
  context_loaded: '已读取偏好与约束',
  feedback_interpreted: '已理解你的意见',
  answer: '已回答',
  human_input_request: '等待你的确认',
  constraint_pending: '识别到一条约束，等待你确认',
  preference_proposed: '提议了一条偏好，需要你接受才会生效',
  tool_declined: '这一步没有执行',
  scope_rejected: '超出可修改范围，已拒绝提交',
  step: '正在处理',
  version_created: '产生了新版本',
  variants_created: '产生了几个备选版本',
  todos: '更新了执行计划',
  run_succeeded: '完成',
  run_failed: '失败',
  run_cancelled: '已取消',
}

/** Tools that take long enough that the wait itself needs explaining. */
const TOOL_TEXT: Record<string, string> = {
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
  search_competitor: '正在看竞品',
  list_versions: '正在查看版本历史',
  restore_version: '正在恢复之前的版本',
  inspect_image: '正在检查图片是否符合规则',
  fix_image: '正在修正图片',
  image_variants: '正在生成几个备选方向',
  record_constraint: '正在记录规则',
  write_todos: '正在更新计划',
  request_upload: '正在请求你上传图片',
}

const STAGE_TEXT: Record<string, string> = {
  context: '正在读取偏好与约束',
  compact: '正在整理对话',
  interpret: '正在分析意图',
  resume: '正在恢复上次的进度',
  dispatch: '正在决定下一步',
  think: '正在思考',
  running: '正在执行',
  tool: '正在调用工具',
  work: '正在处理',
}

/** `generate_product_image:main_image` -> `正在生成图片` (the slot adds nothing while waiting). */
function toolText(detail: string): string {
  const name = detail.split(':', 1)[0] ?? ''
  return TOOL_TEXT[name] ?? STAGE_TEXT.tool ?? '正在调用工具'
}

export interface ProgressLine {
  /** The short line to show: "正在分析意图". */
  text: string
  /** Machine-readable stage, for styling and tests. */
  stage: string
}

/**
 * The most recent thing the Run is doing.
 *
 * `events` is what SSE delivered, in order; the last one wins. Before any event arrives the
 * caller shows "已排队" itself. A `step` event carries `{stage, detail}`; the named events
 * (`context_loaded`, …) carry no stage and fall back to their own sentence.
 */
export function progressOf(events: { type: string; data: unknown }[]): ProgressLine {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const e = events[i]
    if (!e) continue
    const data = (e.data ?? {}) as { stage?: unknown; detail?: unknown }
    const stage = typeof data.stage === 'string' ? data.stage : ''
    if (e.type === 'step' && stage) {
      const detail = typeof data.detail === 'string' ? data.detail : ''
      if (stage === 'tool') return { text: detail ? toolText(detail) : '正在调用工具', stage }
      if (stage === 'running') return { text: detail ? toolText(detail) : '正在执行', stage }
      return { text: STAGE_TEXT[stage] ?? '正在处理', stage }
    }
    const named = EVENT_TEXT[e.type]
    if (named) return { text: named, stage: e.type }
  }
  return { text: '正在处理', stage: 'unknown' }
}

/** A finished Run's last Tool, for the line under a delivered artifact. */
export function lastStepText(steps: TimelineStep[]): string {
  const last = steps.at(-1)
  return last ? stepName(last) : ''
}
