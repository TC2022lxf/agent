import { useMemo, useState } from 'react'
import type { TimelineTurn } from '../../api/types'
import { vLabel } from '../../lib/labels'
import { useTaskData } from '../../state/useTaskData'
import {
  fileMedia, initialFileMode, parseTable, tableDelimiter, type FileViewMode,
} from './preview'

/** Drawer preview for one file version. The chat does not call the model from here. */
export function FilePanel({ taskId, slot }: { taskId: string; slot: string }) {
  const { artifacts, timeline } = useTaskData(taskId)
  const artifact = artifacts.data?.find((a) => a.slot === slot && a.kind === 'file')
    ?? artifacts.data?.find((a) => a.kind === 'file' && a.slot)
  const versions = artifact?.versions ?? []
  const current = versions.find((v) => v.id === artifact?.current_version_id) ?? versions.at(-1) ?? null
  const nameHint = current?.content.filename ?? artifact?.slot ?? slot
  const latest = latestWrite(timeline.data ?? [], nameHint)
  const showing = current ?? null
  const name = nameHint
  const media = fileMedia(name, showing?.content.media)
  const writeOk = latest ? latest.ok : showing?.status === 'ok'
  const draft = latest && !latest.ok ? latest.draft : null
  const versionKey = showing?.id ?? 'draft'
  const [picked, setPicked] = useState<{ id: string; mode: FileViewMode } | null>(null)
  const mode = picked?.id === versionKey ? picked.mode : initialFileMode(media, writeOk)
  const text = !writeOk && draft ? draft : (showing?.content.text ?? '')

  const table = useMemo(
    () => (media === 'table' ? parseTable(showing?.content.text ?? '', tableDelimiter(name)) : []),
    [media, name, showing?.content.text],
  )

  return (
    <div className="file-stage">
      <div className="file-toolbar">
        <strong>{name}</strong>
        {showing && <span className="x-chip-s">{vLabel(showing.seq)}</span>}
        {media === 'html' && showing && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setPicked({ id: versionKey, mode: mode === 'preview' ? 'code' : 'preview' })}>
            {mode === 'preview' ? '源码' : '预览'}
          </button>
        )}
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => downloadFile(name, text, showing?.content.mime, showing?.content.url)}>
          下载
        </button>
      </div>
      {!writeOk && draft && <p className="x-fail">这一次没有写入成功，停在源码。</p>}
      {mode === 'code' ? (
        <pre className="file-source">{text || '还没有写入成功的正文。'}</pre>
      ) : media === 'html' ? (
        <iframe className="file-frame" title={name} sandbox="allow-scripts" srcDoc={showing?.content.text ?? ''} />
      ) : media === 'markdown' ? (
        <Markdown text={showing?.content.text ?? ''} />
      ) : media === 'table' ? (
        <Table rows={table} />
      ) : media === 'iframe' && showing?.content.url ? (
        <iframe className="file-frame" title={name} src={showing.content.url} />
      ) : (
        <p className="x-ghost">这个文件只提供下载。</p>
      )}
    </div>
  )
}

function latestWrite(turns: TimelineTurn[], slot: string): { ok: boolean; draft: string | null } | null {
  for (let i = turns.length - 1; i >= 0; i -= 1) {
    const steps = turns[i]?.steps ?? []
    for (let j = steps.length - 1; j >= 0; j -= 1) {
      const step = steps[j]
      if (!step) continue
      if (step.tool === 'write_file' && (step.path === slot || step.slot === slot)) {
        return { ok: step.ok, draft: step.draft ?? null }
      }
    }
  }
  return null
}

function downloadFile(name: string, text: string, mime?: string, url?: string) {
  const href = url || URL.createObjectURL(new Blob([text], { type: mime || 'text/plain' }))
  const a = document.createElement('a')
  a.href = href
  a.download = name
  a.click()
  if (!url) URL.revokeObjectURL(href)
}

function Table({ rows }: { rows: string[][] }) {
  if (rows.length === 0) return <p className="x-ghost">空表格</p>
  const head = rows[0] ?? []
  const body = rows.slice(1)
  return (
    <table className="file-table">
      <thead><tr>{head.map((cell, j) => <th key={j}>{cell}</th>)}</tr></thead>
      <tbody>
        {body.map((row, i) => (
          <tr key={i}>{row.map((cell, j) => <td key={j}>{cell}</td>)}</tr>
        ))}
      </tbody>
    </table>
  )
}

function Markdown({ text }: { text: string }) {
  const blocks = text.split(/\n{2,}/)
  return (
    <div className="file-md">
      {blocks.map((block, i) => {
        const line = block.trim()
        if (line.startsWith('# ')) return <h1 key={i}>{line.slice(2)}</h1>
        if (line.startsWith('## ')) return <h2 key={i}>{line.slice(3)}</h2>
        return <p key={i}>{line}</p>
      })}
    </div>
  )
}
