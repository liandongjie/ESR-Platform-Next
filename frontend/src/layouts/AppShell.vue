<script setup lang="ts">
import { DataAnalysis, List, MapLocation } from '@element-plus/icons-vue'
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <div class="brand">
        <div class="brand-mark">ESR</div>
        <div>
          <div class="brand-title">环境社会风险分析平台</div>
          <div class="brand-subtitle">WebGIS · Engineering Rebuild</div>
        </div>
      </div>
      <div class="topbar-actions">
        <span class="stage-badge">Phase 2D</span>
        <el-avatar :size="34">DJ</el-avatar>
      </div>
    </header>

    <div class="body-shell">
      <aside class="sidebar">
        <RouterLink class="nav-item" to="/">
          <el-icon><MapLocation /></el-icon>
          <span>分析工作台</span>
        </RouterLink>
        <RouterLink class="nav-item" to="/tasks">
          <el-icon><List /></el-icon>
          <span>历史任务</span>
        </RouterLink>
        <div class="sidebar-note">
          <el-icon><DataAnalysis /></el-icon>
          <span>风险分析任务已支持服务端历史追踪</span>
        </div>
      </aside>

      <main class="main-content">
        <slot />
      </main>
    </div>
  </div>
</template>
