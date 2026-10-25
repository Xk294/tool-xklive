<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { getFriendlyStatus } from '~/utils/eventTranslator'
import type {
  MixerConnectionStatus,
  OperationMode,
  Proposal,
  ChannelInfo,
  ActiveNotch,
  LogEntry,
  DiscoveredMixer,
  AudioDeviceItem,
  WizardStartResult,
  WizardStopResult,
  WizardStatusSnapshot,
  ClipAlert,
  GainCalibrationSession
} from '~/composables/useCompanionSocket'
import EasyStepConnect from '~/components/easy/EasyStepConnect.vue'
import EasyStepMicCheck from '~/components/easy/EasyStepMicCheck.vue'
import EasyStepWizard from '~/components/easy/EasyStepWizard.vue'
import EasyStepLiveShow from '~/components/easy/EasyStepLiveShow.vue'
import EasyShowReportModal from '~/components/easy/EasyShowReportModal.vue'

interface Props {
  mixerStatus: MixerConnectionStatus
  mixerModel: string
  isMockMode: boolean
  audioMode?: 'usb' | 'lan_rta' | 'none'
  rttMs?: number | null
  currentMode: OperationMode
  currentPreset: string
  talkoverEnabled?: boolean
  talkoverIsDucked?: boolean
  talkoverMicChannel?: number
  clipAlerts?: ClipAlert[]
  gainSessions?: Record<number, GainCalibrationSession>
  canUndoPanic?: boolean
  activeNotches: ActiveNotch[]
  pendingProposals: Proposal[]
  meters: number[]
  channels: ChannelInfo[]
  eventLogs: LogEntry[]
  connectMixer: (ip: string, port?: number) => Promise<boolean>
  disconnectMixer?: () => Promise<void>
  discoverMixers: () => Promise<DiscoveredMixer[]>
  listAudioDevices?: () => Promise<AudioDeviceItem[]>
  setMode: (mode: OperationMode) => Promise<void>
  setPreset: (preset: string) => Promise<void>
  setTalkoverConfig?: (enabled: boolean, micChannel?: number, fxReturn?: number) => Promise<void>
  startGainCalibration?: (channel: number) => Promise<GainCalibrationSession | undefined>
  cancelGainCalibration?: (channel: number) => Promise<void>
  applyChannelHpf?: (channel: number, enabled: boolean, freqHz?: number) => Promise<boolean>
  toggleWhitelist?: (channel: number) => Promise<boolean>
  releaseChannelNotches?: (channel: number) => Promise<void>
  startWizard: (channel?: number, maxBoost?: number, dwellTime?: number) => Promise<WizardStartResult>
  stopWizard: () => Promise<WizardStopResult>
  getWizardStatus: () => Promise<WizardStatusSnapshot>
  takeSnapshot: () => Promise<void>
  triggerPanic: () => Promise<void>
  undoPanic: () => Promise<void>
  approveProposal: (id: string) => Promise<void>
  rejectProposal: (id: string) => Promise<void>
  triggerFakeFeedback: (channel?: number, freqHz?: number, gain?: number) => Promise<void>
  toggleLiveDemo?: (forceEnable?: boolean) => Promise<void>
  exportReport: (format?: 'csv' | 'json') => Promise<void>
  startAudioCapture: (deviceName?: string) => Promise<boolean>
}

const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'switch-to-advanced'): void
}>()

const isDemo = ref(false)
const isDemoActive = computed(() => props.isMockMode || props.mixerStatus === 'MOCK' || isDemo.value)
const effectiveMixerStatus = computed<MixerConnectionStatus>(() =>
  isDemoActive.value && props.mixerStatus === 'DISCONNECTED' ? 'MOCK' : props.mixerStatus
)
const canEnterLaterSteps = computed(
  () => effectiveMixerStatus.value === 'CONNECTED' || effectiveMixerStatus.value === 'MOCK'
)

// Current Step: 1 = Kết nối, 2 = Kiểm tra Mic, 3 = Cân phòng, 4 = Đang chạy show
const currentStep = ref<number>(1)
const isScanning = ref(false)
const discoveredMixersList = ref<DiscoveredMixer[]>([])
const audioDevicesList = ref<AudioDeviceItem[]>([])
const selectedAudioDevice = ref<string>('')
const connectingIp = ref<string | null>(null)
const connectError = ref<string>('')

