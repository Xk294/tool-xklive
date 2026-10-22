<script setup lang="ts">
import type { Proposal } from '~/composables/useCompanionSocket'
import { useI18n } from '~/composables/useI18n'

const { t } = useI18n()

defineProps<{
  proposals: Proposal[]
}>()

const emit = defineEmits<{
  (e: 'approve', id: string): void
  (e: 'reject', id: string): void
  (e: 'snooze', id: string): void
}>()

function formatTarget(p: Proposal): string {
  if (p.target === 'main' || p.channel === 0) {
    return 'Main LR'
  }
  if (p.target === 'bus') {
    return t('proposals.bus', { n: p.bus ?? '' })
  }
  if (!p.channel_name) {
    return t('proposals.channel', { n: p.channel })
  }
  const match = p.channel_name.match(/^(?:K\u00eanh|Ch)\s*0?(\d+)$/i)
  if (match) {
    return t('proposals.channel', { n: match[1] })
  }
  return p.channel_name
}
</script>

<template>
  <div class="c-card">
    <div class="c-card-title">
      <span>{{ t('proposals.title') }}</span>
      <span :class="['badge', proposals.length > 0 ? 'reconnecting' : 'connected']">
        {{ t('proposals.waiting', { n: proposals.length }) }}
      </span>
    </div>

    <div v-if="proposals.length === 0" class="empty-state">
      {{ t('proposals.empty') }}
    </div>

    <div v-else class="proposals-list">
      <div
        v-for="p in proposals"
        :key="p.id"
        class="proposal-card"
      >
        <div class="prop-header">
          <span class="prop-freq">{{ p.freq_hz.toFixed(1) }} Hz</span>
          <span class="prop-gain">{{ p.gain_db.toFixed(1) }} dB</span>
        </div>

        <div class="prop-meta">
          {{ t('proposals.target') }}: <b>{{ formatTarget(p) }}</b> | {{ t('proposals.confidence') }}: <b>{{ (p.confidence_score * 100).toFixed(0) }}%</b>
        </div>

        <div class="prop-actions">
          <button class="btn-approve" @click="emit('approve', p.id)">{{ t('common.approve') }}</button>
          <button class="btn-reject" @click="emit('reject', p.id)">{{ t('common.reject') }}</button>
          <button class="btn-snooze" @click="emit('snooze', p.id)">{{ t('common.snooze') }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.empty-state {
  color: var(--text-dim);
  font-size: 12px;
  text-align: center;
  padding: 16px 0;
}

.proposal-card {
  background: rgba(239, 68, 68, 0.1);
  border: 2px solid var(--accent-red);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 10px;
  animation: alertPulse 1.8s infinite ease-in-out;
}

@keyframes alertPulse {
  0%, 100% { border-color: rgba(239, 68, 68, 0.8); }
  50% { border-color: rgba(239, 68, 68, 0.3); }
}

.prop-header {
  display: flex;
  justify-content: space-between;
  font-weight: 700;
  margin-bottom: 6px;
}

.prop-freq {
  font-family: var(--font-mono);
  font-size: 18px;
  color: #fca5a5;
}

.prop-gain {
  color: var(--accent-red);
  font-family: var(--font-mono);
  font-weight: 700;
}

.prop-meta {
  font-size: 12px;
  color: var(--text-dim);
  margin-bottom: 10px;
}

.prop-actions {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr;
  gap: 6px;
}

.btn-approve {
  background: var(--accent-green);
  color: #000;
  font-weight: 700;
  border: none;
  padding: 10px;
  border-radius: 5px;
  cursor: pointer;
  min-height: 44px;
}

.btn-reject {
  background: var(--bg-tertiary);
  color: var(--text-main);
  border: 1px solid var(--border-color);
  border-radius: 5px;
  cursor: pointer;
  min-height: 44px;
}

.btn-snooze {
  background: transparent;
  color: var(--accent-amber);
  border: 1px solid var(--accent-amber);
  border-radius: 5px;
  cursor: pointer;
  min-height: 44px;
}

.badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  font-family: var(--font-mono);
  text-transform: uppercase;
}

.badge.connected {
  background: rgba(34, 197, 94, 0.15);
  color: var(--accent-green);
  border: 1px solid var(--accent-green);
}

.badge.reconnecting {
  background: rgba(245, 158, 11, 0.15);
  color: var(--accent-amber);
  border: 1px solid var(--accent-amber);
}
</style>
