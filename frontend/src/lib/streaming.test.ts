import { describe, expect, it } from 'vitest'
import { streamingOf } from './streaming'

const line = (type: string, data: unknown = {}) => ({ type, data })

describe('streamingOf', () => {
  it('is idle before anything arrives', () => {
    expect(streamingOf([])).toEqual({ text: '', active: false })
  })

  it('shows the reply while it is being written', () => {
    const got = streamingOf([line('step', { stage: 'think' }), line('answer_delta', { text: '正在' })])
    expect(got).toEqual({ text: '正在', active: true })
  })

  it('takes the newest delta whole, never concatenated', () => {
    const got = streamingOf([
      line('answer_delta', { text: '正在' }),
      line('answer_delta', { text: '正在调整背景' }),
    ])
    expect(got.text).toBe('正在调整背景')
  })

  it('is idle once the final answer is recorded', () => {
    const got = streamingOf([
      line('answer_delta', { text: '正在调整' }),
      line('answer', { text: '已调整背景' }),
    ])
    expect(got).toEqual({ text: '', active: false })
  })

  it('clears the live text when a tool starts running', () => {
    // The reply ended and the Run moved on to doing the work: a half sentence left on screen
    // would look like the model stopped mid-thought.
    const got = streamingOf([
      line('answer_delta', { text: '这就去改' }),
      line('step', { stage: 'running', detail: 'generate_product_image:image' }),
    ])
    expect(got).toEqual({ text: '', active: false })
  })

  it('ignores a malformed delta instead of rendering undefined', () => {
    expect(streamingOf([line('answer_delta', { text: 42 })])).toEqual({ text: '', active: false })
  })
})
