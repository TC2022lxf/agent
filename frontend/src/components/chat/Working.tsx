import { useEffect, useState } from 'react'
import { progressOf } from '../../lib/progress'
import { streamingOf } from '../../lib/streaming'

/**
 * The line a user watches while the Agent works: a pulsing dot, the current stage, and how
 * long it has been. A Run that takes two minutes used to show one static sentence, which
 * reads as a hang; a moving counter says "still working" without inventing a percentage.
 *
 * Once the reply starts arriving it is shown as written, with the stage line underneath: the
 * answer used to appear only when the Run ended, so a model that had already said what it was
 * doing still looked like it was thinking (docs/06).
 *
 * The elapsed time is client-side only. It starts when this line mounts, which is the moment
 * the Run was accepted, so it is honest to within a poll interval and costs no server state.
 */
export function Working({ events }: { events: { type: string; data: unknown }[] }) {
  const [seconds, setSeconds] = useState(0)
  const { text, stage } = progressOf(events)
  const live = streamingOf(events)

  useEffect(() => {
    const started = Date.now()
    const id = window.setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000)
    return () => window.clearInterval(id)
  }, [])

  if (live.active) {
    return (
      <div className="working is-streaming" role="status" aria-live="polite" data-stage={stage}>
        <p className="working-stream">{live.text}</p>
        <p className="working">
          <span className="working-dot" aria-hidden="true" />
          <span className="working-text">{text}</span>
          {seconds >= 1 && <span className="working-elapsed">已用 {seconds}s</span>}
        </p>
      </div>
    )
  }

  return (
    <p className="working" role="status" aria-live="polite" data-stage={stage}>
      <span className="working-dot" aria-hidden="true" />
      <span className="working-text">{text}</span>
      {seconds >= 1 && <span className="working-elapsed">已用 {seconds}s</span>}
    </p>
  )
}
