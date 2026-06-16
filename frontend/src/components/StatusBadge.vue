<script setup>
defineProps({ status: String })
</script>

<template>
  <span class="badge" :class="`badge-${status}`">{{ status }}</span>
</template>
