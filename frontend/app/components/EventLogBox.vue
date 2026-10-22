<script setup lang="ts">
import type { LogEntry } from '~/composables/useCompanionSocket'
import { useI18n } from '~/composables/useI18n'

const { t } = useI18n()

defineProps<{
  logs: LogEntry[]
}>()

const emit = defineEmits<{
  (e: 'clear'): void
}>()
</script>

<template>
  <div class="c-card">
    <div class="c-card-title">
      <span>{{ t('log.title') }}</span>
      <button class="c-btn-small" @click="emit('clear')">{{ t('common.clearLog') }}</button>
    </div>
    <div class="log-box">
      <div
        v-for="log in logs"
        :key="log.id"
        :class="['log-entry', log.type]"
      >
        <span class="time">{{ log.time }}</span>
        <span>{{ log.text_code ? t(log.text_code, log.params) : log.text }}</span>
      </div>
      <div v-if="logs.length === 0" class="log-empty">
        {{ t('log.empty') }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.log-box {
  height: 160px;
  overflow-y: auto;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-dim);
  background: #07090e;
  padding: 8px;
  border-radius: 4px;
  border: 1px solid var(--border-color);
}

.log-entry {
  margin-bottom: 4px;
  line-height: 1.3;
}

.log-entry span.time {
  color: #64748b;
  margin-right: 6px;
}

.log-entry.panic {
  color: #f87171;
  font-weight: 700;
}

.log-entry.approved {
  color: #86efac;
}

.log-entry.warning {
  color: #fde047;
}

.log-empty {
  color: #475569;
  font-style: italic;
  padding: 8px 0;
}
</style>
