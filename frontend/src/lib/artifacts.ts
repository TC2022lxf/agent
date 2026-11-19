import type { TaskView } from '../api/types'

/** Slots a PDP manifest points at. Anything else a task holds is a file name. */
export const PDP_SLOTS = [
  'main_image', 'secondary_image', 'title', 'bullets', 'description', 'search_terms',
] as const

const PDP_SLOT_SET = new Set<string>(PDP_SLOTS)

/** Does this task have anything to preview? Preview is a rendering of an existing Version. */
export function hasAnyVersion(t: TaskView): boolean {
  return Boolean(t.pdp_version_id) || Boolean(t.canvas_version_id) || Object.values(t.current ?? {}).some(Boolean)
}

/** The slots of this task that currently hold a Version. */
export function filledSlots(t: TaskView): string[] {
  return Object.entries(t.current ?? {})
    .filter(([, versionId]) => Boolean(versionId))
    .map(([slot]) => slot)
}

export type OpenTarget =
  | { view: 'image' }
  | { view: 'canvas' }
  | { kind: 'pdp' }
  | { kind: 'image'; slot: string }
  | { kind: 'file'; slot: string }

/**
 * Where clicking a project should land. Decided by what exists, not by what the task kind
 * could theoretically produce: a Task with nothing in it has no preview to open.
 */
export function openTargetFor(t: TaskView): OpenTarget | null {
  if (t.kind === 'image') return { view: 'image' }
  if (t.kind === 'canvas') return { view: 'canvas' }
  if (t.pdp_version_id) return { kind: 'pdp' }
  if (t.canvas_version_id) return { view: 'canvas' }
  const slots = filledSlots(t)
  const image = slots.find((s) => s === 'image')
  if (image) return { kind: 'image', slot: image }
  const file = slots.find((s) => !PDP_SLOT_SET.has(s) && s !== 'canvas')
  if (file) return { kind: 'file', slot: file }
  return null
}
