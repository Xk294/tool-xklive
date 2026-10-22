<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from '~/composables/useI18n'

const { t } = useI18n()

const props = defineProps<{
  isOpen: boolean
  fetchDynamics: () => Promise<any>
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const loading = ref(false)
const suggestions = ref<any[]>([])

async function loadData() {
  loading.value = true
  const res = await props.fetchDynamics()
  if (res && res.suggestions) {
    suggestions.value = res.suggestions
  }
  loading.value = false
}

onMounted(() => {
  if (props.isOpen) {
    loadData()
  }
})
</script>

<template>
  <div v-if="isOpen" class="modal-overlay" @click.self="emit('close')">
    <div class="modal-card">
      <div class="modal-header">
        <h3>{{ t('dynamics.title') }}</h3>
        <button class="close-btn" @click="emit('close')">✕</button>
      </div>

      <div class="modal-body">
        <p class="notice-box">
          ℹ️ {{ t('dynamics.notice') }}
        </p>

        <div v-if="loading" class="loading-state">
          Đang tính toán phân tích tín hiệu...
        </div>

        <div v-else class="dyn-list">
          <div
            v-for="item in suggestions"
            :key="item.channel"
            class="dyn-card"
          >
            <div class="dyn-header">
              <span class="dyn-ch">CH {{ item.channel.toString().padStart(2, '0') }}</span>
              <span class="dyn-peak">{{ t('dynamics.currentPeak') }}: <b>{{ item.current_peak_db ? item.current_peak_db.toFixed(1) : '-inf' }} dBFS</b></span>
            </div>

            <div class="dyn-details">
              <div class="detail-item">
                <span class="label">{{ t('dynamics.gainStaging') }}:</span>
                <span class="val text-cyan">{{ item.gain_advice || 'Mức Gain tối ưu (-18 dBFS RMS)' }}</span>
              </div>
              <div class="detail-item">
                <span class="label">{{ t('dynamics.compThreshold') }}:</span>
                <span class="val">{{ item.comp_threshold_db ? `${item.comp_threshold_db} dB` : '-16.0 dB (Ratio 2.5:1)' }}</span>
              </div>
              <div class="detail-item">
                <span class="label">{{ t('dynamics.gateThreshold') }}:</span>
                <span class="val">{{ item.gate_threshold_db ? `${item.gate_threshold_db} dB` : '-54.0 dB' }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="modal-footer">
        <button class="c-btn-secondary" @click="loadData">{{ t('common.refresh') }}</button>
        <button class="c-btn-secondary" @click="emit('close')">{{ t('common.close') }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.75);
  backdrop-filter: blur(3px);
  z-index: 200;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
}

.modal-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  max-width: 620px;
  width: 100%;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
}

.modal-header {
  padding: 14px 18px;
  border-bottom: 1px solid var(--border-color);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.modal-header h3 {
  font-size: 15px;
  font-weight: 700;
  color: var(--accent-cyan);
}

.close-btn {
  background: transparent;
  border: none;
  color: var(--text-dim);
  font-size: 16px;
  cursor: pointer;
}

.modal-body {
  padding: 16px 18px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.notice-box {
  background: rgba(56, 189, 248, 0.1);
  border: 1px solid var(--accent-cyan);
  color: var(--accent-cyan);
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.4;
}

.dyn-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.dyn-card {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 10px 14px;
}

.dyn-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 6px;
}

.dyn-ch {
  font-weight: 800;
  font-family: var(--font-mono);
  color: var(--accent-amber);
}

.dyn-peak {
  font-size: 11px;
  color: var(--text-dim);
  font-family: var(--font-mono);
}

.dyn-peak b {
  color: var(--text-main);
}

.dyn-details {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
}

.detail-item {
  display: flex;
  justify-content: space-between;
}

.detail-item .label {
  color: var(--text-dim);
}

.detail-item .val {
  font-family: var(--font-mono);
  color: var(--text-main);
}

.text-cyan {
  color: var(--accent-cyan) !important;
}

.modal-footer {
  padding: 12px 18px;
  border-top: 1px solid var(--border-color);
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.loading-state {
  text-align: center;
  padding: 30px 0;
  color: var(--text-dim);
}
</style>
