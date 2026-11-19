import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { NormRect } from '../../api/types'
import { useToast } from '../../state/toast'
import { buildImageUtterance } from './utterance'
import { rectToStyle, useMarkTool } from './useMarkTool'

interface Mark { id: number; rect: NormRect; prompt: string }

const NODE_W = 520
const DOTS = ['tl', 'tr', 'bl', 'br'] as const

export type ImageStripVersion = {
  id: string
  seq: number
  url: string
  status: 'candidate' | 'ok' | 'rejected'
  isArtifactCurrent: boolean
}

/**
 * One image canvas for the Image Agent page and the drawer.
 * Zoom and pan only change the view. A mark is one normalized rect and one utterance.
 * Page mode: top filmstrip picks the edit base; the side node is that version's parent.
 */
export function ImageWorkbench({
  variant, imageUrl, alt, versionId, slot, label, prevUrl, prevLabel, width, height,
  reasoning, busy, onFeedback, onClose, onUpload,
  stripVersions, focusVersionId, onFocusVersion,
}: {
  variant: 'page' | 'drawer'
  imageUrl: string
  alt: string
  versionId: string
  slot: string
  label: string
  prevUrl?: string
  prevLabel?: string
  width?: number
  height?: number
  reasoning?: boolean
  busy?: boolean
  onFeedback: (body: ReturnType<typeof buildImageUtterance>) => Promise<unknown> | void
  onClose?: () => void
  onUpload?: () => void
  /** Newest-first row of thumbnails; page mode only. */
  stripVersions?: ImageStripVersion[]
  focusVersionId?: string
  onFocusVersion?: (versionId: string) => void
}) {
  const toast = useToast()
  const [marks, setMarks] = useState<Mark[]>([])
  const [markMode, setMarkMode] = useState(true)
  const [panelOpen, setPanelOpen] = useState(false)
  const [scale, setScale] = useState(0.62)
  const [pan, setPan] = useState({ x: 30, y: 10 })
  const [aspect, setAspect] = useState(width && height ? width / height : 1)
  const [prompt, setPrompt] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const nextId = useRef(1)
  const viewport = useRef<HTMLDivElement>(null)
  const nodeRef = useRef<HTMLDivElement>(null)
  const [toolbarPos, setToolbarPos] = useState<{ left: number; top: number } | null>(null)
  const panning = useRef<{ x: number; y: number; px: number; py: number } | null>(null)

  useEffect(() => { setMarks([]); setPrompt('') }, [versionId, slot])
  useEffect(() => { if (width && height) setAspect(width / height) }, [width, height])
  const nodeH = NODE_W / aspect

  // The canvas column is now half the window, so a fixed 0.62 scale put a 520px node past the
  // right edge on a laptop. Fit the node to whatever width the column actually has, and centre
  // it, once per version. The user's own zoom/pan afterwards is left alone.
  useLayoutEffect(() => {
    if (variant !== 'page') return
    const box = viewport.current?.getBoundingClientRect()
    if (!box || box.width < 80 || box.height < 80) return
    const PAD = 96  // room for the node toolbar above and breathing space at the sides
    const fit = Math.min((box.width - PAD) / NODE_W, (box.height - PAD * 2) / nodeH, 1)
    const next = Math.max(0.15, +fit.toFixed(2))
    setScale(next)
    setPan({
      x: Math.max(16, (box.width - NODE_W * next) / 2),
      y: Math.max(16, (box.height - nodeH * next) / 2),
    })
  }, [variant, versionId, nodeH])

  useLayoutEffect(() => {
    if (variant !== 'page') return
    const v = viewport.current?.getBoundingClientRect()
    const n = nodeRef.current?.getBoundingClientRect()
    if (v && n) setToolbarPos({ left: n.left - v.left + n.width / 2, top: Math.max(64, n.top - v.top - 52) })
  }, [scale, pan, versionId, nodeH, variant])

  const mark = useMarkTool(markMode && !submitting && !busy, (rect) => {
    setMarks((m) => [...m, { id: nextId.current++, rect, prompt: '' }])
    setPanelOpen(true)
  })

  const submit = async () => {
    if (variant === 'drawer') {
      const text = prompt.trim()
      if (!marks[0]) { toast('先在图上圈选一块区域'); return }
      if (!text) { toast('每个圈选都要写一句话'); return }
      setSubmitting(true)
      await onFeedback(buildImageUtterance({
        text, slot, versionId, region: marks[0].rect, reasoning,
      }))
      setMarks([])
      setPrompt('')
      setSubmitting(false)
      return
    }
    if (marks.length === 0) { toast('先在图上圈选一块区域'); return }
    if (marks.some((m) => !m.prompt.trim())) { toast('每个圈选都要写一句话'); return }
    setSubmitting(true)
    for (const m of marks) {
      await onFeedback(buildImageUtterance({
        text: m.prompt.trim(), slot, versionId, region: m.rect, reasoning,
      }))
    }
    setMarks([])
    setSubmitting(false)
    toast(`已提交 ${marks.length} 条带区域的反馈`)
  }

  const stage = (
    <div className="img-node-inner" style={{ background: '#fff' }} {...mark.bind} data-testid="mark-surface">
      <img src={imageUrl} alt={alt} draggable={false}
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'contain', pointerEvents: 'none' }}
        onLoad={(e) => {
          const i = e.currentTarget
          if (i.naturalWidth && i.naturalHeight) setAspect(i.naturalWidth / i.naturalHeight)
        }} />
      <div className="mark-layer">
        {marks.map((m) => (
          <div key={m.id} className="mark-rect" data-testid="mark-rect" style={rectToStyle(m.rect)}>
            {DOTS.map((d) => <span key={d} className={`mark-dot ${d}`} />)}
          </div>
        ))}
        {mark.draft && <div className="mark-rect" style={rectToStyle(mark.draft)} />}
      </div>
    </div>
  )

  if (variant === 'drawer') {
    return (
      <div className="x-workbench">
        <div className="x-imgwrap"><div className="x-main-frame" style={{ position: 'relative', minHeight: 180 }}>{stage}</div></div>
        <input aria-label="圈选说明" value={prompt} placeholder="这一块要怎么改" onChange={(e) => setPrompt(e.target.value)} />
        <div className="x-focus-row">
          <button type="button" className="btn btn-teal btn-sm" disabled={submitting || busy} onClick={() => void submit()}>作为反馈提交</button>
          <button type="button" className="btn btn-sm" disabled>HD Upscale · 实验</button>
          <button type="button" className="btn btn-sm" disabled>Remove bg · 实验</button>
        </div>
      </div>
    )
  }

  const zoom = (d: number) => setScale((s) => Math.min(2, Math.max(0.1, +(s + d).toFixed(2))))
  const strip = stripVersions ?? []
  return (
    <div ref={viewport} className={`canvas-viewport${markMode ? ' is-mark' : ''}`} data-testid="canvas-viewport"
      onPointerDown={(e) => {
        if (e.target !== e.currentTarget && !(e.target as HTMLElement).classList.contains('canvas-world')) return
        panning.current = { x: e.clientX, y: e.clientY, px: pan.x, py: pan.y }
        e.currentTarget.setPointerCapture?.(e.pointerId)
      }}
      onPointerMove={(e) => {
        const p = panning.current
        if (p) setPan({ x: p.px + e.clientX - p.x, y: p.py + e.clientY - p.y })
      }}
      onPointerUp={() => { panning.current = null }}
      onWheel={(e) => { if (e.ctrlKey || e.metaKey) zoom(e.deltaY < 0 ? 0.05 : -0.05) }}>
      {strip.length > 0 && (
        <div className="img-version-strip" role="tablist" aria-label="版本历史" data-testid="version-strip">
          {strip.map((v) => (
            <button
              key={v.id}
              type="button"
              role="tab"
              aria-selected={v.id === focusVersionId}
              data-testid={`version-thumb-${v.id}`}
              className={`img-version-thumb${v.id === focusVersionId ? ' is-focus' : ''}${v.isArtifactCurrent ? ' is-current' : ''}`}
              title={`v${v.seq}${v.isArtifactCurrent ? ' · 当前交付' : ''}`}
              onClick={() => onFocusVersion?.(v.id)}
            >
              <img src={v.url} alt="" draggable={false} />
              <span className="img-version-thumb-label">v{v.seq}</span>
            </button>
          ))}
        </div>
      )}
      <span className="img-preview-mark">图片预览</span>
      <button type="button" className="canvas-chrome-btn canvas-save btn-ghost" disabled>{label}</button>
      <button type="button" className="canvas-chrome-btn canvas-close" title="回到对话" aria-label="关闭" onClick={onClose}>×</button>
      <div className="canvas-world" style={{ transform: `translate(${pan.x}px,${pan.y}px) scale(${scale})` }}>
        <div ref={nodeRef} className="img-node is-selected" data-testid="node-current" style={{ left: 80, top: 140, width: NODE_W, height: nodeH }}>
          <div className="img-node-meta"><span className="fname">{label}</span></div>
          {stage}
        </div>
        {prevUrl && (
          <div className="img-node" data-readonly="1" style={{ left: 80 + NODE_W + 80, top: 140, width: NODE_W, height: nodeH, opacity: 0.7 }}>
            <div className="img-node-meta"><span className="fname">{prevLabel}</span><span className="dims">只读</span></div>
            <div className="img-node-inner" style={{ background: '#fff' }}>
              <img src={prevUrl} alt={prevLabel} draggable={false}
                style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'contain' }} />
            </div>
          </div>
        )}
      </div>
      {toolbarPos && (
        <div className="node-toolbar is-visible" style={{ left: toolbarPos.left, top: toolbarPos.top }}>
          <button type="button" disabled>HD Upscale · 实验</button>
          <button type="button" disabled>Remove bg · 实验</button>
          <button type="button" className={markMode ? 'is-active' : ''} onClick={() => setMarkMode((m) => !m)}>Mark edit</button>
          <a className="tb-icon" href={imageUrl} download title="下载" aria-label="下载"
            style={{ display: 'inline-flex', alignItems: 'center', padding: '0 8px', color: 'inherit', textDecoration: 'none' }}>↓</a>
        </div>
      )}
      <aside className="v-toolbar" aria-label="画布工具">
        <button type="button" className={`v-tool${markMode ? '' : ' is-active'}`} title="拖动画布（空白处）" aria-label="选择" onClick={() => setMarkMode(false)}>选择</button>
        <button type="button" className="v-tool" title="上传参考图" aria-label="上传" onClick={onUpload}>上传</button>
        <button type="button" className={`v-tool${markMode ? ' is-active' : ''}`} title="Mark 圈选" aria-label="Mark" onClick={() => setMarkMode(true)}>Mark</button>
      </aside>
      <div className="canvas-zoom">
        <button type="button" aria-label="缩小" onClick={() => zoom(-0.1)}>−</button>
        <span>{Math.round(scale * 100)}%</span>
        <button type="button" aria-label="放大" onClick={() => zoom(0.1)}>+</button>
      </div>
      <div className={`task-panel${panelOpen ? '' : ' is-collapsed'}`}>
        <div className="task-panel-head" role="button" tabIndex={0} onClick={() => setPanelOpen((o) => !o)}>
          <span>圈选反馈</span>
          <span style={{ color: 'var(--muted)', fontWeight: 500 }}>{marks.length}</span>
        </div>
        <div className="task-panel-body">
          {marks.length === 0 && <div className="task-empty">在图上圈选一块，写下这一块要怎么改。每个圈选是一条独立的反馈。</div>}
          {marks.map((m, i) => (
            <div className="task-row" key={m.id}>
              <label htmlFor={`mk-${m.id}`}>圈选 {i + 1}</label>
              <input id={`mk-${m.id}`} type="text" value={m.prompt} placeholder="这一块要怎么改"
                onChange={(e) => setMarks((ms) => ms.map((x) => (x.id === m.id ? { ...x, prompt: e.target.value } : x)))} />
              <div className="task-row-actions">
                <button type="button" className="btn btn-sm btn-ghost" onClick={() => setMarks((ms) => ms.filter((x) => x.id !== m.id))}>删除</button>
              </div>
            </div>
          ))}
        </div>
        <div className="task-panel-foot">
          <button type="button" className="btn btn-teal" style={{ width: '100%' }} disabled={submitting || busy}
            onClick={() => void submit()}>作为反馈提交</button>
        </div>
      </div>
    </div>
  )
}
