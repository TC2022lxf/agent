import type { CanvasModule, CanvasOp, CanvasScreen, CanvasTheme, NormRect } from '../../api/types'

/**
 * Screen pixels <-> board world. A module's rect is normalized (0..1) inside its own screen,
 * and a screen sits at world pixels. This module is pure: no DOM, no requests, no decisions
 * about what the server accepts.
 */
export interface ScreenBox {
  /** The screen's frame size in world px, e.g. 1464 x 600. */
  frameWidth: number
  frameHeight: number
  /** How many screen px are one world px at the current zoom. */
  scale: number
}

/** A pointer delta in CSS pixels as a fraction of one screen. */
export function deltaToFraction(
  dxPx: number, dyPx: number, box: ScreenBox,
): { dx: number; dy: number } {
  const w = box.frameWidth * box.scale
  const h = box.frameHeight * box.scale
  if (w <= 0 || h <= 0) return { dx: 0, dy: 0 }
  return { dx: round(dxPx / w), dy: round(dyPx / h) }
}

/** Where a module lands after a drag, kept inside its screen instead of drifting off it. */
export function movedRect(rect: NormRect, dx: number, dy: number): NormRect {
  const w = clamp(rect.w, 0.01, 1)
  const h = clamp(rect.h, 0.01, 1)
  return {
    x: round(clamp(rect.x + dx, 0, 1 - w)),
    y: round(clamp(rect.y + dy, 0, 1 - h)),
    w: round(w),
    h: round(h),
  }
}

/** A resize from a corner. `min` keeps a module grabbable. */
export function resizedRect(
  start: NormRect, dx: number, dy: number, corner: 'se' | 'sw' | 'ne' | 'nw', min = 0.04,
): NormRect {
  let { x, y, w, h } = start
  if (corner === 'se' || corner === 'ne') w = clamp(w + dx, min, 1 - x)
  else { const nw = clamp(w - dx, min, x + w); x = round(x + w - nw); w = nw }
  if (corner === 'se' || corner === 'sw') h = clamp(h + dy, min, 1 - y)
  else { const nh = clamp(h - dy, min, y + h); y = round(y + h - nh); h = nh }
  return { x: round(x), y: round(y), w: round(w), h: round(h) }
}

/** Percentage strings for CSS, so the same numbers position a module at any container size. */
export function rectStyle(rect: NormRect): { left: string; top: string; width: string; height: string } {
  return {
    left: `${round(rect.x * 100)}%`,
    top: `${round(rect.y * 100)}%`,
    width: `${round(rect.w * 100)}%`,
    height: `${round(rect.h * 100)}%`,
  }
}

/** Font size in screen px scaled to the rendered screen, so text scales with the canvas. */
export function fontSizePx(size: number | undefined, box: ScreenBox): number {
  const base = typeof size === 'number' && size > 0 ? size : 24
  return Math.max(8, Math.round(base * box.scale))
}

/** A colour token resolved against the theme. An unknown token falls back to `fg`. */
export function colorOf(theme: CanvasTheme | null, token: string | undefined): string {
  if (!theme) return '#0D0D0D'
  if (token && theme.colors[token]) return theme.colors[token]
  return theme.colors.fg ?? '#0D0D0D'
}

/** A font token resolved against the theme. An unknown token falls back to `body`. */
export function fontOf(theme: CanvasTheme | null, token: string | undefined): string {
  if (!theme) return 'system-ui, sans-serif'
  if (token && theme.fonts[token]) return theme.fonts[token]
  return theme.fonts.body ?? 'system-ui, sans-serif'
}

/**
 * Where the clickable-flow edges run between two screens: from the centre of one screen's
 * border to the centre of the other's, in world px. A pair of screens that overlaps yields a
 * short line instead of a bogus geometry.
 */
export function edgePath(
  a: Pick<CanvasScreen, 'pos' | 'frame'>,
  b: Pick<CanvasScreen, 'pos' | 'frame'>,
  gap = 24,
): string {
  const ac = centre(a)
  const bc = centre(b)
  const [from, to] = trim(ac, bc, a, b, gap)
  return `M ${from.x} ${from.y} L ${to.x} ${to.y}`
}

