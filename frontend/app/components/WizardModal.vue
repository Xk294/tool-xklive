<script setup lang="ts">
import { ref, onUnmounted, watch } from 'vue'
import { useI18n } from '~/composables/useI18n'
import type {
  WizardStartResult,
  WizardStopResult,
  WizardStatusSnapshot
} from '~/composables/useCompanionSocket'

const { t } = useI18n()

const props = defineProps<{
  isOpen: boolean
  startWizard: (channel: number, maxBoost: number, dwellTime: number) => Promise<WizardStartResult>
  stopWizard: () => Promise<WizardStopResult>
  getWizardStatus: () => Promise<WizardStatusSnapshot>
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const targetChannel = ref(1)
const maxBoostDb = ref(3.0)
const dwellTimeS = ref(3.0)
const errorMsg = ref('')
const statusData = ref<WizardStatusSnapshot>({
  state: 'idle',
  current_gain_added: 0.0,
  detected_notches: 0
})
let pollInterval: ReturnType<typeof setInterval> | null = null

async function pollStatus() {
  try {
    const data = await props.getWizardStatus()
    if (data) {
      statusData.value = data
      if (data.state !== 'running' && data.state !== 'paused') {
        stopPolling()
      }
    }
  } catch (err: unknown) {
    stopPolling()
    statusData.value = { ...statusData.value, state: 'aborted' }
    errorMsg.value = err instanceof Error ? err.message : String(err)
  }
}

async function handleStart() {
  errorMsg.value = ''
  const res = await props.startWizard(targetChannel.value, maxBoostDb.value, dwellTimeS.value)
  if (!res || res.success === false) {
    errorMsg.value = res?.detail || 'Không thể khởi động thuật toán dò hú.'
    return
  }
  startPolling()
}

async function handleStop() {
  stopPolling()
  await props.stopWizard()
  await pollStatus()
}

async function handleClose() {
  if (statusData.value.state === 'running' || statusData.value.state === 'paused') {
    stopPolling()
    await props.stopWizard().catch(() => {})
  }
  emit('close')
}

function startPolling() {
  stopPolling()
  pollStatus()
  pollInterval = setInterval(pollStatus, 1000)
}

function stopPolling() {
  if (pollInterval) {
    clearInterval(pollInterval)
    pollInterval = null
  }
}

watch(() => props.isOpen, (open) => {
  if (open) {
    pollStatus()
  } else {
    stopPolling()
  }
}, { immediate: true })

onUnmounted(() => {
  const wasRunning = statusData.value.state === 'running' || statusData.value.state === 'paused'
  stopPolling()
  if (wasRunning) {
    props.stopWizard().catch(() => {})
  }
})
</script>

<template>
  <div v-if="isOpen" class="modal-overlay" @click.self="handleClose">
    <div class="modal-card wizard-modal-card">
      <div class="modal-header">
        <h3 class="wizard-header-title">{{ t('wizard.title') }}</h3>
        <button class="close-btn" @click="handleClose">✕</button>
      </div>

      <div class="modal-body">
        <p class="wizard-desc">{{ t('wizard.desc') }}</p>

        <div v-if="errorMsg" class="easy-error-banner">
          ⚠️ {{ errorMsg }}
        </div>

        <!-- FORM CONTROLS -->
        <div class="wizard-form">
          <div class="form-item">
            <label>{{ t('wizard.channel') }}</label>
            <select v-model.number="targetChannel" :disabled="statusData.state === 'running'" class="form-input">
              <option :value="0">Main LR</option>
              <option v-for="b in 6" :key="b" :value="b">Bus {{ b.toString().padStart(2, '0') }}</option>
            </select>
          </div>

          <div class="form-item">
            <label>{{ t('wizard.maxBoost') }} (0.5 ~ +4.0 dB)</label>
            <input
              v-model.number="maxBoostDb"
              type="number"
              step="0.5"
              min="0.5"
              max="4.0"
              :disabled="statusData.state === 'running'"
              class="form-input"
            />
          </div>

          <div class="form-item">
            <label>{{ t('wizard.dwellTime') }} (1.0 ~ 10.0 s)</label>
            <input
              v-model.number="dwellTimeS"
              type="number"
              step="0.5"
              min="1.0"
              max="10.0"
              :disabled="statusData.state === 'running'"
              class="form-input"
            />
          </div>
        </div>

        <!-- STATUS PANEL -->
        <div :class="['status-box', statusData.state]">
          <div class="status-title">{{ t('wizard.status') }}: <b>{{ t(`wizard.${statusData.state || 'idle'}`) }}</b></div>
          <div class="status-metrics">
            <div>{{ t('wizard.gainAdded') }}: <b class="font-mono">{{ (statusData.current_gain_added ?? 0).toFixed(1) }} dB</b></div>
            <div>{{ t('wizard.detectedNotches') }}: <b class="font-mono text-cyan">{{ statusData.detected_notches ?? 0 }}</b></div>
          </div>
        </div>

        <!-- ACTION BUTTONS -->
        <div class="wizard-actions">
          <button
            v-if="statusData.state !== 'running'"
            class="start-btn"
            @click="handleStart"
          >
            {{ t('wizard.start') }}
          </button>
          <button
            v-else
            class="stop-btn"
            @click="handleStop"
          >
            {{ t('wizard.stop') }}
          </button>
        </div>
      </div>

      <div class="modal-footer">
        <button class="c-btn-secondary" @click="handleClose">{{ t('common.close') }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.wizard-modal-card {
  max-width: 540px;
}

.wizard-header-title {
  color: var(--accent-amber) !important;
}

.wizard-desc {
  font-size: 12px;
  color: var(--text-dim);
  line-height: 1.4;
}

.wizard-form {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 10px;
}

.form-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.form-item label {
  font-size: 11px;
  color: var(--text-dim);
}

.form-input {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  color: var(--text-main);
  padding: 6px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-family: var(--font-mono);
}

.status-box {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.status-box.running {
  border-color: var(--accent-amber);
  animation: pulse 2s infinite;
}

.status-box.completed {
  border-color: var(--accent-green);
}

.status-box.aborted {
  border-color: var(--accent-red);
}

@keyframes pulse {
  0%, 100% { border-color: rgba(245, 158, 11, 0.4); }
  50% { border-color: rgba(245, 158, 11, 1); }
}

.status-title {
  font-size: 13px;
}

.status-metrics {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: var(--text-dim);
}

.wizard-actions {
  display: flex;
  margin-top: 6px;
}

.start-btn {
  width: 100%;
  padding: 10px;
  background: var(--accent-cyan);
  color: #000;
  font-weight: 700;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
}

.stop-btn {
  width: 100%;
  padding: 10px;
  background: var(--panic-red);
  color: #fff;
  font-weight: 800;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
}
</style>
