import { useEffect, useRef, useState, type ReactNode } from 'react'
import type {
  CanvasEdge,
  CanvasModule,
  CanvasOp,
  CanvasScreen,
  CanvasView,
  NormRect,
} from '../../api/types'
import { useToast } from '../../state/toast'
import {
  colorOf,
  deleteModuleOp,
  deltaToFraction,
  edgeLabelAt,
  edgePath,
  fontOf,
  fontSizePx,
  movedRect,
  moveModuleOp,
  moveScreenOp,
  rectStyle,
  referenceSegments,
  resizeModuleOp,
  resizedRect,
  setTextOp,
  type ScreenBox,
} from './geometry'
import { useFitOnce, useViewport, worldTransform } from './useViewport'

/**
 * The canvas board (decisions/0025, 0029), modelled on an AI design canvas: several screens
 * side by side on one surface, each laying out modules, plus the clickable flow between them.
 *
 * One gesture becomes ONE `canvas-patches` call on release: the layout is a Version, not local
 * state, so it survives a reload and 「从这版继续」 can go back. This component never decides
 * whether a layout is legal, never generates pictures and never calls a model.
 */
export function CanvasWorkbench({
  canvas, readOnly, busy, onPatch, onSelectVersion, onAskAboutModule, onKeepVariant, topRight,
}: {
  canvas: CanvasView
  readOnly?: boolean
  busy?: boolean
  onPatch: (ops: CanvasOp[]) => Promise<unknown>
  onSelectVersion?: (versionId: string) => void
  onAskAboutModule?: (moduleId: string) => void
  onKeepVariant?: (screenId: string) => Promise<unknown> | void
  /** Page-level actions (thread toggle, back to task) that belong in the board's own bar. */
  topRight?: ReactNode
}) {
  const toast = useToast()
  const surface = useRef<HTMLDivElement>(null)
  const { viewport, zoomAt, fit, bind, panning } = useViewport()
  useFitOnce(canvas.bounds, canvas.version_id, fit, surface)

  const [selectedModule, setSelectedModule] = useState<string | null>(null)
  const [selectedScreen, setSelectedScreen] = useState<string | null>(null)
  const [draftRect, setDraftRect] = useState<Record<string, NormRect>>({})
  const [draftPos, setDraftPos] = useState<Record<string, { x: number; y: number }>>({})
  const [text, setText] = useState('')
  const [scale, setScale] = useState(viewport.scale)
  const [saving, setSaving] = useState(false)
  const drag = useRef<
    | { kind: 'module-move' | 'module-resize'; screen: string; id: string; x: number; y: number; start: NormRect; corner?: 'se' | 'nw'; box: ScreenBox }
    | { kind: 'screen-move'; id: string; x: number; y: number; start: { x: number; y: number } }
    | null
  >(null)

  useEffect(() => { setScale(viewport.scale) }, [viewport.scale])
  useEffect(() => {
    setSelectedModule(null)
    setSelectedScreen(null)
    setDraftRect({})
    setDraftPos({})
    setText('')
  }, [canvas.version_id])

  const boxFor = (s: CanvasScreen): ScreenBox => ({
    frameWidth: s.frame.width,
    frameHeight: s.frame.height,
    scale: viewport.scale,
  })
  const rectOf = (m: CanvasModule): NormRect => draftRect[m.id] ?? m.rect
  const posOf = (s: CanvasScreen) => draftPos[s.id] ?? s.pos

  const submit = async (ops: CanvasOp[]) => {
    if (ops.length === 0 || readOnly || busy) return
    setSaving(true)
    try {
      await onPatch(ops)
      setDraftRect({})
      setDraftPos({})
    } catch (e) {
      // The server refused: show the saved layout, not the half-dragged one.
      setDraftRect({})
      setDraftPos({})
      toast(e instanceof Error ? e.message : '这次改动没有保存')
    } finally {
      setSaving(false)
    }
  }

  const beginModuleDrag = (
    e: React.PointerEvent, s: CanvasScreen, m: CanvasModule,
    kind: 'module-move' | 'module-resize', corner?: 'se' | 'nw',
  ) => {
    if (readOnly || busy) return
    e.stopPropagation()
    e.preventDefault()
    setSelectedModule(m.id)
    setSelectedScreen(s.id)
    if (m.kind === 'text') setText(m.text ?? '')
    drag.current = {
      kind, screen: s.id, id: m.id, x: e.clientX, y: e.clientY,
      start: rectOf(m), corner, box: boxFor(s),
    }
    ;(e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId)
  }

  const beginScreenDrag = (e: React.PointerEvent, s: CanvasScreen) => {
    if (readOnly || busy) return
    e.stopPropagation()
    e.preventDefault()
    setSelectedScreen(s.id)
    setSelectedModule(null)
    drag.current = { kind: 'screen-move', id: s.id, x: e.clientX, y: e.clientY, start: posOf(s) }
    ;(e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId)
  }

  const onMove = (e: React.PointerEvent) => {
    const d = drag.current
    if (!d) return
    if (d.kind === 'screen-move') {
      setDraftPos((p) => ({
        ...p,
        [d.id]: {
          x: d.start.x + (e.clientX - d.x) / viewport.scale,
          y: d.start.y + (e.clientY - d.y) / viewport.scale,
        },
      }))
      return
    }
    const { dx, dy } = deltaToFraction(e.clientX - d.x, e.clientY - d.y, d.box)
    const next = d.kind === 'module-move'
      ? movedRect(d.start, dx, dy)
      : resizedRect(d.start, dx, dy, d.corner ?? 'se')
    setDraftRect((r) => ({ ...r, [d.id]: next }))
  }

  const endDrag = () => {
    const d = drag.current
    drag.current = null
    if (!d) return
    if (d.kind === 'screen-move') {
      const next = draftPos[d.id]
      if (!next) return
      const dx = next.x - d.start.x
      const dy = next.y - d.start.y
      if (Math.abs(dx) < 2 && Math.abs(dy) < 2) { setDraftPos({}); return }
      void submit([moveScreenOp(d.id, dx, dy)])
      return
    }
    const next = draftRect[d.id]
    if (!next) return
    const moved = Math.abs(next.x - d.start.x) > 0.002 || Math.abs(next.y - d.start.y) > 0.002
    const resized = Math.abs(next.w - d.start.w) > 0.002 || Math.abs(next.h - d.start.h) > 0.002
    if (!moved && !resized) { setDraftRect({}); return }
    void submit([
      d.kind === 'module-move'
        ? moveModuleOp(d.screen, d.id, next.x - d.start.x, next.y - d.start.y)
        : resizeModuleOp(d.screen, d.id, next),
    ])
  }

  const module = findModule(canvas.screens, selectedModule)
  const screen = canvas.screens.find((s) => s.id === selectedScreen) ?? null
  const bounds = canvas.bounds ?? { x: 0, y: 0, width: 1464, height: 600 }
  const theme = canvas.theme
  const screenById = new Map(canvas.screens.map((s) => [s.id, s]))
  // Draft positions, so a dashed reference line follows a module while it is being dragged.
  const laidOut = canvas.screens.map((s) => ({
    ...s,
    pos: posOf(s),
    modules: s.modules.map((m) => ({ ...m, rect: rectOf(m) })),
  }))
  const refs = referenceSegments(laidOut, bounds)
  const refModule = module?.ref ? findModule(canvas.screens, module.ref) : null

  return (
    <div className="canvas-wb" onPointerMove={onMove} onPointerUp={endDrag} onPointerLeave={endDrag}>
      <div className="canvas-wb-bar">
        <span className="canvas-wb-title">
          {canvas.seq ? `画布 v${canvas.seq}` : '画布'}
          <span className="canvas-wb-tag">{canvas.screens.length} 屏</span>
          {readOnly && <span className="canvas-wb-tag">只读</span>}
          {saving && <span className="canvas-wb-tag">保存中…</span>}
        </span>
        <div className="canvas-wb-versions" role="tablist" aria-label="画布版本">
          {canvas.versions.slice(0, 8).map((v) => (
            <button key={v.id} type="button" role="tab" aria-selected={v.is_current}
              className={`canvas-wb-version${v.is_current ? ' is-current' : ''}`}
              onClick={() => onSelectVersion?.(v.id)}>
              v{v.seq}{v.status === 'rejected' ? ' ✕' : ''}
            </button>
          ))}
        </div>
        {topRight && <div className="canvas-wb-actions">{topRight}</div>}
      </div>

      <div className="canvas-wb-body">
        <div ref={surface} className={`canvas-wb-surface${panning ? ' is-panning' : ''}`}
          data-testid="canvas-surface" {...bind}>
          <div className="canvas-wb-world" style={{ transform: worldTransform(viewport) }}>
            <div className="canvas-wb-bounds" style={{
              left: bounds.x, top: bounds.y, width: bounds.width, height: bounds.height,
            }} />
            <svg className="canvas-wb-edges" style={{
              left: bounds.x, top: bounds.y, width: bounds.width, height: bounds.height,
            }} aria-label="屏之间可点击的跳转">
              {canvas.edges.map((e) => {
                const a = screenById.get(e.from)
                const b = screenById.get(e.to)
                if (!a || !b) return null
                const label = edgeLabelAt(a, b)
                return (
                  <g key={`${e.from}->${e.to}`}>
                    <path d={edgePath(a, b)} className="canvas-edge" />
                    <circle cx={label.x} cy={label.y} r={5} className="canvas-edge-dot" />
                    {e.label && (
                      <text x={label.x} y={label.y} className="canvas-edge-label"
                        textAnchor="start" dx={10} dy={4}>{e.label}</text>
                    )}
                  </g>
                )
              })}
            </svg>

            {canvas.screens.map((s) => {
              const pos = posOf(s)
              const isSelScreen = selectedScreen === s.id
              return (
                <article key={s.id}
                  className={`canvas-screen${isSelScreen ? ' is-selected' : ''}`}
                  data-testid={`canvas-screen-${s.id}`}
                  data-canvas-interactive=""
                  style={{
                    left: pos.x, top: pos.y, width: s.frame.width, height: s.frame.height,
                    borderRadius: theme?.radius ?? 12,
                    background: colorOf(theme, 'bg'),
                  }}
                  onPointerDown={(e) => { setSelectedScreen(s.id); e.stopPropagation() }}>
                  <header className="canvas-screen-head" onPointerDown={(e) => beginScreenDrag(e, s)}>
                    <span className="canvas-screen-name">{s.name || s.id}</span>
                    {s.variant_label && <span className="canvas-screen-variant">{s.variant_label}</span>}
                    {s.variant_of && onKeepVariant && (
                      <button type="button" className="canvas-screen-keep"
                        onPointerDown={(e) => e.stopPropagation()}
                        onClick={() => void onKeepVariant(s.id)}>保留这个</button>
                    )}
                  </header>
                  <div className="canvas-screen-body">
                    {s.modules.length === 0 && <p className="canvas-wb-empty">这一屏还没有模块。</p>}
                    {s.modules.map((m) => {
                      const rect = rectOf(m)
                      const isSel = selectedModule === m.id
                      return (
                        <div key={m.id}
                          className={`canvas-module is-${m.kind}${isSel ? ' is-selected' : ''}${readOnly ? ' is-readonly' : ''}`}
                          style={rectStyle(rect)}
                          data-testid={`canvas-module-${m.id}`}
                          data-canvas-interactive=""
                          onPointerDown={(e) => beginModuleDrag(e, s, m, 'module-move')}>
                          {m.kind === 'text' ? (
                            <div className="canvas-text"
                              style={{
                                fontSize: fontSizePx(m.style.size, boxFor(s)),
                                fontWeight: m.style.weight ?? 400,
                                textAlign: m.style.align ?? 'left',
                                color: colorOf(theme, m.style.color),
                                fontFamily: fontOf(theme, m.style.font),
                              }}>{m.text}</div>
                          ) : m.url ? (
                            <>
                              <img className="canvas-img" src={m.url} alt={m.name || '图片'} draggable={false}
                                style={{ objectFit: m.style.fit === 'cover' ? 'cover' : 'contain' }} />
                              {m.prompt && (
                                <span className="canvas-img-meta" title={m.prompt}>
                                  <span className="canvas-img-meta-k">提示词</span>
                                  {m.prompt}
                                </span>
                              )}
                            </>
                          ) : (
                            // A picture that has not been drawn yet is a placeholder card, not an
                            // empty box: it shows the prompt waiting for it, and it is what the
                            // first generate call will fill (decisions/0031).
                            <div className={`canvas-img is-pending${busy ? ' is-working' : ''}`}>
                              <span className="canvas-img-badge">{busy ? '生成中' : '待生成'}</span>
                              {m.prompt && <span className="canvas-img-prompt">{m.prompt}</span>}
                            </div>
                          )}
                          {isSel && !readOnly && (
                            <>
                              <span className="canvas-handle se"
                                onPointerDown={(e) => beginModuleDrag(e, s, m, 'module-resize', 'se')} />
                              <span className="canvas-handle nw"
                                onPointerDown={(e) => beginModuleDrag(e, s, m, 'module-resize', 'nw')} />
                            </>
                          )}
                          {m.newer_version && !readOnly && (
                            <span className="canvas-module-flag" title="这个模块有更新的图，但版面还指向旧的" />
                          )}
                        </div>
                      )
                    })}
                  </div>
                </article>
              )
            })}
            <svg className="canvas-wb-refs" style={{
              left: bounds.x, top: bounds.y, width: bounds.width, height: bounds.height,
            }} aria-label="图片与参考图的关系">
              {refs.map((r) => (
                <g key={`${r.from}->${r.to}`} data-testid={`canvas-ref-${r.from}-${r.to}`}>
                  <line x1={r.x1} y1={r.y1} x2={r.x2} y2={r.y2} className="canvas-ref-line" />
                  <text x={r.labelX} y={r.labelY} className="canvas-ref-label" textAnchor="middle" dy={-8}>
                    参考
                  </text>
                </g>
              ))}
            </svg>
          </div>

          {canvas.screens.length === 0 && (
            <p className="canvas-wb-hollow">空白画板。在底部说一句要画的内容，图片会先以占位卡片出现。</p>
          )}
          <div className="canvas-wb-zoom">
            <button type="button" aria-label="缩小" onClick={() => zoomAt(0.9)}>−</button>
            <span>{Math.round(scale * 100)}%</span>
            <button type="button" aria-label="放大" onClick={() => zoomAt(1.1)}>+</button>
            <button type="button" aria-label="适应窗口"
              onClick={() => fit(bounds, {
                width: surface.current?.clientWidth ?? 800,
                height: surface.current?.clientHeight ?? 600,
              })}>适应</button>
          </div>
          {canvas.notes.length > 0 && (
            <ul className="canvas-wb-notes">{canvas.notes.map((n) => <li key={n}>{n}</li>)}</ul>
          )}
        </div>

        <aside className="canvas-wb-inspector" aria-label="属性"
          data-open={Boolean(module || screen)}>
          {!module && !screen && <p className="canvas-wb-hint">点一屏拖动它的位置，点一个模块看它的样子。也可以直接拖模块。</p>}
          {screen && !module && <ScreenPane screen={screen} screens={canvas.screens} busy={busy}
            readOnly={readOnly} onPatch={submit} currentId={canvas.version_id} />}
          {module && screen && (
            <>
              <h3>{module.name || module.id}</h3>
              <p className="canvas-wb-meta">
                {module.kind === 'text' ? '文字模块' : `图片模块 · ${module.slot}`} · {screen.name || screen.id}
              </p>
              {module.kind === 'text' ? (
                <>
                  <label className="canvas-wb-field">
                    <span>文案</span>
                    <textarea rows={3} value={text} disabled={readOnly || busy}
                      onChange={(e) => setText(e.target.value)}
                      onBlur={() => {
                        const t = text.trim()
                        if (t && t !== (module.text ?? '')) void submit([setTextOp(screen.id, module.id, t)])
                      }} />
                  </label>
                  <label className="canvas-wb-field">
                    <span>字号</span>
                    <input type="number" min={8} max={200} value={module.style.size ?? 24}
                      disabled={readOnly || busy}
                      onChange={(e) => {
                        const size = Number(e.target.value)
                        if (Number.isFinite(size) && size >= 8 && size <= 200) {
                          void submit([{ op: 'set_style', screen: screen.id, id: module.id, style: { size } }])
                        }
                      }} />
                  </label>
                  <label className="canvas-wb-field">
                    <span>颜色令牌</span>
                    <select value={module.style.color ?? 'fg'} disabled={readOnly || busy}
                      onChange={(e) => void submit([{
                        op: 'set_style', screen: screen.id, id: module.id,
                        style: { color: e.target.value },
                      }])}>
                      {Object.keys(theme?.colors ?? {}).map((k) => <option key={k} value={k}>{k}</option>)}
                    </select>
                  </label>
                  <label className="canvas-wb-field">
                    <span>字体令牌</span>
                    <select value={module.style.font ?? 'body'} disabled={readOnly || busy}
                      onChange={(e) => void submit([{
                        op: 'set_style', screen: screen.id, id: module.id,
                        style: { font: e.target.value },
                      }])}>
                      {Object.keys(theme?.fonts ?? {}).map((k) => <option key={k} value={k}>{k}</option>)}
                    </select>
                  </label>
                </>
              ) : (
                <>
                  {module.ref && (
                    <p className="canvas-wb-note">参考：{refModule?.name || module.ref}</p>
                  )}
                  <label className="canvas-wb-field">
                    <span>提示词</span>
                    <textarea rows={3} defaultValue={module.prompt ?? ''} disabled={readOnly || busy}
                      placeholder="这张图是怎么来的；改了它就是新的版本"
                      onBlur={(e) => {
                        const p = e.target.value.trim()
                        if (p !== (module.prompt ?? '')) {
                          void submit([{
                            op: 'set_prompt', screen: screen.id, id: module.id, prompt: p || null,
                          }])
                        }
                      }} />
                  </label>
                  {module.newer_version && (
                    <p className="canvas-wb-note">
                      这个模块有更新的图（v{module.newer_version.seq}）。在对话里说「用这一版」，版面才会指向它。
                    </p>
                  )}
                  {onAskAboutModule && (
                    <button type="button" className="btn btn-secondary btn-sm"
                      onClick={() => onAskAboutModule(module.id)}>在对话里说这张图</button>
                  )}
                </>
              )}
              {!readOnly && (
                <button type="button" className="btn btn-ghost btn-sm"
                  disabled={busy || screen.modules.length <= 1}
                  onClick={() => void submit([deleteModuleOp(screen.id, module.id)])}>删除这个模块</button>
              )}
            </>
          )}
        </aside>
      </div>
    </div>
  )
}

