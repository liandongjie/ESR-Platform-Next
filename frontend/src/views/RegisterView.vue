<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import { getApiErrorMessage } from '@/api/errors'
import { useAuthStore } from '@/stores/auth'
import { useSystemStore } from '@/stores/system'

const router = useRouter()
const authStore = useAuthStore()
const systemStore = useSystemStore()
const username = ref('')
const password = ref('')
const error = ref<string | null>(null)
const registrationDisabled = computed(
  () => systemStore.capabilities?.registration_enabled === false,
)

void systemStore.load()

async function submit() {
  if (registrationDisabled.value) return
  error.value = null
  try {
    await authStore.register({ username: username.value.trim(), password: password.value })
    await router.push('/')
  } catch (cause) {
    error.value = getApiErrorMessage(cause, '注册失败')
  }
}
</script>

<template>
  <main class="auth-page">
    <section class="auth-card" aria-labelledby="register-title">
      <div class="auth-brand">Environmental and Social Risk Platform</div>
      <h1 id="register-title">创建账号</h1>
      <p class="auth-subtitle">注册后即可保存和查看本人任务</p>

      <el-alert
        v-if="registrationDisabled"
        title="当前环境已关闭公开注册"
        type="warning"
        :closable="false"
      />
      <el-alert v-if="error" :title="error" type="error" :closable="false" />

      <form class="auth-form" @submit.prevent="submit">
        <label for="register-username">用户名</label>
        <el-input id="register-username" v-model="username" autocomplete="username" required />
        <label for="register-password">密码</label>
        <el-input
          id="register-password"
          v-model="password"
          type="password"
          autocomplete="new-password"
          show-password
          required
        />
        <el-button
          type="primary"
          native-type="submit"
          :loading="authStore.loading"
          :disabled="registrationDisabled"
        >
          注册并登录
        </el-button>
      </form>

      <RouterLink to="/login">返回登录</RouterLink>
    </section>
  </main>
</template>