// Step 4 Show State & Alerts
const lastFeedbackInfo = ref<{ channel: number; freq_hz: number; target?: string; bus?: number | null } | null>(null)
let recentFeedbackTimer: ReturnType<typeof setTimeout> | null = null
const showReportModal = ref(false)
const showDurationMinutes = ref(0)
let showStartTime: number | null = null
const hadConnectionDrop = ref(false)

// Logo click counter for secret technician access
const logoClickCount = ref(0)
let logoClickResetTimer: ReturnType<typeof setTimeout> | null = null

function onLogoClick() {
  logoClickCount.value += 1
  if (logoClickResetTimer) clearTimeout(logoClickResetTimer)
  if (logoClickCount.value >= 5) {
    logoClickCount.value = 0
    emit('switch-to-advanced')
  } else {
    logoClickResetTimer = setTimeout(() => {
      logoClickCount.value = 0
    }, 2000)
  }
}

watch(currentStep, (step) => {
  if (step === 4 && showStartTime === null) {
    showStartTime = Date.now()
    hadConnectionDrop.value = false
  }
})

watch(
  () => props.mixerStatus,
  (newStatus, oldStatus) => {
    if (
      currentStep.value === 4
      && !isDemoActive.value
      && oldStatus === 'CONNECTED'
      && (newStatus === 'DISCONNECTED' || newStatus === 'RECONNECTING')
    ) {
      hadConnectionDrop.value = true
    }
  }
)

watch(
  () => props.activeNotches.length,
  (newLen, oldLen) => {
    if (newLen > oldLen && props.activeNotches.length > 0) {
      const latest = props.activeNotches[props.activeNotches.length - 1]
      if (!latest) return
      lastFeedbackInfo.value = {
        channel: latest.channel,
        freq_hz: latest.freq_hz,
        target: latest.target,
        bus: latest.bus
      }
      if (recentFeedbackTimer) clearTimeout(recentFeedbackTimer)
      recentFeedbackTimer = setTimeout(() => {
        lastFeedbackInfo.value = null
      }, 12000)
    }
  }
)

const friendlyStatus = computed(() =>
  getFriendlyStatus(
    effectiveMixerStatus.value,
    lastFeedbackInfo.value !== null,
    props.activeNotches.length,
    lastFeedbackInfo.value
  )
)

const audioModeBadgeText = computed(() => {
  if (isDemoActive.value) return '🎮 Demo'
  if (props.audioMode === 'usb') return '🔌 USB Đa Kênh'
  if (props.audioMode === 'lan_rta') return '🌐 LAN RTA'
  return ''
})

async function runDiscovery() {
  isScanning.value = true
  connectError.value = ''
  try {
    const [list, devs] = await Promise.all([
      props.discoverMixers(),
      props.listAudioDevices ? props.listAudioDevices() : Promise.resolve([])
    ])
    discoveredMixersList.value = list || []
    audioDevicesList.value = devs || []
  } catch (err) {
    console.error('Scan error', err)
    discoveredMixersList.value = []
  } finally {
    isScanning.value = false
  }
}

async function handleConnect(ip: string, modelName?: string, deviceName?: string) {
  connectingIp.value = ip
  connectError.value = ''
  if (deviceName !== undefined) {
    selectedAudioDevice.value = deviceName
  }
  const ok = await props.connectMixer(ip)
  connectingIp.value = null
  if (ok || props.mixerStatus === 'CONNECTED') {
    isDemo.value = false
    showStartTime = null
    hadConnectionDrop.value = false
    localStorage.setItem('xklive_last_mixer_ip', ip)
    if (modelName) {
      localStorage.setItem('xklive_last_mixer_model', modelName)
    }
    currentStep.value = 2
    const targetAudioDev = selectedAudioDevice.value.trim() || undefined
    props.startAudioCapture(targetAudioDev).catch(() => {})
  } else {
    connectError.value = `Không thể kết nối đến bàn mixer tại địa chỉ ${ip}. Vui lòng kiểm tra lại dây mạng hoặc Wi-Fi.`
  }
}