/** Screen properties: name, height, the screens it links to, and adding a neighbour. */
function ScreenPane({
  screen, screens, busy, readOnly, onPatch, currentId,
}: {
  screen: CanvasScreen
  screens: CanvasScreen[]
  busy?: boolean
  readOnly?: boolean
  onPatch: (ops: CanvasOp[]) => Promise<unknown>
  currentId: string | null
}) {
  const [name, setName] = useState(screen.name)
  useEffect(() => { setName(screen.name) }, [screen.id, screen.name])
  return (
    <>
      <h3>{screen.name || screen.id}</h3>
      <p className="canvas-wb-meta">{screen.frame.width} × {screen.frame.height}</p>
      <label className="canvas-wb-field">
        <span>这一屏叫什么</span>
        <input value={name} disabled={readOnly || busy}
          onChange={(e) => setName(e.target.value)}
          onBlur={() => {
            const v = name.trim()
            if (v && v !== screen.name) void onPatch([{ op: 'rename_screen', id: screen.id, name: v }])
          }} />
      </label>
      <label className="canvas-wb-field">
        <span>高度</span>
        <input type="number" min={120} max={4000} defaultValue={screen.frame.height}
          disabled={readOnly || busy}
          onBlur={(e) => {
            const h = Number(e.target.value)
            if (Number.isFinite(h) && h >= 120 && h !== screen.frame.height) {
              void onPatch([{ op: 'resize_screen', id: screen.id, height: h }])
            }
          }} />
      </label>
      {!readOnly && (
        <>
          <button type="button" className="btn btn-secondary btn-sm" disabled={busy}
            onClick={() => void onPatch([{
              op: 'add_screen',
              screen: { name: `新的一屏`, frame: { ...screen.frame }, modules: [{
                id: `m-${Date.now()}`, kind: 'text', name: '标题',
                rect: { x: 0.08, y: 0.2, w: 0.5, h: 0.2 },
                style: { size: 40, weight: 600, align: 'left', color: 'fg', font: 'display' },
                text: '新的标题',
              }] },
            }])}>加一屏</button>
          <div className="canvas-wb-links">
            <span>跳到哪一屏</span>
            <select defaultValue="" disabled={busy}
              onChange={(e) => {
                if (!e.target.value) return
                void onPatch([{ op: 'link_screens', from: screen.id, to: e.target.value }])
                e.target.value = ''
              }}>
              <option value="">选择…</option>
              {screens.filter((x) => x.id !== screen.id).map((x) => (
                <option key={x.id} value={x.id}>{x.name || x.id}</option>
              ))}
            </select>
          </div>
        </>
      )}
      {currentId && (
        <p className="canvas-wb-hint">这一屏和画布一起保存在当前版本里。</p>
      )}
    </>
  )
}

function findModule(screens: CanvasScreen[], id: string | null): CanvasModule | null {
  if (!id) return null
  for (const s of screens) {
    const m = s.modules.find((x) => x.id === id)
    if (m) return m
  }
  return null
}

export type { CanvasEdge }
