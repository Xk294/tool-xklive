<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from 'vue'
import type {
  MixerConnectionStatus,
  WizardStartResult,
  WizardStopResult,
  WizardStatusSnapshot
} from '~/composables/useCompanionSocket'

const props = defineProps<{
  mixerStatus: MixerConnectionStatus
  isDemoMode: boolean
  currentPreset: string
  startWizard: (channel?: number, maxBoost?: number, dwellTime?: number) => Promise<WizardStartResult>
  stopWizard: () => Promise<WizardStopResult>
  getWizardStatus: () => Promise<WizardStatusSnapshot>
  takeSnapshot: () => Promise<void>
}>()

const emit = defineEmits<{
  (e: 'prevStep'): void
  (e: 'nextStep'): void
}>()

const selectedTarget = ref<number>(props.currentPreset === 'monitor' ? 1 : 0)
const isWizardRunning = ref(false)
const wizardProgress = ref<string>('Sẵn sàng')
const wizardBoostDb = ref<number>(0)
const wizardDetectedCount = ref<number>(0)
const wizardDetectedFreqs = ref<number[]>([])
const wizardError = ref<string>('')
let wizardPollTimer: ReturnType<typeof setInterval> | null = null

const wizardProgressPct = computed(() =>
  Math.min(100, Math.max(0, Math.round((wizardBoostDb.value / 3.0) * 100)))
)

function clearPollTimer() {
  if (wizardPollTimer) {
    clearInterval(wizardPollTimer)
    wizardPollTimer = null
  }
}

watch(
  () => props.mixerStatus,
  (status) => {
    if (isWizardRunning.value && !props.isDemoMode && (status === 'DISCONNECTED' || status === 'RECONNECTING')) {
      clearPollTimer()
      isWizardRunning.value = false
      wizardError.value = 'Mất kết nối với bàn mixer — Đã tự động dừng cân phòng để đảm bảo an toàn.'
      wizardProgress.value = 'Đã dừng cân phòng do mất kết nối'
      props.stopWizard().catch(() => {})
    }
  }
)

async function handleStartWizard() {
  wizardError.value = ''
  if (!props.isDemoMode && props.mixerStatus !== 'CONNECTED' && props.mixerStatus !== 'MOCK') {
    wizardError.value = 'Chưa kết nối tới bàn mixer. Vui lòng kết nối mixer hoặc bật chế độ Demo trước khi cân phòng.'
    return
  }

  isWizardRunning.value = true
  wizardProgress.value = 'Đang bắt đầu phát tín hiệu kiểm tra…'

  try {
    const res = await props.startWizard(selectedTarget.value, 3.0, 1.5)
    if (!res || res.success === false) {
      isWizardRunning.value = false
      wizardError.value = res?.detail || 'Không thể khởi động thuật toán cân phòng.'
      wizardProgress.value = 'Chưa thể bắt đầu cân phòng'
      return
    }
  } catch (err: unknown) {
    isWizardRunning.value = false
    wizardError.value = err instanceof Error ? err.message : String(err)
    wizardProgress.value = 'Lỗi khi bắt đầu cân phòng'
    return
  }

  clearPollTimer()
  wizardPollTimer = setInterval(async () => {
    if (!props.isDemoMode && (props.mixerStatus === 'DISCONNECTED' || props.mixerStatus === 'RECONNECTING')) {
      clearPollTimer()
      isWizardRunning.value = false
      wizardError.value = 'Mất kết nối mạng với mixer trong lúc cân phòng. Đã tự động dừng an toàn.'
      wizardProgress.value = 'Đã dừng cân phòng'
      return
    }

    try {
      const st = await props.getWizardStatus()
      if (!st) return
      wizardBoostDb.value = st.current_gain_added ?? 0
      wizardDetectedCount.value = st.detected_notches ?? 0
      if (Array.isArray(st.detected_frequencies)) {
        wizardDetectedFreqs.value = st.detected_frequencies
      }
      if (st.state === 'running' || st.state === 'paused') {
        wizardProgress.value = `Đang nhích thử +${wizardBoostDb.value.toFixed(1)} dB / +3.0 dB… đã xử lý ${wizardDetectedCount.value} điểm cộng hưởng`
      } else {
        isWizardRunning.value = false
        clearPollTimer()
        if (st.state === 'completed') {
          wizardBoostDb.value = 3.0
          wizardProgress.value = `Xong! Đã xử lý ${wizardDetectedCount.value} điểm hay hú và trả âm lượng về ban đầu.`
          await props.takeSnapshot()
        } else {
          wizardProgress.value = 'Đã dừng cân phòng và trả âm lượng về mức an toàn'
        }
      }
    } catch (err: unknown) {
      clearPollTimer()
      isWizardRunning.value = false
      wizardError.value = `Lỗi đọc trạng thái cân phòng: ${err instanceof Error ? err.message : String(err)}`
      wizardProgress.value = 'Đã dừng cân phòng do lỗi kết nối'
    }
  }, 1000)
}

async function handleStopWizard() {
  clearPollTimer()
  isWizardRunning.value = false
  await props.stopWizard()
  wizardProgress.value = 'Đã dừng cân phòng'
}

async function handleLeaveStep(target: 'prevStep' | 'nextStep') {
  if (isWizardRunning.value) {
    clearPollTimer()
    isWizardRunning.value = false
    await props.stopWizard().catch(() => {})
  }
  emit(target)
}

onUnmounted(() => {
  const wasRunning = isWizardRunning.value
  clearPollTimer()
  if (wasRunning) {
    isWizardRunning.value = false
    props.stopWizard().catch(() => {})
  }
})
</script>