async function handleStartDemo() {
  if (props.mixerStatus === 'CONNECTED' && props.disconnectMixer) {
    await props.disconnectMixer().catch(() => {})
  }
  isDemo.value = true
  connectError.value = ''
  if (showStartTime === null) {
    showStartTime = Date.now()
  }
  currentStep.value = 4
  if (props.toggleLiveDemo) {
    await props.toggleLiveDemo(true)
  } else {
    await props.triggerFakeFeedback().catch(() => {})
  }
}

async function handlePanicClick() {
  await props.triggerPanic()
}

async function handleUndoPanicClick() {
  await props.undoPanic()
}

function handleEndShow() {
  const start = showStartTime ?? Date.now()
  const elapsedMs = Math.max(0, Date.now() - start)
  showDurationMinutes.value = Math.max(1, Math.round(elapsedMs / 60000))
  showReportModal.value = true
}

onMounted(async () => {
  const savedIp = localStorage.getItem('xklive_last_mixer_ip')
  const savedPreset = localStorage.getItem('xklive_last_preset')
  if (savedPreset) {
    props.setPreset(savedPreset).catch(() => {})
  }

  await runDiscovery()

  const matched = savedIp ? discoveredMixersList.value.find(m => m.ip === savedIp) : undefined
  if (matched) {
    await handleConnect(matched.ip, matched.model)
  } else if (props.mixerStatus === 'CONNECTED') {
    currentStep.value = 2
  }
})

onUnmounted(() => {
  if (recentFeedbackTimer) clearTimeout(recentFeedbackTimer)
  if (logoClickResetTimer) clearTimeout(logoClickResetTimer)
})
</script>

