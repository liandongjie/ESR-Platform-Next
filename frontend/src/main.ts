import 'element-plus/dist/index.css'
import '@/assets/base.css'

import ElementPlus from 'element-plus'
import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from '@/App.vue'
import { configureHttpAuth } from '@/api/http'
import router from '@/router'
import { useAuthStore } from '@/stores/auth'

const app = createApp(App)
const pinia = createPinia()
const authStore = useAuthStore(pinia)

configureHttpAuth({
  getAccessToken: () => authStore.accessToken,
  getSessionEpoch: () => authStore.sessionEpoch,
  refresh: (expectedEpoch) => authStore.refresh(expectedEpoch),
  onSessionExpired: (expectedEpoch) => {
    if (!authStore.expireSession('登录状态已过期，请重新登录', expectedEpoch)) return
    const redirect = router.currentRoute.value.meta.requiresAuth
      ? router.currentRoute.value.fullPath
      : undefined
    void router.push({ name: 'login', query: redirect ? { redirect } : {} })
  },
})

app.use(pinia).use(router).use(ElementPlus).mount('#app')
