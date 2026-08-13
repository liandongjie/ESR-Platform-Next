<script setup lang="ts">
defineProps<{
  open: boolean
  title: string
}>()

defineEmits<{ close: [] }>()
</script>

<template>
  <section v-show="open" class="workspace-result-drawer panel-card" aria-label="分析结果抽屉">
    <header class="workspace-result-drawer-header">
      <strong>{{ title }}</strong>
      <button type="button" aria-label="关闭结果抽屉" @click="$emit('close')">×</button>
    </header>
    <div class="workspace-result-drawer-body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.workspace-result-drawer {
  position: absolute;
  z-index: 10;
  right: 12px;
  bottom: 12px;
  left: 12px;
  display: flex;
  max-height: calc(100% - 24px);
  height: 300px;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  padding: 0;
}

.workspace-result-drawer-header {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
}

.workspace-result-drawer-header button {
  width: 28px;
  height: 28px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--muted);
  font: inherit;
  font-size: 20px;
  cursor: pointer;
}

.workspace-result-drawer-header button:hover {
  background: #f0f3f9;
}

.workspace-result-drawer-header button:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 1px;
}

.workspace-result-drawer-body {
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 12px 14px 14px;
}
</style>
