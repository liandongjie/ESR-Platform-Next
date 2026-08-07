<script setup lang="ts">
defineProps<{
  label: string
  value: string
  hint: string
}>()
</script>

<template>
  <article class="status-card">
    <span class="status-label">{{ label }}</span>
    <strong>{{ value }}</strong>
    <small>{{ hint }}</small>
  </article>
</template>
