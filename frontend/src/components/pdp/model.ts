import type { ArtifactView, FeedbackView, PlatformConstraints, VersionView } from '../../api/types'
import { slotLabel } from '../../lib/labels'

export interface SlotRow {
  slot: string
  label: string
  artifact: ArtifactView
  current: VersionView | undefined
  versions: VersionView[]
}

export function slotRows(artifacts: ArtifactView[]): SlotRow[] {
  return artifacts
    .filter((a) => a.slot && PDP_SLOTS.includes(a.slot))
    .map((a) => ({
      slot: a.slot as string,
      label: slotLabel(a.slot as string),
      artifact: a,
      current: a.versions.find((v) => v.id === a.current_version_id),
      versions: a.versions,
    }))
}

/** The slots a PDP manifest can point at. A general Task also holds files; those are not PDP. */
export const PDP_SLOTS = [
  'main_image', 'secondary_image', 'title', 'bullets', 'description', 'search_terms',
]

export const rowOf = (rows: SlotRow[], slot: string): SlotRow | undefined => rows.find((r) => r.slot === slot)

export interface CheckLine {
  code: string
  ok: boolean
  /** Rule checks only exist today; model checks arrive with docs/09 evaluators. */
  kind: 'rule' | 'model'
  message: string
  baseline: boolean
  fixed: boolean
}

/** One line per evaluator result of a version. `fixed`: failed on the imported baseline, passes now. */
export function checkLines(v: VersionView | undefined, first: VersionView | undefined): CheckLine[] {
  if (!v) return []
  return v.evaluations.map((e) => {
    const problems = (e.details.problems as string[] | undefined) ?? []
    const baselineFail =
      first?.origin === 'imported' && first.evaluations.some((x) => x.evaluator_id === e.evaluator_id && !x.passed)
    return {
      code: e.evaluator_id,
      ok: e.passed,
      kind: 'rule',
      message: e.passed ? '通过' : problems.join('；') || '未通过',
      baseline: v.origin === 'imported' && !e.passed,
      fixed: Boolean(baselineFail) && v.origin !== 'imported' && e.passed,
    }
  })
}

export const failedCount = (v: VersionView | undefined): number =>
  v ? v.evaluations.filter((e) => !e.passed).length : 0

export function noteOf(v: VersionView, feedback: FeedbackView[]): { note: string; fb?: string } {
  const fb = feedback.find((f) => f.run_id === v.run_id && v.run_id !== null && (f.target_slot === v.slot || f.target_slot === null))
  switch (v.origin) {
    case 'imported': return { note: '导入的内容，直接成为当前版本' }
    case 'generated': return { note: v.created_by === 'user' ? '用户提供' : 'Agent 生成的第一版', fb: fb?.text }
    case 'user': return { note: '用户把它设为当前版本' }
    default: return { note: 'Agent 基于上一版修改', fb: fb?.text }
  }
}

export function limitOf(rules: PlatformConstraints | undefined, key: string): number | undefined {
  return rules?.items.find((i) => i.key === key)?.value
}

export const statusOf = (v: VersionView, currentId: string | null): 'current' | 'superseded' | 'rejected' | 'candidate' =>
  v.status === 'rejected' ? 'rejected' : v.status === 'candidate' ? 'candidate' : v.id === currentId ? 'current' : 'superseded'

export const STATUS_TEXT = { current: '当前', superseded: '已被取代', rejected: '已拒绝', candidate: '检查中' } as const