<template>
  <div class="easy-container">
    <!-- TOP HEADER -->
    <header class="easy-header">
      <div class="easy-brand" title="Bấm 5 lần để mở giao diện kỹ thuật chuyên sâu" @click="onLogoClick">
        <div class="easy-logo-badge">XK</div>
        <div>
          <h1 class="easy-title">Trợ Lý Âm Thanh Chống Hú</h1>
          <p class="easy-subtitle">Cắm vào mixer · Bấm 1 nút · Hết hú</p>
        </div>
      </div>

      <!-- 4-STEP PROGRESS BAR -->
      <nav class="easy-stepper" aria-label="Tiến trình thiết lập">
        <button
          type="button"
          class="step-item"
          :class="{ active: currentStep === 1, completed: currentStep > 1 }"
          @click="currentStep = 1"
        >
          <span class="step-num">1</span>
          <span class="step-text">Kết nối</span>
        </button>
        <span class="step-line" :class="{ filled: currentStep > 1 }" />

        <button
          type="button"
          class="step-item"
          :class="{ active: currentStep === 2, completed: currentStep > 2 }"
          :disabled="!canEnterLaterSteps"
          @click="currentStep = 2"
        >
          <span class="step-num">2</span>
          <span class="step-text">Kiểm tra mic</span>
        </button>
        <span class="step-line" :class="{ filled: currentStep > 2 }" />

        <button
          type="button"
          class="step-item"
          :class="{ active: currentStep === 3, completed: currentStep > 3 }"
          :disabled="!canEnterLaterSteps"
          @click="currentStep = 3"
        >
          <span class="step-num">3</span>
          <span class="step-text">Cân phòng</span>
        </button>
        <span class="step-line" :class="{ filled: currentStep > 3 }" />

        <button
          type="button"
          class="step-item"
          :class="{ active: currentStep === 4, completed: currentStep === 4 }"
          :disabled="!canEnterLaterSteps"
          @click="currentStep = 4"
        >
          <span class="step-num">4</span>
          <span class="step-text">Đang chạy show</span>
        </button>
      </nav>

      <!-- QUICK STATUS BADGE -->
      <div class="easy-top-status">
        <span
          class="status-dot"
          :class="{
            'dot-green': friendlyStatus.color === 'green',
            'dot-amber': friendlyStatus.color === 'amber',
            'dot-red': friendlyStatus.color === 'red'
          }"
        />
        <span class="status-name">{{ isDemoActive ? 'XR18 (Demo)' : (props.mixerModel || 'Chưa nối mixer') }}</span>
        <span v-if="audioModeBadgeText" class="audio-mode-pill">{{ audioModeBadgeText }}</span>
        <span v-if="props.rttMs !== null && props.rttMs !== undefined" class="rtt-pill">{{ Math.round(props.rttMs) }}ms</span>
      </div>
    </header>

    <!-- MOCK MODE BANNER -->
    <div v-if="isDemoActive" class="demo-banner">
      ⚠️ ĐANG CHẠY THỬ NGHIỆM (DEMO) — Chưa nối mixer thật. Mọi thao tác đều an toàn.
    </div>

    <!-- MAIN STEP CONTENT -->
    <main class="easy-main">
      <EasyStepConnect
        v-if="currentStep === 1"
        :is-scanning="isScanning"
        :discovered-mixers="discoveredMixersList"
        :audio-devices="audioDevicesList"
        :selected-audio-device="selectedAudioDevice"
        :connecting-ip="connectingIp"
        :connect-error="connectError"
        @scan="runDiscovery"
        @connect="handleConnect"
        @select-audio-device="selectedAudioDevice = $event"
        @start-demo="handleStartDemo"
      />

      <EasyStepMicCheck
        v-else-if="currentStep === 2"
        :mixer-model="props.mixerModel"
        :current-preset="props.currentPreset"
        :meters="props.meters"
        :channels="props.channels"
        :gain-sessions="props.gainSessions || {}"
        @set-preset="props.setPreset"
        @toggle-whitelist="(ch) => props.toggleWhitelist?.(ch)"
        @apply-channel-hpf="(ch, en, f) => props.applyChannelHpf?.(ch, en, f)"
        @start-gain-calibration="(ch) => props.startGainCalibration?.(ch)"
        @cancel-gain-calibration="(ch) => props.cancelGainCalibration?.(ch)"
        @prev-step="currentStep = 1"
        @skip-to-show="currentStep = 4"
        @next-step="currentStep = 3"
      />

      <EasyStepWizard
        v-else-if="currentStep === 3"
        :mixer-status="effectiveMixerStatus"
        :is-demo-mode="isDemoActive"
        :current-preset="props.currentPreset"
        :start-wizard="props.startWizard"
        :stop-wizard="props.stopWizard"
        :get-wizard-status="props.getWizardStatus"
        :take-snapshot="props.takeSnapshot"
        @prev-step="currentStep = 2"
        @next-step="currentStep = 4"
      />

      <EasyStepLiveShow
        v-else-if="currentStep === 4"
        :friendly-status="friendlyStatus"
        :mixer-model="props.mixerModel"
        :current-mode="props.currentMode"
        :active-notches="props.activeNotches"
        :pending-proposals="props.pendingProposals"
        :channels="props.channels"
        :meters="props.meters"
        :clip-alerts="props.clipAlerts || []"
        :talkover-enabled="!!props.talkoverEnabled"
        :talkover-is-ducked="!!props.talkoverIsDucked"
        :talkover-mic-channel="props.talkoverMicChannel || 1"
        :event-logs="props.eventLogs"
        :can-undo-panic="!!props.canUndoPanic"
        @panic="handlePanicClick"
        @undo-panic="handleUndoPanicClick"
        @set-mode="props.setMode"
        @set-talkover-config="(en, ch) => props.setTalkoverConfig?.(en, ch)"
        @toggle-whitelist="(ch) => props.toggleWhitelist?.(ch)"
        @release-channel-notches="(ch) => props.releaseChannelNotches?.(ch)"
        @approve-proposal="props.approveProposal"
        @reject-proposal="props.rejectProposal"
        @end-show="handleEndShow"
      />
    </main>

    <!-- FOOTER WITH TECHNICIAN ACCESS -->
    <footer class="easy-footer">
      <span>Auto Sound Engineer · Bảo vệ âm thanh trực tiếp</span>
      <button
        type="button"
        class="technician-link"
        @click="emit('switch-to-advanced')"
      >
        🛠️ Chế độ kỹ thuật chuyên sâu (Dành cho Pro Soundman)
      </button>
    </footer>

    <!-- SHOW REPORT MODAL -->
    <EasyShowReportModal
      :is-open="showReportModal"
      :show-duration-minutes="showDurationMinutes"
      :active-notches-count="props.activeNotches.length"
      :mixer-model="props.mixerModel"
      :mixer-status="effectiveMixerStatus"
      :is-demo-mode="isDemoActive"
      :had-connection-drop="hadConnectionDrop"
      @export="props.exportReport"
      @close="showReportModal = false"
    />
  </div>
