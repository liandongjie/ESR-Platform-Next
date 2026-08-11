import AMapLoader from '@amap/amap-jsapi-loader'

const AMAP_VERSION = '2.0'
const AMAP_BASE_PLUGINS = ['AMap.Scale', 'AMap.ToolBar']

let amapPromise: Promise<unknown> | null = null

export function hasAmapConfiguration(): boolean {
  return Boolean(
    import.meta.env.VITE_AMAP_JS_API_KEY?.trim() &&
      import.meta.env.VITE_AMAP_SECURITY_JS_CODE?.trim(),
  )
}

export function loadAmap<T>(): Promise<T> {
  if (amapPromise) return amapPromise as Promise<T>

  const key = import.meta.env.VITE_AMAP_JS_API_KEY?.trim()
  const securityCode = import.meta.env.VITE_AMAP_SECURITY_JS_CODE?.trim()
  if (!key || !securityCode) {
    return Promise.reject(new Error('高德地图密钥尚未配置'))
  }

  window._AMapSecurityConfig = { securityJsCode: securityCode }
  amapPromise = AMapLoader.load({
    key,
    version: AMAP_VERSION,
    plugins: AMAP_BASE_PLUGINS,
  }).catch((error: unknown) => {
    amapPromise = null
    throw error
  })
  return amapPromise as Promise<T>
}
