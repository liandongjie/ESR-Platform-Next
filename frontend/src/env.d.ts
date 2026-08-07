/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  readonly VITE_DEV_PROXY_TARGET?: string
  readonly VITE_AMAP_JS_API_KEY?: string
  readonly VITE_AMAP_SECURITY_JS_CODE?: string
  readonly VITE_AMAP_CENTER_LNG?: string
  readonly VITE_AMAP_CENTER_LAT?: string
  readonly VITE_AMAP_ZOOM?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

interface Window {
  _AMapSecurityConfig?: {
    securityJsCode: string
  }
}
