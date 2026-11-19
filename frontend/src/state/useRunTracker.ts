import { useCallback, useEffect, useRef, useState } from 'react'
import { TERMINAL_EVENTS } from '../api/client'
import type { UtteranceBody } from '../api/types'
import { useApi } from './api-context'
import { useRefreshTask } from './useTaskData'

export interface RunEventLine {
  type: string
  data: unknown
}

/**
 * Posts an utterance (202), then follows the Run on SSE and refreshes server state as events
 * arrive. Nothing here decides what the Agent does. `send` resolves when the Run is finished,
 * so callers can queue several utterances one after another (one active Run per Task).
 */
export function useRunTracker(taskId: string | null, agentKey: string) {
  const api = useApi()
  const refresh = useRefreshTask(taskId)
  const [events, setEvents] = useState<RunEventLine[]>([])
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const unsub = useRef<(() => void) | null>(null)

  useEffect(() => () => unsub.current?.(), [])

  const send = useCallback(
    async (body: Omit<UtteranceBody, 'agent_id'>): Promise<void> => {
      if (!taskId) return
      setError(null)
      setEvents([])
      try {
        const run = await api.utter(taskId, { ...body, agent_id: agentKey })
        setRunId(run.id)
        setRunning(true)
        await refresh()
        unsub.current?.()
        await new Promise<void>((resolve) => {
          unsub.current = api.subscribeRun(run.id, (type, data) => {
            setEvents((prev) => [...prev, { type, data }])
            void refresh()
            if (TERMINAL_EVENTS.includes(type)) {
              setRunning(false)
              resolve()
            }
          })
        })
      } catch (e) {
        setRunning(false)
        setError(e instanceof Error ? e.message : String(e))
      }
    },
    [api, agentKey, refresh, taskId],
  )

  const cancel = useCallback(async () => {
    if (runId) {
      await api.cancelRun(runId)
      await refresh()
    }
  }, [api, refresh, runId])

  return { send, cancel, events, running, error }
}

export type RunTracker = ReturnType<typeof useRunTracker>
