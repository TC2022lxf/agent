import { useCallback, useRef, useState } from 'react'
import type { NormRect } from '../../api/types'

export type Point = { x: number; y: number } // pixels, relative to the image box
export type Box = { width: number; height: number }

const MIN_SIDE = 0.02 // smaller than 2% of the image is treated as a stray click

const clamp01 = (v: number) => Math.min(1, Math.max(0, v))

/** Pure: two pixel points inside a box -> region normalised to 0..1 of the image. */
export function normalizeRect(a: Point, b: Point, box: Box): NormRect | null {
  if (box.width <= 0 || box.height <= 0) return null
  const x0 = clamp01(Math.min(a.x, b.x) / box.width)
  const y0 = clamp01(Math.min(a.y, b.y) / box.height)
  const x1 = clamp01(Math.max(a.x, b.x) / box.width)
  const y1 = clamp01(Math.max(a.y, b.y) / box.height)
  const w = x1 - x0
  const h = y1 - y0
  if (w < MIN_SIDE || h < MIN_SIDE) return null
  return { x: x0, y: y0, w, h }
}

/** Pure: region -> CSS percentages for overlay boxes. */
export function rectToStyle(r: NormRect): { left: string; top: string; width: string; height: string } {
  return { left: `${r.x * 100}%`, top: `${r.y * 100}%`, width: `${r.w * 100}%`, height: `${r.h * 100}%` }
}

/** Drag-to-circle state. The element the handlers are bound to defines the image box. */
export function useMarkTool(enabled: boolean, onRegion: (r: NormRect) => void) {
  const start = useRef<Point | null>(null)
  const [draft, setDraft] = useState<NormRect | null>(null)

  const local = (e: React.PointerEvent<HTMLElement>): { p: Point; box: Box } => {
    const r = e.currentTarget.getBoundingClientRect()
    return { p: { x: e.clientX - r.left, y: e.clientY - r.top }, box: { width: r.width, height: r.height } }
  }

  const onPointerDown = useCallback(
    (e: React.PointerEvent<HTMLElement>) => {
      if (!enabled) return
      start.current = local(e).p
      e.currentTarget.setPointerCapture?.(e.pointerId)
    },
    [enabled],
  )
  const onPointerMove = useCallback(
    (e: React.PointerEvent<HTMLElement>) => {
      if (!enabled || !start.current) return
      const { p, box } = local(e)
      setDraft(normalizeRect(start.current, p, box))
    },
    [enabled],
  )
  const onPointerUp = useCallback(
    (e: React.PointerEvent<HTMLElement>) => {
      if (!enabled || !start.current) return
      const { p, box } = local(e)
      const r = normalizeRect(start.current, p, box)
      start.current = null
      setDraft(null)
      if (r) onRegion(r)
    },
    [enabled, onRegion],
  )
  return { draft, bind: { onPointerDown, onPointerMove, onPointerUp } }
}