</template>

<style scoped>
.easy-container {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background-color: var(--bg-primary);
  background-image: radial-gradient(circle at 50% 0%, rgba(56, 189, 248, 0.06) 0%, transparent 70%);
  color: var(--text-main);
  font-family: var(--font-sans);
}

.easy-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 24px;
  background: rgba(13, 18, 26, 0.9);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border-color);
  gap: 16px;
  flex-wrap: wrap;
}

.easy-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
  user-select: none;
}

.easy-logo-badge {
  width: 40px;
  height: 40px;
  border-radius: 8px;
  background: linear-gradient(135deg, var(--accent-cyan), #0284c7);
  color: #fff;
  font-weight: 900;
  font-size: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 0 16px rgba(56, 189, 248, 0.4);
}

.easy-title {
  font-size: 16px;
  font-weight: 800;
  letter-spacing: -0.3px;
  margin: 0;
}

.easy-subtitle {
  font-size: 12px;
  color: var(--text-dim);
  margin: 0;
}

.easy-stepper {
  display: flex;
  align-items: center;
  gap: 8px;
}

.step-item {
  display: flex;
  align-items: center;
  gap: 6px;
  background: none;
  border: 1px solid transparent;
  padding: 6px 12px;
  border-radius: 20px;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  transition: all 0.2s ease;
}

.step-item:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.step-num {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
}

.step-item.active {
  background: rgba(56, 189, 248, 0.12);
  border-color: var(--accent-cyan);
  color: var(--accent-cyan);
}

.step-item.active .step-num {
  background: var(--accent-cyan);
  color: #000;
  font-weight: 800;
  border-color: var(--accent-cyan);
}

.step-item.completed {
  color: var(--text-secondary);
}

.step-item.completed .step-num {
  background: var(--accent-green);
  color: #000;
  font-weight: 800;
  border-color: var(--accent-green);
}

.step-line {
  width: 24px;
  height: 2px;
  background: var(--border-color);
}

.step-line.filled {
  background: var(--accent-green);
}

.easy-top-status {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 20px;
  font-size: 12px;
  font-weight: 600;
}

.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.dot-green {
  background: var(--accent-green);
  box-shadow: 0 0 8px var(--accent-green);
}

.dot-amber {
  background: var(--accent-amber);
  box-shadow: 0 0 8px var(--accent-amber);
}

.dot-red {
  background: var(--accent-red);
  box-shadow: 0 0 8px var(--accent-red);
}

.audio-mode-pill {
  background: rgba(56, 189, 248, 0.14);
  color: var(--accent-cyan);
  border: 1px solid rgba(56, 189, 248, 0.35);
  border-radius: 12px;
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 700;
}

.rtt-pill {
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: 11px;
}

.demo-banner {
  background: rgba(245, 158, 11, 0.2);
  border-bottom: 1px solid var(--accent-amber);
  color: #fef08a;
  text-align: center;
  padding: 8px 16px;
  font-weight: 700;
  font-size: 13px;
}

.easy-main {
  flex: 1;
  max-width: 1100px;
  width: 100%;
  margin: 0 auto;
  padding: 24px 20px;
  display: flex;
  flex-direction: column;
}

.easy-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 24px;
  font-size: 12px;
  color: var(--text-muted);
  border-top: 1px solid var(--border-color);
  flex-wrap: wrap;
  gap: 12px;
}

.technician-link {
  background: none;
  border: none;
  color: var(--accent-cyan);
  font-size: 12px;
  cursor: pointer;
  text-decoration: underline;
}
</style>
