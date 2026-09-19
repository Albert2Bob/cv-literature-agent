<template>
  <div class="ai-avatar-fallback" :class="type">
    <span v-if="type === 'paper'">📄</span>
    <span v-else>🤖</span>
  </div>
</template>

<script setup>
defineProps({
  type: {
    type: String,
    default: 'default'
  }
})
</script>

<style scoped>
.ai-avatar-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  border-radius: 50%;
}

.paper {
  background: linear-gradient(45deg, #14b8a6, #4ade80);
}

.default, .cv {
  background: linear-gradient(45deg, #3f51b5, #5677fc);
}
</style>

<style scoped>
.ai-avatar-fallback {
  color: transparent;
  background-color: #eaf2ff;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23175fcb' stroke-width='1.7' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M8 8.5h8a3 3 0 0 1 3 3v5a3 3 0 0 1-3 3H8a3 3 0 0 1-3-3v-5a3 3 0 0 1 3-3Z'/%3E%3Cpath d='M12 8.5V5.5M9 13h.01M15 13h.01M9 16.5h6'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: center;
  background-size: 20px;
  border-radius: 10px;
}
.paper {
  background-color: #e8f7f5;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23087f79' stroke-width='1.7' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M6.5 3.5h8l3 3v14h-11z'/%3E%3Cpath d='M14.5 3.5v4h4M9.5 12h5M9.5 15.5h5'/%3E%3C/svg%3E");
}
</style>
