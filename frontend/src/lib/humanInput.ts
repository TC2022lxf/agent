import type { HumanInputRequest } from '../api/types'

/** Canned reply labels for `AnswerOptions`-style buttons. */
export function humanInputOptionLabels(req: HumanInputRequest): string[] {
  return (req.options ?? []).map((o) => o.value || o.label)
}

/** Latest interaction request on a turn, if any. */
export function lastHumanInput(turn: { human_input_requests?: HumanInputRequest[] }): HumanInputRequest | null {
  const list = turn.human_input_requests ?? []
  return list.length ? list[list.length - 1]! : null
}

export function parseHumanInputEvent(data: unknown): HumanInputRequest | null {
  if (!data || typeof data !== 'object') return null
  const d = data as Record<string, unknown>
  if (d.kind !== 'human_input_request' || typeof d.question !== 'string') return null
  return data as HumanInputRequest
}
