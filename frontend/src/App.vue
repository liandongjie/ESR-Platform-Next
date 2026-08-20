<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import AppShell from '@/layouts/AppShell.vue'

const route = useRoute()
const publicPage = computed(() => Boolean(route.meta.public))
</script>

<template>
  <RouterView v-if="publicPage" />
  <AppShell v-else><RouterView /></AppShell>
</template>
