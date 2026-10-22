<script setup lang="ts">
import { useI18n } from '~/composables/useI18n'

const { t } = useI18n()

const emit = defineEmits<{
  (e: 'take'): void
  (e: 'rollback'): void
}>()
</script>

<template>
  <div class="c-card">
    <div class="c-card-title">
      <span>{{ t('snapshot.title') }}</span>
    </div>
    <p class="snapshot-desc">
      {{ t('snapshot.description') }}
    </p>
    <div class="snapshot-bar">
      <button class="c-btn-secondary" @click="emit('take')">{{ t('common.takeSnapshot') }}</button>
      <button class="c-btn-secondary rollback-btn" @click="emit('rollback')">{{ t('common.rollback') }}</button>
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
