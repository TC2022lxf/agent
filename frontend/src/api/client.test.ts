import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, createApiClient } from './client'

afterEach(() => vi.unstubAllGlobals())

function stubFetch(status: number, body: unknown) {
  const f = vi.fn(async (..._args: unknown[]) => new Response(JSON.stringify(body), { status }))
  vi.stubGlobal('fetch', f)
  return f
}

describe('ApiClient', () => {
  it('sends a fresh Idempotency-Key with every utterance', async () => {
    const f = stubFetch(202, { id: 'run1' })
    const c = createApiClient()
    await c.utter('t1', { text: 'a' })
    await c.utter('t1', { text: 'a' })
    const keys = f.mock.calls.map((call) => (call[1] as RequestInit).headers as Record<string, string>).map((h) => h['Idempotency-Key'])
    expect(keys[0]).toBeTruthy()
    expect(keys[0]).not.toBe(keys[1])
  })

  it('maps the unified error format to ApiError', async () => {
    stubFetch(402, { error: { code: 'INSUFFICIENT_CREDITS', message: 'not enough credits' } })
    await expect(createApiClient().utter('t', { text: 'x' })).rejects.toMatchObject({
      status: 402,
      code: 'INSUFFICIENT_CREDITS',
    })
    await expect(createApiClient().utter('t', { text: 'x' })).rejects.toBeInstanceOf(ApiError)
  })

  it('only talks to /api paths', async () => {
    const f = stubFetch(200, [])
    await createApiClient().agents()
    expect(String(f.mock.calls[0]?.[0])).toBe('/api/agents')
  })
})
