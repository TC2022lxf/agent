import type { RunEventLine } from '../state/useRunTracker'

/**
 * The reply text as it is being written, and whether it has started.
 *
 * `answer_delta` carries the whole text so far (not a fragment), so a late or reconnecting
 * subscriber sees the same value as a live one: the newest event wins and is never
 * concatenated. A finished Run gets its authoritative text from the `answer` event instead,
 * because the delta rows are a live stream and the `answer` is the record.
 */
export function streamingOf(events: RunEventLine[]): { text: string; active: boolean } {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const e = events[i]
    if (!e) continue
    if (e.type === 'answer') return { text: '', active: false }
    if (e.type === 'answer_delta') {
      const data = (e.data ?? {}) as { text?: unknown }
      const text = typeof data.text === 'string' ? data.text : ''
      return { text, active: text.length > 0 }
    }
    // A Tool call means the reply ended and the Run moved on to doing the work.
    if (e.type === 'step') {
      const data = (e.data ?? {}) as { stage?: unknown }
      const stage = typeof data.stage === 'string' ? data.stage : ''
      if (stage === 'running' || stage === 'tool') return { text: '', active: false }
    }
  }
  return { text: '', active: false }
}
