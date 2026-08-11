import AMapLoader from '@amap/amap-jsapi-loader'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@amap/amap-jsapi-loader', () => ({
  default: { load: vi.fn() },
}))

describe('shared AMap loader', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.stubEnv('VITE_AMAP_JS_API_KEY', 'test-key')
    vi.stubEnv('VITE_AMAP_SECURITY_JS_CODE', 'test-security-code')
    vi.mocked(AMapLoader.load).mockReset()
  })

  it('loads the configured SDK once and shares the same namespace', async () => {
    const namespace = { Map: class {} }
    vi.mocked(AMapLoader.load).mockResolvedValue(namespace as never)
    const { loadAmap } = await import('@/map/amap')

    const [first, second] = await Promise.all([loadAmap(), loadAmap()])

    expect(first).toBe(namespace)
    expect(second).toBe(namespace)
    expect(AMapLoader.load).toHaveBeenCalledOnce()
    expect(AMapLoader.load).toHaveBeenCalledWith({
      key: 'test-key',
      version: '2.0',
      plugins: ['AMap.Scale', 'AMap.ToolBar'],
    })
    expect(window._AMapSecurityConfig).toEqual({ securityJsCode: 'test-security-code' })
  })

  it('rejects missing credentials before loading the SDK', async () => {
    vi.stubEnv('VITE_AMAP_JS_API_KEY', '')
    const { loadAmap } = await import('@/map/amap')

    await expect(loadAmap()).rejects.toThrow('高德地图密钥尚未配置')
    expect(AMapLoader.load).not.toHaveBeenCalled()
  })
})
