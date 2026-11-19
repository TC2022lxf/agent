import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Pan and zoom for a big surface. The state is world-space: `pan` is where world (0,0) sits in
 * the viewport, `scale` is screen px per world px. Everything the board renders uses these two
 * numbers, so a screen's own geometry never depends on the viewport.
 */
export interface Viewport {
  pan: { x: number; y: number }
  scale: number
}

export interface Box {
  x: number
  y: number
  width: number
  height: number
}

const MIN_SCALE = 0.05
const MAX_SCALE = 2

/** Frame `box` inside `view` with `pad` px of margin. Pure, so the maths is testable. */
export function fitted(box: Box, view: { width: number; height: number }, pad = 40): Viewport {
  const availW = Math.max(1, view.width - pad * 2)
  const availH = Math.max(1, view.height - pad * 2)
  const raw = Math.min(availW / Math.max(1, box.width), availH / Math.max(1, box.height))
  const scale = clamp(raw, MIN_SCALE, MAX_SCALE)
  return {
    scale,
    pan: {
      x: pad - box.x * scale + (availW - box.width * scale) / 2,
      y: pad - box.y * scale + (availH - box.height * scale) / 2,
    },
  }
}

export function useViewport(initial: Viewport = { pan: { x: 24, y: 24 }, scale: 0.42 }) {
  const [viewport, setViewport] = useState<Viewport>(initial)
  const [panning, setPanning] = useState(false)
  const dragging = useRef<{ x: number; y: number; px: number; py: number } | null>(null)

  const zoomAt = useCallback((factor: number, at?: { x: number; y: number }) => {
    setViewport((v) => {
      const scale = clamp(v.scale * factor, MIN_SCALE, MAX_SCALE)
      if (!at) return { ...v, scale }
      // Keep the point under the cursor fixed while zooming.
      const wx = (at.x - v.pan.x) / v.scale
      const wy = (at.y - v.pan.y) / v.scale
      return { scale, pan: { x: at.x - wx * scale, y: at.y - wy * scale } }
    })
  }, [])

  const fit = useCallback((box: Box, view: { width: number; height: number }) => {
    setViewport(fitted(box, view))
  }, [])

  const bind = {
    onPointerDown: (e: React.PointerEvent<HTMLElement>) => {
      if (e.button !== 0) return
      const target = e.target as HTMLElement
      // A module or a screen card handles its own pointer: only the empty surface pans.
      if (target.closest('[data-canvas-interactive]')) return
      dragging.current = { x: e.clientX, y: e.clientY, px: viewport.pan.x, py: viewport.pan.y }
      setPanning(true)
      e.currentTarget.setPointerCapture?.(e.pointerId)
    },
    onPointerMove: (e: React.PointerEvent<HTMLElement>) => {
      const d = dragging.current
      if (!d) return
      setViewport((v) => ({ ...v, pan: { x: d.px + e.clientX - d.x, y: d.py + e.clientY - d.y } }))
    },
    onPointerUp: () => { dragging.current = null; setPanning(false) },
    onPointerLeave: () => { dragging.current = null; setPanning(false) },
    onWheel: (e: React.WheelEvent<HTMLElement>) => {
      if (!(e.ctrlKey || e.metaKey)) return
      const rect = e.currentTarget.getBoundingClientRect()
      zoomAt(e.deltaY < 0 ? 1.08 : 0.93, { x: e.clientX - rect.left, y: e.clientY - rect.top })
    },
  }

  return { viewport, setViewport, zoomAt, fit, bind, panning }
}

/** The world -> CSS transform for the board surface. */
export function worldTransform(v: Viewport): string {
  return `translate(${v.pan.x}px, ${v.pan.y}px) scale(${v.scale})`
}

/**
 * Frame the board the first time a given canvas Version is shown. Later zooms belong to the
 * user: refitting on every change would fight their hand.
 */
export function useFitOnce(
  bounds: Box | null,
  versionId: string | null,
  fit: (box: Box, view: { width: number; height: number }) => void,
  viewportEl: React.RefObject<HTMLElement | null>,
) {
  const framed = useRef<string | null>(null)
  useEffect(() => {
    if (!bounds || !versionId) return
    if (framed.current === versionId) return
    const el = viewportEl.current
    if (!el) return
    const r = el.getBoundingClientRect()
    if (r.width < 80 || r.height < 80) return
    fit(bounds, { width: r.width, height: r.height })
    framed.current = versionId
  }, [bounds, fit, versionId, viewportEl])
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(Math.max(v, lo), hi)
}
