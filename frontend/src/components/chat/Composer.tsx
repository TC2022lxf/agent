import { useEffect, useRef, useState } from 'react'
import type { AgentInfo } from '../../api/types'
import type { FocusTarget } from '../../state/nav'
import { humanSize, type StagedFile } from './attachments'

export interface SlashSkill { id: string; description: string; audience?: string }

/**
 * Chat input: `+` for files, `/` for Skills, and a task picker that switches the Agent.
 * The picker is the only place an entry changes; it never guesses from the sentence.
 */
export function Composer({ running, disabled, target, skills, agents, agentKey, onAgent, onClearTarget, onSend, onCancel, onAttach, reasoning, onReasoning, onCompact, progress }: {
  running: boolean
  disabled: boolean
  progress?: string
  target: FocusTarget | null
  skills: SlashSkill[]
  agents: AgentInfo[]
  agentKey: string
  onAgent: (key: string) => void
  onClearTarget: () => void
  onSend: (text: string, hint?: 'constraint' | 'preference', skillId?: string, attachmentIds?: string[]) => void
  onCancel: () => void
  onAttach: (files: File[]) => Promise<StagedFile[]>
  reasoning?: boolean
  onReasoning?: (value: boolean) => void
  onCompact?: () => void
}) {
  const [text, setText] = useState('')
  const [hint, setHint] = useState<'constraint' | 'preference' | null>(null)
  const [files, setFiles] = useState<StagedFile[]>([])
  const [uploading, setUploading] = useState(false)
  const [picker, setPicker] = useState<'agent' | 'skill' | null>(null)
  const input = useRef<HTMLInputElement>(null)

  const slash = text.startsWith('/') && !text.includes(' ')
  const matches = slash ? skills.filter((s) => s.id.includes(text.slice(1))) : []
  const picked = /^\/([a-z0-9-]+)\s/.exec(text)
  const activeSkill = picked ? skills.find((s) => s.id === picked[1])?.id : undefined
  const current = agents.find((a) => a.key === agentKey)

  useEffect(() => {
    if (!picker) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setPicker(null) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [picker])

  const submit = () => {
    const t = text.trim()
    if (!t || disabled) return
    onSend(t, hint ?? undefined, activeSkill, files.map((f) => f.upload_id))
    setText('')
    setHint(null)
    setFiles([])
  }

  const attach = async (list: FileList | null) => {
    if (!list || list.length === 0) return
    setUploading(true)
    try {
      const staged = await onAttach([...list])
      setFiles((prev) => [...prev, ...staged])
    } finally {
      setUploading(false)
      if (input.current) input.current.value = ''
    }
  }

  return (
    <div className="chat-composer">
      <div className="x-target-row">
        <span className="x-target">任务：{current?.title ?? agentKey}</span>
        <button type="button" className="x-chip" aria-expanded={picker === 'agent'} onClick={() => setPicker(picker === 'agent' ? null : 'agent')}>
          切换任务
        </button>
        <span className="x-target">目标：{target ? target.label : '整个任务'}</span>
        {target && <button type="button" className="x-link" onClick={onClearTarget}>清除</button>}
        <button type="button" className="x-chip" aria-pressed={hint === 'constraint'}
          style={hint === 'constraint' ? { outline: '1px solid var(--accent)' } : undefined}
          onClick={() => setHint(hint === 'constraint' ? null : 'constraint')}>记成长期约束</button>
        <button type="button" className="x-chip" aria-pressed={hint === 'preference'}
          style={hint === 'preference' ? { outline: '1px solid var(--accent)' } : undefined}
          onClick={() => setHint(hint === 'preference' ? null : 'preference')}>写入我的偏好</button>
        {onReasoning && (
          <button type="button" className="x-chip" aria-pressed={reasoning} onClick={() => onReasoning(!reasoning)}>
            推理{reasoning ? '开' : '关'}
          </button>
        )}
        {onCompact && <button type="button" className="x-chip" onClick={onCompact}>总结到这里</button>}
      </div>

      {picker === 'agent' && (
        <div className="composer-menu" role="listbox" aria-label="选择任务">
          {agents.map((a) => (
            <button key={a.key} type="button" role="option" aria-selected={a.key === agentKey}
              className={a.key === agentKey ? 'is-on' : ''}
              onClick={() => { onAgent(a.key); setPicker(null) }}>
              <b>{a.title}</b>
              <span>{a.description || a.artifact_kinds.join(' · ')}</span>
            </button>
          ))}
        </div>
      )}

      {files.length > 0 && (
        <div className="attach-row">
          {files.map((f) => (
            <span key={f.upload_id} className="attach-chip">
              <b>{f.name}</b>
              <span>{humanSize(f.size)}{f.kind === 'image' ? ' · 图片' : f.readable ? ' · 可读' : ' · 仅下载'}</span>
              <button type="button" aria-label={`移除 ${f.name}`} onClick={() => setFiles(files.filter((x) => x.upload_id !== f.upload_id))}>×</button>
            </span>
          ))}
        </div>
      )}

      <div className="composer-wrap">
        <div className={`slash-menu${matches.length ? ' is-open' : ''}`} role="listbox" aria-label="可用技能">
          {matches.map((s) => (
            <button key={s.id} type="button" role="option" aria-selected={false}
              onClick={() => { setText(`/${s.id} `); setPicker(null) }}>
              <b>/{s.id}</b> <span>{s.description}</span>
            </button>
          ))}
        </div>
        <div className="composer-inner gpt-composer">
          <input ref={input} type="file" multiple hidden aria-label="上传文件" onChange={(e) => void attach(e.target.files)} />
          <button type="button" className="gpt-plus" aria-label="添加文件" disabled={uploading || disabled}
            onClick={() => input.current?.click()}>{uploading ? '…' : '+'}</button>
          <button type="button" className="gpt-plus" aria-label="选择技能" aria-expanded={picker === 'skill'}
            onClick={() => setPicker(picker === 'skill' ? null : 'skill')}>/</button>
          <textarea rows={1} value={text} aria-label="消息输入"
            placeholder="说出你的意见，或先点预览里的区域再说。输入 / 指定 Skill，+ 上传文件"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit() }
            }} />
          {running
            ? <button type="button" className="gpt-send is-stop" aria-label="停止生成" title="停止生成" onClick={onCancel}>
                <svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="3" fill="currentColor" /></svg>
              </button>
            : <button type="button" className="gpt-send" aria-label="发送" disabled={disabled || !text.trim()} onClick={submit}>
                <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M12 19V5M6 11l6-6 6 6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
              </button>}
        </div>
        {running && (
          <p className="composer-status" role="status" aria-live="polite">
            {progress ? `${progress}…` : '正在处理…'}
          </p>
        )}
      </div>

      {picker === 'skill' && (
        <div className="composer-menu" role="listbox" aria-label="技能列表">
          {skills.map((s) => (
            <button key={s.id} type="button" role="option" aria-selected={activeSkill === s.id}
              className={activeSkill === s.id ? 'is-on' : ''}
              onClick={() => { setText(`/${s.id} `); setPicker(null) }}>
              <b>/{s.id}</b>
              <span>{s.description}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
