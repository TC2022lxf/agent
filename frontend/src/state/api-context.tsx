import { createContext, useContext, type ReactNode } from 'react'
import type { ApiClient } from '../api/client'

const Ctx = createContext<ApiClient | null>(null)

export function ApiProvider({ client, children }: { client: ApiClient; children: ReactNode }) {
  return <Ctx.Provider value={client}>{children}</Ctx.Provider>
}

export function useApi(): ApiClient {
  const c = useContext(Ctx)
  if (!c) throw new Error('ApiProvider is missing')
  return c
}
