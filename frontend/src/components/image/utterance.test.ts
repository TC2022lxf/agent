import { describe, expect, it } from 'vitest'
import { buildImageUtterance } from './utterance'

describe('buildImageUtterance', () => {
  it('sends the normalized region and the reasoning switch', () => {
    const region = { x: 0.25, y: 0.25, w: 0.5, h: 0.5 }
    expect(buildImageUtterance({
      text: '这里再亮一点', slot: 'main_image', versionId: 'v2', region, reasoning: true,
    })).toEqual({
      text: '这里再亮一点',
      target_slot: 'main_image',
      target_version_id: 'v2',
      target_region: region,
      reasoning: true,
    })
  })

  it('omits the region when the whole image is redone', () => {
    const body = buildImageUtterance({ text: '重做', slot: 'image', versionId: 'v1' })
    expect(body.target_region).toBeUndefined()
    expect(body.reasoning).toBe(false)
  })
})
