<script setup>
const version = __APP_VERSION__
</script>

<template>
  <RouterView />
  <div class="app-version">v{{ version }}</div>
</template>

<style scoped>
.app-version {
  position: fixed;
  right: 10px;
  bottom: 6px;
  font-size: 11px;
  color: var(--text-muted, #888);
  pointer-events: none;
  user-select: none;
  z-index: 1;
}
</style>
