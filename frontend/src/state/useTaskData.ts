import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback } from 'react'
import { useApi } from './api-context'

export const keys = {
  tasks: ['tasks'] as const,
  task: (id: string) => ['task', id] as const,
  timeline: (id: string) => ['timeline', id] as const,
  artifacts: (id: string) => ['artifacts', id] as const,
  feedback: (id: string) => ['feedback', id] as const,
  constraints: (id: string) => ['constraints', id] as const,
  products: ['products'] as const,
  me: ['me'] as const,
}

/** Server state only (docs/architecture/data-and-contracts.md): everything shown comes from the API, never from local copies. */
export function useTaskData(taskId: string | null) {
  const api = useApi()
  const enabled = taskId !== null
  const id = taskId ?? ''
  const task = useQuery({ queryKey: keys.task(id), queryFn: () => api.getTask(id), enabled })
  const timeline = useQuery({ queryKey: keys.timeline(id), queryFn: () => api.timeline(id), enabled })
  const artifacts = useQuery({ queryKey: keys.artifacts(id), queryFn: () => api.artifacts(id), enabled })
  const feedback = useQuery({ queryKey: keys.feedback(id), queryFn: () => api.feedback(id), enabled })
  const constraints = useQuery({ queryKey: keys.constraints(id), queryFn: () => api.constraints(id), enabled })
  return { task, timeline, artifacts, feedback, constraints }
}

export function useRefreshTask(taskId: string | null) {
  const qc = useQueryClient()
  return useCallback(async () => {
    if (!taskId) return
    await Promise.all([
      qc.invalidateQueries({ queryKey: keys.task(taskId) }),
      qc.invalidateQueries({ queryKey: keys.timeline(taskId) }),
      qc.invalidateQueries({ queryKey: keys.artifacts(taskId) }),
      qc.invalidateQueries({ queryKey: keys.feedback(taskId) }),
      qc.invalidateQueries({ queryKey: keys.constraints(taskId) }),
      qc.invalidateQueries({ queryKey: keys.me }),
      qc.invalidateQueries({ queryKey: keys.tasks }),
    ])
  }, [qc, taskId])
}
