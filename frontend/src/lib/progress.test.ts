import { describe, expect, it } from 'vitest'
import { progressOf } from './progress'

const ev = (type: string, data: unknown = {}) => ({ type, data })

describe('progressOf', () => {
  it('says it is analysing intent, not just "处理中"', () => {
    expect(progressOf([ev('step', { stage: 'interpret', detail: 'interpret' })]).text)
      .toBe('正在分析意图')
  })

  it('names the long tool, because a picture takes a minute and a half', () => {
    expect(progressOf([ev('step', { stage: 'running', detail: 'generate_product_image:image' })]).text)
      .toBe('正在生成图片')
    expect(progressOf([ev('step', { stage: 'running', detail: 'edit_product_image:main_image' })]).text)
      .toBe('正在修改图片')
    expect(progressOf([ev('step', { stage: 'running', detail: 'web_search:' })]).text)
      .toBe('正在搜索网页')
  })

  it('falls back to a generic tool line for a tool it does not know', () => {
    expect(progressOf([ev('step', { stage: 'running', detail: 'some_new_tool:image' })]).text)
      .toBe('正在调用工具')
  })

  it('reports the newest event, not the first', () => {
    const events = [
      ev('step', { stage: 'context', detail: 'load_context' }),
      ev('step', { stage: 'interpret', detail: 'interpret' }),
      ev('step', { stage: 'running', detail: 'generate_product_image:image' }),
    ]
    expect(progressOf(events).text).toBe('正在生成图片')
  })

  it('understands the named events that arrive before any step', () => {
    expect(progressOf([ev('run_queued')]).text).toBe('已排队')
    expect(progressOf([ev('context_loaded')]).text).toBe('已读取偏好与约束')
    expect(progressOf([ev('feedback_interpreted')]).text).toBe('已理解你的意见')
  })

  it('has something to say before any event arrives', () => {
    expect(progressOf([]).text).toBe('正在处理')
  })

  it('ignores an unknown stage rather than showing an empty line', () => {
    expect(progressOf([ev('step', { stage: 'mystery' })]).text).toBe('正在处理')
  })

  it('survives a malformed event', () => {
    expect(progressOf([ev('step', {}), ev('nonsense', null)]).text).toBe('正在处理')
  })
})