/** Centre of a module in world pixels. */
export function moduleCenter(
  screen: Pick<CanvasScreen, 'pos' | 'frame'>,
  rect: NormRect,
): { x: number; y: number } {
  return {
    x: screen.pos.x + (rect.x + rect.w / 2) * screen.frame.width,
    y: screen.pos.y + (rect.y + rect.h / 2) * screen.frame.height,
  }
}

export interface RefSegment {
  from: string
  to: string
  x1: number
  y1: number
  x2: number
  y2: number
  labelX: number
  labelY: number
}

/**
 * Dashed reference lines, in the same coordinates as the edge svg (relative to the board's
 * bounding box). A `ref` that does not name a picture on the board is skipped.
 */
export function referenceSegments(
  screens: CanvasScreen[],
  origin: { x: number; y: number },
): RefSegment[] {
  const byId = new Map<string, { screen: CanvasScreen; module: CanvasModule }>()
  for (const screen of screens) {
    for (const module of screen.modules) {
      if (module.kind === 'image') byId.set(module.id, { screen, module })
    }
  }
  const out: RefSegment[] = []
  for (const { screen, module } of byId.values()) {
    if (!module.ref || module.ref === module.id) continue
    const source = byId.get(module.ref)
    if (!source) continue
    const a = moduleCenter(source.screen, source.module.rect)
    const b = moduleCenter(screen, module.rect)
    out.push({
      from: source.module.id,
      to: module.id,
      x1: a.x - origin.x,
      y1: a.y - origin.y,
      x2: b.x - origin.x,
      y2: b.y - origin.y,
      labelX: (a.x + b.x) / 2 - origin.x,
      labelY: (a.y + b.y) / 2 - origin.y,
    })
  }
  return out
}

export function edgeLabelAt(
  a: Pick<CanvasScreen, 'pos' | 'frame'>,
  b: Pick<CanvasScreen, 'pos' | 'frame'>,
): { x: number; y: number } {
  const ac = centre(a)
  const bc = centre(b)
  return { x: Math.round((ac.x + bc.x) / 2), y: Math.round((ac.y + bc.y) / 2) }
}

function centre(s: Pick<CanvasScreen, 'pos' | 'frame'>): { x: number; y: number } {
  return { x: s.pos.x + s.frame.width / 2, y: s.pos.y + s.frame.height / 2 }
}

/** Stop each end at the screen border so the arrow does not run under the card. */
function trim(
  ac: { x: number; y: number },
  bc: { x: number; y: number },
  a: Pick<CanvasScreen, 'pos' | 'frame'>,
  b: Pick<CanvasScreen, 'pos' | 'frame'>,
  gap: number,
): [{ x: number; y: number }, { x: number; y: number }] {
  const dx = bc.x - ac.x
  const dy = bc.y - ac.y
  const len = Math.hypot(dx, dy)
  if (len < 1) return [ac, bc]
  return [
    { x: Math.round(ac.x + (dx / len) * (a.frame.width / 2 + gap)), y: ac.y },
    { x: Math.round(bc.x - (dx / len) * (b.frame.width / 2 + gap)), y: bc.y },
  ]
}

export function moveModuleOp(screen: string | undefined, id: string, dx: number, dy: number): CanvasOp {
  return { op: 'move_module', ...(screen ? { screen } : {}), id, dx: round(dx), dy: round(dy) }
}

export function resizeModuleOp(screen: string | undefined, id: string, rect: NormRect): CanvasOp {
  return { op: 'resize_module', ...(screen ? { screen } : {}), id, rect }
}

export function setTextOp(screen: string | undefined, id: string, text: string): CanvasOp {
  return { op: 'set_text', ...(screen ? { screen } : {}), id, text }
}

export function deleteModuleOp(screen: string | undefined, id: string): CanvasOp {
  return { op: 'delete_module', ...(screen ? { screen } : {}), id }
}

export function moveScreenOp(id: string, dx: number, dy: number): CanvasOp {
  return { op: 'move_screen', id, dx: Math.round(dx), dy: Math.round(dy) }
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(Math.max(v, lo), hi)
}

function round(v: number): number {
  return Math.round(v * 1e6) / 1e6
}
