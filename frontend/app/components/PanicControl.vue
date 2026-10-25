<script setup lang="ts">
import { useI18n } from '~/composables/useI18n'

const { t } = useI18n()

const emit = defineEmits<{
  (e: 'panic'): void
  (e: 'undo'): void
}>()
</script>

<template>
  <div class="panic-container">
    <button
      class="panic-btn"
      :title="t('panic.shortcut')"
      :aria-label="t('panic.button')"
      @click="emit('panic')"
    >
      <span>{{ t('panic.button') }}</span>
    </button>
    <button
      class="panic-undo-btn"
      :title="t('panic.undoTitle')"
      :aria-label="t('common.undo')"
      @click="emit('undo')"
    >
      {{ t('common.undo') }}
    </button>
  </div>
</template>

<style scoped>
.panic-container {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.panic-btn {
  height: 32px;
  padding: 0 14px;
  background: linear-gradient(135deg, #ef4444, #b91c1c);
  color: #fff;
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.5px;
  border: 1px solid #f87171;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  box-shadow: 0 2px 10px rgba(220, 38, 38, 0.4);
  transition: all 0.1s ease;
  white-space: nowrap;
}

.panic-btn:active {
  transform: scale(0.96);
  background: var(--panic-hover);
}

.panic-undo-btn {
  height: 32px;
  padding: 0 10px;
  font-size: 11px;
  font-weight: 600;
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  color: var(--text-dim);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
  white-space: nowrap;
}

.panic-undo-btn:hover {
  color: var(--text-main);
  border-color: var(--border-highlight);
}
</style>
