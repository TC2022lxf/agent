// Display text only. Which slots exist, their order and their kinds come from the server
// (/api/slots, /api/tasks/{id}/artifacts); an unknown slot falls back to its own key.
import type { ArtifactView, TimelineStep, VersionView } from '../api/types'

const SLOT_LABEL: Record<string, string> = {
  title: '标题',
  bullets: '五点',
  description: '描述',
  search_terms: '后台关键词',
  main_image: '主图',
  secondary_image: '副图',
  image: '图片',
  canvas: '画布',
}
export const slotLabel = (slot: string): string => SLOT_LABEL[slot] ?? slot

export const taskKindLabel = (kind: string): string =>
  kind === 'pdp' ? 'PDP' : kind === 'image' ? '图片' : kind === 'file' ? '文件'
    : kind === 'canvas' ? '画布' : '通用'

/** Task kind -> the artifact kinds an Agent must support to work on it. */
export function requiredKinds(kind: string): string[] {
  if (kind === 'general') return ['file', 'image']
  if (kind === 'image') return ['image']
  if (kind === 'file') return ['file']
  if (kind === 'canvas') return ['canvas']
  return ['pdp']
}

export function canHandle(kinds: string[], kind: string): boolean {
  return requiredKinds(kind).every((k) => kinds.includes(k))
}

/** Who may load a Skill: `any` means both specialists can. */
export const AUDIENCE_LABEL: Record<string, string> = {
  general: '通用', pdp: 'PDP', image: '图片', any: '通用 · PDP · 图片',
}

export function skillAudience(a: string): 'general' | 'pdp' | 'image' {
  return a === 'pdp' || a === 'image' ? a : 'general'
}

export const INTERP_LABEL = {
  parameter_patch: '参数修改',
  new_constraint: '新约束',
  question: '提问',
  strategy_switch: '换策略',
} as const

export const STATUS_LABEL: Record<string, string> = {
  draft: '草稿',
  running: '进行中',
  awaiting_user: '等待确认',
  accepted: '已接受',
  abandoned: '已放弃',
}

export const pLabel = (seq: number): string => `P${seq}`
export const vLabel = (seq: number): string => `v${seq}`

/** Failed-rule messages recorded on a version. */
export function problemsOf(v: Pick<VersionView, 'evaluations'>): string[] {
  return v.evaluations
    .filter((e) => !e.passed)
    .flatMap((e) => (e.details.problems as string[] | undefined) ?? [e.evaluator_id])
}

export const currentVersion = (a: ArtifactView | undefined): VersionView | undefined =>
  a?.versions.find((v) => v.id === a.current_version_id)

/** `edit_product_image · 主图` */
export function stepName(s: TimelineStep): string {
  if (s.tool === 'ask_question') return '向用户提问'
  return s.slot ? `${s.tool} · ${slotLabel(s.slot)}` : s.tool
}

export function fmtTime(iso: string): string {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getMonth() + 1}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
