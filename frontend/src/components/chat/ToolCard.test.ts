import { describe, expect, it } from 'vitest'
import type { TimelineStep, ToolStarted } from '../../api/types'
import { announcedCalls, toolCards } from './ToolCard'

const started = (id: string, tool: string, extra: Partial<ToolStarted> = {}): ToolStarted => ({
  tool_call_id: id,
  tool,
  slot: extra.slot ?? null,
  cost: extra.cost ?? 20,
  args: extra.args ?? {},
})

const step = (id: string, tool: string, extra: Partial<TimelineStep> = {}): TimelineStep => ({
  tool_call_id: id,
  tool,
  slot: extra.slot ?? null,
  ok: extra.ok ?? true,
  error: extra.error ?? null,
  duration_ms: extra.duration_ms ?? 1200,
  cost: extra.cost ?? 20,
  base_version_id: null,
  patch: null,
  input: extra.input,
  output: extra.output,
})

describe('toolCards', () => {
  it('shows a call that has started but not finished as running', () => {
    const cards = toolCards([started('r:1', 'generate_product_image')], [])
    expect(cards).toHaveLength(1)
    expect(cards[0]).toMatchObject({ id: 'r:1', state: 'running', durationMs: null })
  })

  it('turns the same card into a finished one when the record arrives — never two rows', () => {
    const cards = toolCards(
      [started('r:1', 'generate_product_image')],
      [step('r:1', 'generate_product_image', { output: { version_id: 'ver_x' } })],
    )
    expect(cards).toHaveLength(1)
    expect(cards[0]).toMatchObject({
      id: 'r:1', state: 'ok', durationMs: 1200, versionId: 'ver_x',
    })
  })

  it('keeps calls in the order they were announced', () => {
    const cards = toolCards(
      [started('a', 'web_search'), started('b', 'write_file')],
      [step('b', 'write_file'), step('a', 'web_search')],
    )
    expect(cards.map((c) => c.id)).toEqual(['a', 'b'])  })

  it('keeps a failed call with its error and state', () => {
    const cards = toolCards([], [step('x', 'edit_listing', { ok: false, error: 'budget_exceeded' })])
    expect(cards[0]).toMatchObject({ state: 'error', error: 'budget_exceeded' })
  })

  it('gives a card to a recorded call that was never announced', () => {
    // A Run from before `tool_started` existed still gets a card: the record is the authority.
    const cards = toolCards([], [step('q', 'edit_listing')])
    expect(cards).toHaveLength(1)
    expect(cards[0]?.state).toBe('ok')
  })

  it('never draws a card for ask_question: it has its own panel', () => {
    const cards = toolCards(
      [started('q', 'ask_question')],
      [step('q', 'ask_question')],
    )
    expect(cards).toEqual([])
  })

  it('prefers the recorded arguments over the announced summary', () => {
    const cards = toolCards(
      [started('r:1', 'edit_listing', { args: { slot: 'title' } })],
      [step('r:1', 'edit_listing', { input: { slot: 'title', instruction: 'full text' } })],
    )
    expect(cards[0]?.args).toEqual({ slot: 'title', instruction: 'full text' })
  })

  it('exposes the version a call produced, for the card footer', () => {
    const cards = toolCards([], [step('v', 'write_file', { output: { version_id: 'ver_abc123' } })])
    expect(cards[0]?.versionId).toBe('ver_abc123')
  })

  it('ignores an announcement with no id', () => {
    const cards = toolCards([{ tool_call_id: '', tool: 'x', slot: null, cost: 0, args: {} }], [])
    expect(cards).toEqual([])
  })
})

describe('announcedCalls', () => {
  it('merges stored announcements with live ones', () => {
    const got = announcedCalls(
      [started('a', 'web_search')],
      [{ type: 'tool_started', data: { tool_call_id: 'b', tool: 'write_file', cost: 0, args: {} } }],
    )
    expect(got.map((c) => c.tool_call_id)).toEqual(['a', 'b'])
  })

  it('drops events that are not tool_started or are malformed', () => {
    const got = announcedCalls(undefined, [
      { type: 'step', data: { stage: 'think' } },
      { type: 'tool_started', data: { tool: 'no id' } },
      { type: 'tool_started', data: null },
    ])
    expect(got).toEqual([])
  })

  it('is safe with nothing at all', () => {
    expect(announcedCalls(undefined, undefined)).toEqual([])
  })
})
