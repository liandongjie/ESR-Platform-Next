<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { getApiErrorMessage } from '@/api/errors'
import { useAuthStore } from '@/stores/auth'
import { useSystemStore } from '@/stores/system'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const systemStore = useSystemStore()
const username = ref('')
const password = ref('')
const error = ref<string | null>(null)

void systemStore.load()

async function submit() {
  error.value = null
  try {
    await authStore.login({ username: username.value.trim(), password: password.value })
    const requestedRedirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    const redirect = requestedRedirect.startsWith('/') && !requestedRedirect.startsWith('//')
      ? requestedRedirect
      : '/'
    await router.push(redirect)
  } catch (cause) {
    error.value = getApiErrorMessage(cause, '用户名或密码错误')
  }
}
</script>

<template>
  <main class="auth-page">
    <section class="auth-card" aria-labelledby="login-title">
      <div class="auth-brand">Environmental and Social Risk Platform</div>
      <h1 id="login-title">登录</h1>
      <p class="auth-subtitle">进入环境社会风险分析工作台</p>

      <el-alert v-if="authStore.notice" :title="authStore.notice" type="warning" :closable="false" />
      <el-alert
        v-if="authStore.bootstrapError"
        :title="authStore.bootstrapError"
        type="error"
        :closable="false"
      />
      <el-alert v-if="error" :title="error" type="error" :closable="false" />

      <form class="auth-form" @submit.prevent="submit">
        <label for="username">用户名</label>
        <el-input id="username" v-model="username" autocomplete="username" required />
        <label for="password">密码</label>
        <el-input
          id="password"
          v-model="password"
          type="password"
          autocomplete="current-password"
          show-password
          required
        />
        <el-button type="primary" native-type="submit" :loading="authStore.loading">登录</el-button>
      </form>

      <RouterLink v-if="systemStore.capabilities?.registration_enabled" to="/register">
        创建账号
      </RouterLink>
      <p v-else-if="systemStore.capabilities && !systemStore.capabilities.registration_enabled" class="auth-hint">
        当前仅开放演示账号登录
      </p>
    </section>
  </main>
</template>
