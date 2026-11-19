import type { ReactNode } from 'react'

export function Tag({ cls = '', children }: { cls?: '' | 'ok' | 'bad' | 'warn' | 'imp'; children: ReactNode }) {
  return <span className={`x-tag${cls ? ` ${cls}` : ''}`}>{children}</span>
}
