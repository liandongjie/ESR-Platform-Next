<script setup lang="ts">
import { List, MapLocation } from '@element-plus/icons-vue'
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <div class="brand">
        <div class="brand-mark">ESR</div>
        <div class="brand-title">环境社会风险分析平台</div>
      </div>
      <div class="topbar-actions">
        <el-avatar :size="34">DJ</el-avatar>
      </div>
    </header>
    <div class="body-shell">
      <aside class="sidebar" aria-label="全局导航">
        <RouterLink class="nav-item" to="/" title="分析工作台">
          <el-icon><MapLocation /></el-icon>
          <span>工作台</span>
        </RouterLink>
        <RouterLink class="nav-item" to="/tasks" title="历史任务">
          <el-icon><List /></el-icon>
          <span>历史任务</span>
        </RouterLink>
      </aside>
      <main class="main-content">
        <slot />
      </main>
    </div>
  </div>
</template>
