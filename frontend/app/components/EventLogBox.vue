<script setup lang="ts">
import type { LogEntry } from '~/composables/useCompanionSocket'
import { useI18n } from '~/composables/useI18n'
import { translateEventMessage } from '~/utils/eventTranslator'

const { t } = useI18n()

defineProps<{
  logs: LogEntry[]
}>()

const emit = defineEmits<{
  (e: 'clear'): void
}>()

function renderLogText(log: LogEntry): string {
  return translateEventMessage(log, t)
}
</script>

<template>
  <div class="c-card log-card">
    <div class="c-card-title">
      <div class="title-group">
        <span>📜 {{ t('log.title') }}</span>
      </div>
      <button class="c-btn-small" @click="emit('clear')">
        {{ t('common.clearLog') }}
      </button>
    </div>

    <div class="log-box">
      <div
        v-for="log in logs"
        :key="log.id"
        :class="['log-entry', log.type]"
      >
        <span class="log-time font-mono">{{ log.time }}</span>
        <span class="log-icon">
          <template v-if="log.type === 'panic'">🚨</template>
          <template v-else-if="log.type === 'warning'">⚠️</template>
          <template v-else-if="log.type === 'approved'">✅</template>
          <template v-else>ℹ️</template>
        </span>
        <span class="log-text">{{ renderLogText(log) }}</span>
      </div>

      <div v-if="logs.length === 0" class="log-empty">
        {{ t('log.empty') }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.log-card {
  margin-bottom: 0;
}

.log-box {
  height: 280px;
  overflow-y: auto;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-dim);
  background: #06080d;
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.log-entry {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  line-height: 1.35;
}

.log-time {
  color: #64748b;
  flex-shrink: 0;
}

.log-icon {
  flex-shrink: 0;
  font-size: 10px;
}

.log-text {
  word-break: break-word;
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
  padding: 16px 0;
  text-align: center;
}
</style>
