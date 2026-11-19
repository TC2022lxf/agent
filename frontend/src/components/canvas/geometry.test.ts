import { describe, expect, it } from 'vitest'
import type { CanvasTheme } from '../../api/types'
import {
  colorOf,
  deltaToFraction,
  edgeLabelAt,
  edgePath,
  fontOf,
  fontSizePx,
  movedRect,
  rectStyle,
  referenceSegments,
  resizedRect,
} from './geometry'

const BOX = { frameWidth: 1464, frameHeight: 600, scale: 0.5 }
const R = { x: 0.1, y: 0.2, w: 0.3, h: 0.4 }
const THEME: CanvasTheme = {
  colors: { bg: '#FFFFFF', fg: '#111111', accent: '#10A37F' },
  fonts: { display: 'Georgia, serif', body: 'Inter, sans-serif' },
  radius: 12,
}
const SCREEN_A = { pos: { x: 0, y: 0 }, frame: { width: 1464, height: 600 } }
const SCREEN_B = { pos: { x: 1560, y: 0 }, frame: { width: 1464, height: 600 } }

describe('canvas geometry', () => {
  it('converts a pointer drag into fractions of one screen', () => {
    // 73.2 px is 10% of a 1464 px screen rendered at 50% (732 px on screen).
    expect(deltaToFraction(73.2, 30, BOX)).toEqual({ dx: 0.1, dy: 0.1 })
  })

  it('keeps a dragged module inside its own screen', () => {
    expect(movedRect(R, 5, -5)).toEqual({ x: 0.7, y: 0, w: 0.3, h: 0.4 })
    expect(movedRect(R, -5, 5)).toEqual({ x: 0, y: 0.6, w: 0.3, h: 0.4 })
  })

  it('resizes from a corner without leaving the screen', () => {
    expect(resizedRect(R, 0.1, 0.1, 'se')).toEqual({ x: 0.1, y: 0.2, w: 0.4, h: 0.5 })
    const nw = resizedRect(R, 0.1, 0.1, 'nw')
    expect(nw.x).toBeCloseTo(0.2)
    expect(nw.w).toBeCloseTo(0.2)
    expect(nw.y).toBeCloseTo(0.3)
    expect(nw.h).toBeCloseTo(0.3)
  })

  it('never shrinks a module below the grab size', () => {
    const tiny = resizedRect(R, -1, -1, 'se')
    expect(tiny.w).toBeGreaterThanOrEqual(0.04)
    expect(tiny.h).toBeGreaterThanOrEqual(0.04)
  })

  it('positions with percentages so a resize of the screen keeps the layout', () => {
    expect(rectStyle(R)).toEqual({ left: '10%', top: '20%', width: '30%', height: '40%' })
  })

  it('scales the module font with the screen', () => {
    expect(fontSizePx(44, BOX)).toBe(22)
    expect(fontSizePx(undefined, BOX)).toBe(12)
    expect(fontSizePx(44, { ...BOX, scale: 1 })).toBe(44)
    expect(fontSizePx(44, { ...BOX, scale: 0 })).toBe(8)
  })

  it('resolves colour and font tokens, falling back to fg / body', () => {
    expect(colorOf(THEME, 'accent')).toBe('#10A37F')
    expect(colorOf(THEME, 'nope')).toBe('#111111')
    expect(colorOf(null, 'accent')).toBe('#0D0D0D')
    expect(fontOf(THEME, 'display')).toBe('Georgia, serif')
    expect(fontOf(THEME, undefined)).toBe('Inter, sans-serif')
  })

  it('draws an edge between two screens, trimmed off the cards', () => {
    const path = edgePath(SCREEN_A, SCREEN_B)
    expect(path.startsWith('M ')).toBe(true)
    const [, x1] = path.match(/M (\d+) /) ?? []
    // Starts inside the right half of A, not at its centre.
    expect(Number(x1)).toBeGreaterThan(SCREEN_A.frame.width / 2)
    const label = edgeLabelAt(SCREEN_A, SCREEN_B)
    expect(label.x).toBe(Math.round((SCREEN_A.frame.width / 2 + 1560 + SCREEN_B.frame.width / 2) / 2))
    expect(label.y).toBe(300)
  })

  it('draws a reference line from one picture to the picture it was made from', () => {
    const screen = {
      id: 's1', name: 's1', pos: { x: 40, y: 20 },
      frame: { width: 1000, height: 500 },
      modules: [
        {
          id: 'src', kind: 'image' as const, name: '源', rect: { x: 0, y: 0, w: 0.4, h: 0.5 },
          style: { fit: 'cover' as const, background: 'white' as const },
        },
        {
          id: 'made', kind: 'image' as const, name: '成', rect: { x: 0.5, y: 0, w: 0.4, h: 0.5 },
          style: { fit: 'cover' as const, background: 'white' as const }, ref: 'src',
        },
      ],
    }
    const [line] = referenceSegments([screen], { x: 40, y: 20 })
    expect(line).toMatchObject({ from: 'src', to: 'made', x1: 200, y1: 125, x2: 700, y2: 125 })
    // A ref that names nothing on the board is not a line.
    expect(referenceSegments([{
      ...screen,
      modules: [{ ...screen.modules[1]!, ref: 'gone' }],
    }], { x: 0, y: 0 })).toEqual([])
  })
})
