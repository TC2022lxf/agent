import { describe, expect, it } from 'vitest'
import { TASK } from '../test-utils'
import { filledSlots, hasAnyVersion, openTargetFor } from './artifacts'
import type { TaskView } from '../api/types'

const task = (over: Partial<TaskView> = {}): TaskView => ({
  ...TASK, current: {}, pdp_version_id: null, ...over,
})

describe('artifact preview targets', () => {
  it('says a task has nothing to preview until a version exists', () => {
    expect(hasAnyVersion(task({ current: { title: null } }))).toBe(false)
    expect(hasAnyVersion(task({ current: { title: 'v1' } }))).toBe(true)
    expect(hasAnyVersion(task({ pdp_version_id: 'p1' }))).toBe(true)
  })

  it('lists only the slots that hold a version', () => {
    expect(filledSlots(task({ current: { title: 'v1', bullets: null, 'notes.md': 'v2' } })))
      .toEqual(['title', 'notes.md'])
  })

  it('opens a pdp drawer only when the manifest exists', () => {
    expect(openTargetFor(task({ kind: 'pdp', current: { title: 'v1' } }))).toBeNull()
    expect(openTargetFor(task({ kind: 'pdp', pdp_version_id: 'p1', current: { title: 'v1' } })))
      .toEqual({ kind: 'pdp' })
  })

  it('opens a general task by whatever it actually produced', () => {
    expect(openTargetFor(task({ kind: 'general', current: { 'notes.md': 'v1' } })))
      .toEqual({ kind: 'file', slot: 'notes.md' })
    expect(openTargetFor(task({ kind: 'general', current: { image: 'v1' } })))
      .toEqual({ kind: 'image', slot: 'image' })
    expect(openTargetFor(task({ kind: 'general', pdp_version_id: 'p1', current: { title: 'v1' } })))
      .toEqual({ kind: 'pdp' })
  })

  it('sends an image task to the image page, which handles the empty case itself', () => {
    expect(openTargetFor(task({ kind: 'image', current: { image: null } }))).toEqual({ view: 'image' })
  })
})
