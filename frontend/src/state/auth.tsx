import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useMemo, type ReactNode } from 'react'
import type { AuthStatus, SessionUser } from '../api/types'
import { useApi } from './api-context'

export const AUTH_KEY = ['auth', 'status'] as const

interface AuthApi {
  status: AuthStatus | undefined
  user: SessionUser | null
  loading: boolean
  /** Re-read /api/auth/status. Call after login, logout, and after a 401. */
  refresh: () => Promise<void>
  logout: () => Promise<void>
}

const Ctx = createContext<AuthApi | null>(null)

/**
 * Who am I, and may I use the app?
 *
 * The backend is the only judge: `/api/auth/status` reports whether a session cookie is
 * valid and whether dev identity (the X-User-Id header) is enabled. The UI never decides
 * that on its own, and never reads a role out of local storage.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const api = useApi()
  const qc = useQueryClient()
  const q = useQuery({ queryKey: AUTH_KEY, queryFn: () => api.authStatus(), retry: false })

  const refresh = useCallback(async () => {
    await qc.invalidateQueries({ queryKey: AUTH_KEY })
  }, [qc])

  const logout = useCallback(async () => {
    try {
      await api.logout()
    } finally {
      // Drop every cached query EXCEPT the auth probe. `qc.clear()` would also remove that
      // one, and with it the mounted observer, so the app would sit on a stale "signed in"
      // state until a manual reload. Removing by predicate keeps the gate live.
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== 'auth' })
      await refresh()
    }
  }, [api, qc, refresh])

  const value = useMemo<AuthApi>(
    () => ({
      status: q.data,
      user: q.data?.authenticated ? (q.data.user ?? null) : null,
      loading: q.isLoading,
      refresh,
      logout,
    }),
    [q.data, q.isLoading, refresh, logout],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAuth(): AuthApi {
  const c = useContext(Ctx)
  if (!c) throw new Error('AuthProvider is missing')
  return c
}

export function isAdmin(user: SessionUser | null): boolean {
  return user?.role === 'admin'
}
