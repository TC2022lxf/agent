import { describe, expect, it } from 'vitest'
import { normalizeRect, rectToStyle } from './useMarkTool'

const box = { width: 400, height: 200 }

describe('normalizeRect', () => {
  it('normalises to 0..1 of the image box', () => {
    expect(normalizeRect({ x: 100, y: 50 }, { x: 300, y: 150 }, box)).toEqual({ x: 0.25, y: 0.25, w: 0.5, h: 0.5 })
  })
  it('is direction independent (drag from bottom-right to top-left)', () => {
    expect(normalizeRect({ x: 300, y: 150 }, { x: 100, y: 50 }, box)).toEqual({ x: 0.25, y: 0.25, w: 0.5, h: 0.5 })
  })
  it('clamps to the image', () => {
    const r = normalizeRect({ x: -50, y: -10 }, { x: 999, y: 999 }, box)
    expect(r).toEqual({ x: 0, y: 0, w: 1, h: 1 })
  })
  it('drops stray clicks', () => {
    expect(normalizeRect({ x: 10, y: 10 }, { x: 11, y: 11 }, box)).toBeNull()
  })
  it('returns null for an empty box', () => {
    expect(normalizeRect({ x: 0, y: 0 }, { x: 5, y: 5 }, { width: 0, height: 0 })).toBeNull()
  })
  it('maps back to css percentages', () => {
    expect(rectToStyle({ x: 0.25, y: 0.5, w: 0.5, h: 0.25 })).toEqual({
      left: '25%', top: '50%', width: '50%', height: '25%',
    })
  })
})
