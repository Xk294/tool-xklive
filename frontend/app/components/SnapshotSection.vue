<script setup lang="ts">
import { useI18n } from '~/composables/useI18n'

const { t } = useI18n()

defineProps<{
  snapshotBandsCount?: number
}>()

const emit = defineEmits<{
  (e: 'take'): void
  (e: 'rollback'): void
}>()
</script>

<template>
  <div class="c-card snapshot-card">
    <div class="c-card-title">
      <div class="title-left">
        <span>📸 {{ t('snapshot.title') }}</span>
      </div>
      <span v-if="snapshotBandsCount && snapshotBandsCount > 0" class="bands-count font-mono">
        {{ t('snapshot.bandsSaved', { count: snapshotBandsCount }) }}
      </span>
    </div>

    <p class="snapshot-desc">
      {{ t('snapshot.description') }}
    </p>

    <div class="snapshot-actions">
      <button class="c-btn-secondary btn-take" @click="emit('take')">
        {{ t('common.takeSnapshot') }}
      </button>
      <button class="c-btn-secondary btn-rollback" @click="emit('rollback')">
        {{ t('common.rollback') }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.snapshot-card {
  margin-bottom: 12px;
}

.bands-count {
  font-size: 10px;
  background: rgba(16, 185, 129, 0.15);
  color: var(--accent-green);
  border: 1px solid rgba(16, 185, 129, 0.3);
  padding: 1px 6px;
  border-radius: 4px;
}

.snapshot-desc {
  font-size: 11px;
  color: var(--text-dim);
  line-height: 1.4;
  margin-bottom: 8px;
}

.snapshot-actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.btn-take:hover {
  border-color: var(--accent-cyan);
  color: var(--accent-cyan);
}

.btn-rollback {
  color: var(--accent-amber);
}

.btn-rollback:hover {
  border-color: var(--accent-amber);
  background: rgba(245, 158, 11, 0.1);
}
</style>