<template>
  <section class="easy-step-card">
    <div class="easy-step-header">
      <h2>Bước 3: Cân Phòng (Tự Động Tìm Điểm Hay Hú)</h2>
      <p class="easy-step-desc">
        Hệ thống sẽ thử nghiệm nhẹ nhàng từng dải tần để phát hiện trước các tần số dội âm trong phòng và triệt tiêu trước khi mở màn.
      </p>
    </div>

    <div v-if="wizardError" class="easy-error-banner">
      ⚠️ {{ wizardError }}
    </div>

    <div class="wizard-box">
      <div class="wizard-target-row">
        <label for="easy-wizard-target" class="target-label">Chọn đường loa cần cân phòng:</label>
        <select
          id="easy-wizard-target"
          v-model.number="selectedTarget"
          :disabled="isWizardRunning"
          class="c-input target-select"
        >
          <option :value="0">Loa Chính Hội Trường (Main LR)</option>
          <option v-for="b in 6" :key="b" :value="b">Loa Kiểm Âm Sân Khấu (Monitor Bus {{ b }})</option>
        </select>
      </div>

      <div class="wizard-notice">
        <p class="notice-title">📢 Lưu ý trước khi bấm cân phòng:</p>
        <p>1. Hãy bật loa sân khấu ở mức âm lượng vừa phải (Trần tăng tối đa an toàn: +3.0 dB / giới hạn cứng +4.0 dB).</p>
        <p>2. Trong lúc cân, loa sẽ phát tiếng rít nhỏ vài giây để máy dò điểm cộng hưởng.</p>
        <p>3. Bạn có thể bấm "DỪNG NGAY" bất cứ lúc nào nếu thấy quá to.</p>
      </div>

      <div class="wizard-action-area">
        <button
          v-if="!isWizardRunning"
          type="button"
          class="btn-wizard-start"
          @click="handleStartWizard"
        >
          🔔 BẮT ĐẦU CÂN PHÒNG TỰ ĐỘNG
        </button>
        <button
          v-else
          type="button"
          class="btn-wizard-stop"
          @click="handleStopWizard"
        >
          ⏹️ DỪNG CÂN PHÒNG NGAY
        </button>

        <div class="wizard-status-display">
          <span class="wizard-status-text">{{ wizardProgress }}</span>
          <div v-if="isWizardRunning || wizardBoostDb > 0" class="wizard-progress-track">
            <div class="wizard-progress-fill" :style="{ width: `${wizardProgressPct}%` }" />
          </div>
          <div v-if="wizardDetectedFreqs.length > 0" class="wizard-detected-freqs">
            <span class="freqs-label">Đã ghim điểm cộng hưởng:</span>
            <span
              v-for="(f, idx) in wizardDetectedFreqs"
              :key="idx"
              class="freq-badge"
            >
              {{ Math.round(f) }} Hz
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- Navigation Buttons -->
    <div class="easy-step-nav-footer">
      <button type="button" class="easy-btn-secondary" @click="handleLeaveStep('prevStep')">
        ← Quay lại kiểm tra mic
      </button>
      <button type="button" class="easy-btn-primary-big" @click="handleLeaveStep('nextStep')">
        BƯỚC VÀO SHOW NGAY →
      </button>
    </div>
  </section>
</template>

<style scoped>
.wizard-box {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.wizard-target-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  background: var(--bg-secondary);
  padding: 12px 16px;
  border-radius: 8px;
  border: 1px solid var(--border-color);
}

.target-label {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-secondary);
}

.target-select {
  max-width: 320px;
}

.wizard-notice {
  background: rgba(56, 189, 248, 0.05);
  border: 1px solid rgba(56, 189, 248, 0.2);
  border-radius: 10px;
  padding: 18px 22px;
  font-size: 14px;
  color: var(--text-secondary);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.notice-title {
  color: var(--accent-cyan);
  font-weight: 800;
}

.wizard-action-area {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  padding: 30px 0;
}

.btn-wizard-start {
  background: linear-gradient(135deg, #10b981, #059669);
  color: #fff;
  font-weight: 900;
  font-size: 18px;
  border: none;
  border-radius: 12px;
  padding: 18px 36px;
  cursor: pointer;
  box-shadow: 0 6px 24px rgba(16, 185, 129, 0.4);
  transition: transform 0.15s ease;
}

.btn-wizard-start:hover {
  transform: scale(1.03);
}

.btn-wizard-stop {
  background: var(--accent-red);
  color: #fff;
  font-weight: 800;
  font-size: 16px;
  border: none;
  border-radius: 10px;
  padding: 16px 30px;
  cursor: pointer;
  animation: pulse-red 1s infinite;
}

@keyframes pulse-red {
  0%, 100% { box-shadow: 0 0 0 rgba(239, 68, 68, 0.5); }
  50% { box-shadow: 0 0 20px rgba(239, 68, 68, 0.8); }
}

.wizard-status-text {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-dim);
}

.wizard-status-display {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  width: 100%;
  max-width: 440px;
}

.wizard-progress-track {
  width: 100%;
  height: 10px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  overflow: hidden;
}

.wizard-progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--accent-cyan), var(--accent-green));
  transition: width 0.25s ease;
}

.wizard-detected-freqs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  justify-content: center;
  margin-top: 6px;
}

.freqs-label {
  font-size: 13px;
  color: var(--text-secondary);
}

.freq-badge {
  background: rgba(16, 185, 129, 0.15);
  color: var(--accent-green);
  border: 1px solid rgba(16, 185, 129, 0.35);
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 6px;
}
</style>
