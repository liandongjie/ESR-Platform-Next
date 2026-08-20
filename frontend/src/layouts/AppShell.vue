<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { getApiErrorMessage } from '@/api/errors'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const loggingOut = ref(false)

async function signOut() {
  loggingOut.value = true
  try {
    await authStore.logout()
    await router.push({ name: 'login' })
  } catch (error: unknown) {
    ElMessage.error(getApiErrorMessage(error, '退出登录失败，请稍后重试'))
  } finally {
    loggingOut.value = false
  }
}
</script>

<template>
  <div class="app-shell">
    <header class="brand-bar">
      <div class="wordmark">
        <strong>Environmental and Social Risk Platform | 环境社会风险分析平台</strong>
        <!-- <span>环境社会风险分析平台</span> -->
      </div>
      <div v-if="authStore.user" class="account-nav">
        <span>{{ authStore.user.username }}</span>
        <button type="button" :disabled="loggingOut" @click="signOut">退出</button>
      </div>
    </header>
    <nav class="global-nav" aria-label="全局导航">
      <RouterLink class="global-nav-item" to="/">风险分析</RouterLink>
      <RouterLink class="global-nav-item" to="/tasks">历史任务</RouterLink>
    </nav>
    <div class="body-shell">
      <main class="main-content">
        <slot />
      </main>
    </div>
  </div>
</template>
