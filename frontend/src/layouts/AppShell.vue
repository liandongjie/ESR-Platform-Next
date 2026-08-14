<template>
  <div class="app-shell">
    <header class="brand-bar">
      <div class="wordmark">
        <strong>Environmental and Social Risk Platform | 环境社会风险分析平台</strong>
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
