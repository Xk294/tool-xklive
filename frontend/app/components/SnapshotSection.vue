<script setup lang="ts">
const emit = defineEmits<{
  (e: 'take'): void
  (e: 'rollback'): void
}>()
</script>

<template>
  <div class="c-card">
    <div class="c-card-title">
      <span>Chụp & Khôi Phục PEQ (Pre-Show)</span>
    </div>
    <p class="snapshot-desc">
      Lưu trạng thái PEQ trước giờ biểu diễn. Khôi phục toàn bộ trong &lt; 1 giây khi cần thiết.
    </p>
    <div class="snapshot-bar">
      <button class="c-btn-secondary" @click="emit('take')">📸 Chụp Snapshot</button>
      <button class="c-btn-secondary rollback-btn" @click="emit('rollback')">⏪ Khôi Phục (&lt; 1s)</button>
    </div>
  </div>
</template>

<style scoped>
.snapshot-desc {
  font-size: 11px;
  color: var(--text-dim);
  margin-bottom: 8px;
}

.snapshot-bar {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}

.rollback-btn {
  color: var(--accent-amber);
}
</style>
