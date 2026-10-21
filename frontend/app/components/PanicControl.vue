<script setup lang="ts">
defineProps<{
  hasActiveNotches: boolean
}>()

const emit = defineEmits<{
  (e: 'panic'): void
  (e: 'undo'): void
}>()
</script>

<template>
  <div class="panic-container">
    <button
      class="panic-btn"
      title="Phím tắt: P hoặc Escape"
      @click="emit('panic')"
    >
      <span>🚨 PANIC</span>
    </button>
    <button
      class="panic-undo-btn"
      title="Khôi phục lại notch trước khi Panic"
      @click="emit('undo')"
    >
      Hoàn tác
    </button>
  </div>
</template>

<style scoped>
.panic-container {
  display: flex;
  align-items: center;
  gap: 8px;
}

.panic-btn {
  min-height: 56px;
  min-width: 140px;
  padding: 8px 20px;
  background: linear-gradient(135deg, #ef4444, #b91c1c);
  color: #fff;
  font-family: var(--font-mono);
  font-size: 18px;
  font-weight: 900;
  letter-spacing: 1px;
  border: 2px solid #f87171;
  border-radius: 8px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  box-shadow: 0 4px 15px rgba(220, 38, 38, 0.4);
  transition: all 0.1s ease;
  touch-action: manipulation;
}

.panic-btn:active {
  transform: scale(0.96);
  background: var(--panic-hover);
}

.panic-undo-btn {
  padding: 6px 12px;
  font-size: 11px;
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  color: var(--text-dim);
  border-radius: 4px;
  cursor: pointer;
  transition: color 0.15s ease;
}

.panic-undo-btn:hover {
  color: var(--text-main);
}
</style>
