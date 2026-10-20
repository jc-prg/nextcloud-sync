import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

let connectivity
beforeEach(async () => {
  vi.useFakeTimers()
  vi.resetModules() // the probe timer is module state
  connectivity = await import('@/stores/connectivity')
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('connectivity', () => {
  it('probes every 5 s while offline and stops once the server answers', async () => {
    const fetch = vi.fn().mockRejectedValueOnce(new TypeError('down')).mockResolvedValue({ status: 401 })
    vi.stubGlobal('fetch', fetch)

    connectivity.markOffline()
    expect(connectivity.backendOnline.value).toBe(false)

    await vi.advanceTimersByTimeAsync(5000)
    expect(fetch).toHaveBeenCalledWith('/api/rules', { method: 'HEAD' })
    expect(connectivity.backendOnline.value).toBe(false)

    await vi.advanceTimersByTimeAsync(5000)
    expect(connectivity.backendOnline.value).toBe(true)

    await vi.advanceTimersByTimeAsync(20000)
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it('starts only one probe when marked offline repeatedly', async () => {
    const fetch = vi.fn().mockRejectedValue(new TypeError('down'))
    vi.stubGlobal('fetch', fetch)
    connectivity.markOffline()
    connectivity.markOffline()
    await vi.advanceTimersByTimeAsync(5000)
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('markOnline stops probing', async () => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    connectivity.markOffline()
    connectivity.markOnline()
    await vi.advanceTimersByTimeAsync(15000)
    expect(fetch).not.toHaveBeenCalled()
    expect(connectivity.backendOnline.value).toBe(true)
  })
})
