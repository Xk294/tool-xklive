<script setup lang="ts">
import type { Proposal } from '~/composables/useCompanionSocket'
import { useI18n } from '~/composables/useI18n'
import { formatTargetName } from '~/utils/eventTranslator'

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
  return formatTargetName(p, t)
}
</script>

<template>
  <div class="c-card proposals-card">
    <div class="c-card-title">
      <div class="title-group">
        <span>⚡ {{ t('proposals.title') }}</span>
      </div>
      <span
        :class="['proposal-badge font-mono', proposals.length > 0 ? 'badge-alert' : 'badge-safe']"
      >
        {{ t('proposals.waiting', { n: proposals.length }) }}
      </span>
    </div>

    <div v-if="proposals.length === 0" class="empty-state">
      <span class="safe-icon">🛡️</span>
      <span class="empty-msg">{{ t('proposals.empty') }}</span>
    </div>

    <div v-else class="proposals-list">
      <div class="quick-tip">
        <span>⌨️ {{ t('proposals.quickTip') }}</span>
      </div>

      <div
        v-for="(p, idx) in proposals"
        :key="p.id"
        :class="['proposal-card', { 'is-top': idx === 0 }]"
      >
        <div class="prop-header">
          <div class="prop-target">
            <span class="target-name font-mono">{{ formatTarget(p) }}</span>
            <span class="confidence-tag font-mono">
              {{ (p.confidence_score * 100).toFixed(0) }}% {{ t('proposals.confidence') }}
            </span>
          </div>
          <div class="prop-metrics">
            <span class="prop-freq font-mono">{{ p.freq_hz.toFixed(1) }} Hz</span>
            <span class="prop-gain font-mono">{{ p.gain_db.toFixed(1) }} dB</span>
          </div>
        </div>

        <!-- CONFIDENCE LEVEL BAR -->
        <div class="confidence-bar-bg">
          <div
            class="confidence-bar-fill"
            :style="{ width: Math.min(100, p.confidence_score * 100) + '%' }"
          />
        </div>

        <div class="prop-actions">
          <button class="btn-approve" @click="emit('approve', p.id)">
            {{ t('common.approve') }}
          </button>
          <button class="btn-reject" @click="emit('reject', p.id)">
            {{ t('common.reject') }}
          </button>
          <button class="btn-snooze" @click="emit('snooze', p.id)">
            {{ t('common.snooze') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.proposals-card {
  margin-bottom: 12px;
}

.proposal-badge {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 12px;
}

.badge-safe {
  background: rgba(16, 185, 129, 0.15);
  color: var(--accent-green);
  border: 1px solid rgba(16, 185, 129, 0.3);
}

.badge-alert {
  background: rgba(239, 68, 68, 0.2);
  color: #f87171;
  border: 1px solid rgba(239, 68, 68, 0.5);
  animation: pulse-border 1.5s infinite;
}

@keyframes pulse-border {
  0%, 100% { box-shadow: 0 0 4px rgba(239, 68, 68, 0.4); }
  50% { box-shadow: 0 0 12px rgba(239, 68, 68, 0.8); }
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 24px 12px;
  text-align: center;
  gap: 8px;
}

.safe-icon {
  font-size: 24px;
}

.empty-msg {
  font-size: 11px;
  color: var(--text-dim);
}

.quick-tip {
  font-size: 10px;
  color: var(--accent-cyan);
  background: rgba(56, 189, 248, 0.08);
  padding: 4px 8px;
  border-radius: 4px;
  margin-bottom: 8px;
}

.proposals-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.proposal-card {
  background: #090e17;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: all 0.15s ease;
}

.proposal-card.is-top {
  border-color: #ef4444;
  box-shadow: 0 0 12px rgba(239, 68, 68, 0.25);
}

.prop-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.prop-target {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.target-name {
  font-weight: 700;
  font-size: 12px;
  color: var(--text-main);
}

.confidence-tag {
  font-size: 10px;
  color: var(--accent-amber);
}

.prop-metrics {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

.prop-freq {
  font-size: 13px;
  font-weight: 700;
  color: var(--accent-cyan);
}

.prop-gain {
  font-size: 11px;
  font-weight: 700;
  color: var(--accent-red);
}

.confidence-bar-bg {
  width: 100%;
  height: 4px;
  background: #151d2a;
  border-radius: 2px;
  overflow: hidden;
}

.confidence-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #f59e0b, #ef4444);
  border-radius: 2px;
}

.prop-actions {
  display: flex;
  gap: 6px;
}

.btn-approve {
  flex: 2;
  padding: 6px 10px;
  background: linear-gradient(135deg, #059669, #047857);
  border: 1px solid #10b981;
  color: #fff;
  border-radius: 4px;
  font-weight: 700;
  font-size: 11px;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(5, 150, 105, 0.3);
  transition: all 0.15s ease;
}

.btn-approve:hover {
  background: #047857;
  box-shadow: 0 0 10px rgba(16, 185, 129, 0.5);
}

.btn-reject {
  flex: 1;
  padding: 6px;
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  color: var(--text-dim);
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-reject:hover {
  border-color: var(--accent-red);
  color: var(--accent-red);
}

.btn-snooze {
  flex: 1;
  padding: 6px;
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  color: var(--text-dim);
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-snooze:hover {
  border-color: var(--accent-amber);
  color: var(--accent-amber);
}
</style>
