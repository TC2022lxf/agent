import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import type { SlotKey } from '../api/types'

export type ViewName =
  | 'home' | 'chat' | 'history' | 'artifacts' | 'products' | 'tools' | 'skills'
  | 'automation' | 'canvas' | 'image' | 'console' | 'account' | 'admin'

/** Which workbench is open in the right-hand drawer (docs/06). */
export interface DrawerTarget {
  kind: 'pdp' | 'image' | 'rules' | 'file'
  slot?: SlotKey
}

/** What the next utterance is bound to (target_slot). Set by clicking a region in a preview. */
export interface FocusTarget {
  slot: SlotKey
  label: string
  versionId?: string
}

export interface NavState {
  view: ViewName
  /** Entry the user chose: `general` or `amazon_pdp` for the chat view (decisions/0010). */
  agent: string
  taskId: string | null
  drawer: DrawerTarget | null
  target: FocusTarget | null
  productId: string | null
  toolName: string | null
  skillId: string | null
  /** Image Agent page: which task and slot it is focused on. */
  imageTaskId: string | null
  imageSlot: SlotKey | null
  /** Canvas Agent page: which task it shows. */
  canvasTaskId: string | null
  /** First sentence to send once the new task is on screen. */
  bootText: string | null
}

const INITIAL: NavState = {
  view: 'chat', agent: 'general', taskId: null, drawer: null, target: null,
  productId: null, toolName: null, skillId: null, imageTaskId: null, imageSlot: null,
  canvasTaskId: null, bootText: null,
}

interface NavApi {
  nav: NavState
  go(patch: Partial<NavState>): void
  openTask(taskId: string, agent?: string): void
  openDrawer(d: DrawerTarget | null): void
}

const Ctx = createContext<NavApi | null>(null)

export function NavProvider({ children, initial }: { children: ReactNode; initial?: Partial<NavState> }) {
  const [nav, setNav] = useState<NavState>({ ...INITIAL, ...initial })
  const go = useCallback((patch: Partial<NavState>) => setNav((n) => ({ ...n, ...patch })), [])
  const openTask = useCallback(
    (taskId: string, agent?: string) =>
      setNav((n) => ({ ...n, view: 'chat', taskId, agent: agent ?? n.agent, drawer: null, target: null })),
    [],
  )
  const openDrawer = useCallback((drawer: DrawerTarget | null) => setNav((n) => ({ ...n, drawer })), [])
  const value = useMemo(() => ({ nav, go, openTask, openDrawer }), [nav, go, openTask, openDrawer])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useNav(): NavApi {
  const c = useContext(Ctx)
  if (!c) throw new Error('NavProvider is missing')
  return c
}
