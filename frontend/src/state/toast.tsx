import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'

const Ctx = createContext<(msg: string) => void>(() => {})

export function ToastProvider({ children }: { children: ReactNode }) {
  const [msg, setMsg] = useState('')
  const [visible, setVisible] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const show = useCallback((m: string) => {
    setMsg(m)
    setVisible(true)
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => setVisible(false), 2600)
  }, [])
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])
  return (
    <Ctx.Provider value={show}>
      {children}
      <div role="status" style={{ ...toastStyle, opacity: visible ? 1 : 0 }}>{msg}</div>
    </Ctx.Provider>
  )
}

// The workbench stylesheet has no .toast rule; this is the prototype's image-design toast.
const toastStyle: React.CSSProperties = {
  position: 'fixed', bottom: 24, left: '50%', transform: 'translateX(-50%)', padding: '10px 18px',
  background: 'var(--fg)', color: 'var(--accent-on)', fontSize: 13, borderRadius: 9999, zIndex: 300,
  opacity: 0, pointerEvents: 'none', transition: 'opacity .2s',
}

export const useToast = () => useContext(Ctx)
