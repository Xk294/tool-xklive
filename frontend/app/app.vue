<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useHead } from '#imports'
import { useI18n } from '~/composables/useI18n'
import { useCompanionSocket } from '~/composables/useCompanionSocket'
import EasyModeView from '~/components/EasyModeView.vue'
import StatusBar from '~/components/StatusBar.vue'
import PanicControl from '~/components/PanicControl.vue'
import RtaCanvas from '~/components/RtaCanvas.vue'
import MetersGrid from '~/components/MetersGrid.vue'
import ProposalsQueue from '~/components/ProposalsQueue.vue'
import NotchesTable from '~/components/NotchesTable.vue'
import SnapshotSection from '~/components/SnapshotSection.vue'
import EventLogBox from '~/components/EventLogBox.vue'
import DiagnosticsModal from '~/components/DiagnosticsModal.vue'
import WizardModal from '~/components/WizardModal.vue'
import DemoFeedbackModal from '~/components/DemoFeedbackModal.vue'
import DynamicsModal from '~/components/DynamicsModal.vue'
import ConnectModal from '~/components/ConnectModal.vue'
import SignalGeneratorModal from '~/components/SignalGeneratorModal.vue'

const { lang } = useI18n()

useHead({
  htmlAttrs: {
    lang: computed(() => lang.value)
  }
})

const viewMode = ref<'easy' | 'advanced'>('easy')

const {
  mixerStatus,
  isMockMode,
  dryRun,
  mixerModel,
  rttMs,
  dspLatencyMs,
  xruns,
  audioMode,
  currentMode,
  currentPreset,
  snapshotBandsCount,
  talkoverEnabled,
  talkoverIsDucked,
  talkoverMicChannel,
  clipAlerts,
  gainSessions,
  canUndoPanic,
  channels,
  activeNotches,
  pendingProposals,
  meters,
  rtaBins,
  peakHoldBins,
  eventLogs,
  setMode,
  setPreset,
  setTalkoverConfig,
  startGainCalibration,
  cancelGainCalibration,
  applyChannelHpf,
  applyManualNotch,
  toggleLiveDemo,
  toggleDryRun,
  triggerPanic,
  undoPanic,
  approveProposal,
  rejectProposal,
  snoozeProposal,
  releaseNotch,
  releaseChannelNotches,
  releaseAllNotches,
  takeSnapshot,
  rollbackSnapshot,
  triggerFakeFeedback,
  exportReport,
  fetchDiagnostics,
  fetchDynamicsSuggestions,
  startWizard,
  stopWizard,
  getWizardStatus,
  connectMixer,
  disconnectMixer,
  discoverMixers,
  listAudioDevices,
  startAudioCapture,
  stopAudioCapture,
  toggleLock,
  toggleWhitelist,
  clearLogs
} = useCompanionSocket()

const isDiagOpen = ref(false)
const isWizardOpen = ref(false)
const isDemoFeedbackOpen = ref(false)
const isDynamicsOpen = ref(false)
const isConnectOpen = ref(false)
const isSignalGenOpen = ref(false)
const selectedManualFreq = ref<number | null>(null)

function onSelectFreq(freq: number) {
  selectedManualFreq.value = freq
}

function handleKeyDown(e: KeyboardEvent) {
  const tag = (e.target as HTMLElement)?.tagName
  if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') {
    return
  }
  if (e.key === 'p' || e.key === 'P' || e.key === 'Escape') {
    triggerPanic()
  } else if (e.code === 'Space' && pendingProposals.value.length > 0) {
    e.preventDefault()
    const top = pendingProposals.value[0]
    if (top) {
      approveProposal(top.id)
    }
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeyDown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeyDown)
})
</script>

<template>
  <div class="app-root">
    <!-- EASY MODE VIEW (DEFAULT) -->
    <EasyModeView
      v-if="viewMode === 'easy'"
      :mixer-status="mixerStatus"
      :mixer-model="mixerModel"
      :is-mock-mode="isMockMode"
      :audio-mode="audioMode"
      :rtt-ms="rttMs"
      :current-mode="currentMode"
      :current-preset="currentPreset"
      :talkover-enabled="talkoverEnabled"
      :talkover-is-ducked="talkoverIsDucked"
      :talkover-mic-channel="talkoverMicChannel"
      :clip-alerts="clipAlerts"
      :gain-sessions="gainSessions"
      :can-undo-panic="canUndoPanic"
      :active-notches="activeNotches"
      :pending-proposals="pendingProposals"
      :meters="meters"
      :channels="channels"
      :event-logs="eventLogs"
      :connect-mixer="connectMixer"
      :disconnect-mixer="disconnectMixer"
      :discover-mixers="discoverMixers"
      :list-audio-devices="listAudioDevices"
      :set-mode="setMode"
      :set-preset="setPreset"
      :set-talkover-config="setTalkoverConfig"
      :start-gain-calibration="startGainCalibration"
      :cancel-gain-calibration="cancelGainCalibration"
      :apply-channel-hpf="applyChannelHpf"
      :toggle-whitelist="toggleWhitelist"
      :release-channel-notches="releaseChannelNotches"
      :start-wizard="startWizard"
      :stop-wizard="stopWizard"
      :get-wizard-status="getWizardStatus"
      :take-snapshot="takeSnapshot"
      :trigger-panic="triggerPanic"
      :undo-panic="undoPanic"
      :approve-proposal="approveProposal"
      :reject-proposal="rejectProposal"
      :trigger-fake-feedback="triggerFakeFeedback"
      :toggle-live-demo="toggleLiveDemo"
      :export-report="exportReport"
      :start-audio-capture="startAudioCapture"
      @switch-to-advanced="viewMode = 'advanced'"
    />

    <!-- ADVANCED PRO STUDIO DASHBOARD -->
    <template v-else>
      <div class="advanced-banner">
        <span>⚙️ ĐANG Ở CHẾ ĐỘ KỸ THUẬT CHUYÊN SÂU (PRO DASHBOARD)</span>
        <button
          type="button"
          class="btn-return-easy"
          @click="viewMode = 'easy'"
        >
          ← Quay Lại Chế Độ Đơn Giản (Easy Mode)
        </button>
      </div>

      <!-- TOP STICKY STATUS BAR -->
      <StatusBar
        :mixer-status="mixerStatus"
        :is-mock-mode="isMockMode"
        :dry-run="dryRun"
        :mixer-model="mixerModel"
        :rtt-ms="rttMs"
        :dsp-latency-ms="dspLatencyMs"
        :xruns="xruns"
        :current-mode="currentMode"
        :current-preset="currentPreset"
        @set-mode="setMode"
        @set-preset="setPreset"
        @toggle-dry-run="toggleDryRun()"
        @open-diagnostics="isDiagOpen = true"
        @open-wizard="isWizardOpen = true"
        @open-demo-feedback="isDemoFeedbackOpen = true"
        @open-dynamics="isDynamicsOpen = true"
        @open-connect="isConnectOpen = true"
        @open-signal-gen="isSignalGenOpen = true"
      >
        <template #panic>
          <PanicControl
            @panic="triggerPanic"
            @undo="undoPanic"
          />
        </template>
      </StatusBar>

      <!-- MAIN DASHBOARD -->
    <main class="dashboard">
      <!-- LEFT COLUMN -->
      <div class="dash-left">
        <!-- REAL-TIME RTA SPECTRUM / WATERFALL -->
        <RtaCanvas
          :rta-bins="rtaBins"
          :peak-hold-bins="peakHoldBins"
          :active-notches="activeNotches"
          @select-freq="onSelectFreq"
        />

        <!-- MIC LEVEL METERS -->
        <MetersGrid
          :mixer-model="mixerModel"
          :meters="meters"
          :channels="channels"
          @toggle-lock="toggleLock"
        />

        <!-- ACTIVE NOTCH FILTERS & MANUAL INJECTOR -->
        <NotchesTable
          :mixer-model="mixerModel"
          :notches="activeNotches"
          :selected-freq="selectedManualFreq"
          @release="releaseNotch"
          @release-all="releaseAllNotches"
          @export="exportReport"
          @apply-manual-notch="applyManualNotch"
        />
      </div>

      <!-- RIGHT COLUMN -->
      <div class="dash-right">
        <!-- FEEDBACK PROPOSALS QUEUE -->
        <ProposalsQueue
          :proposals="pendingProposals"
          @approve="approveProposal"
          @reject="rejectProposal"
          @snooze="snoozeProposal"
        />

        <!-- PEQ SNAPSHOT & ROLLBACK -->
        <SnapshotSection
          :snapshot-bands-count="snapshotBandsCount"
          @take="takeSnapshot"
          @rollback="rollbackSnapshot"
        />

        <!-- SYSTEM EVENT LOG -->
        <EventLogBox
          :logs="eventLogs"
          @clear="clearLogs"
        />
      </div>
    </main>

    <!-- MODALS -->
    <SignalGeneratorModal
      v-if="isSignalGenOpen"
      :is-open="isSignalGenOpen"
      @close="isSignalGenOpen = false"
    />

    <DiagnosticsModal
      v-if="isDiagOpen"
      :is-open="isDiagOpen"
      :fetch-diagnostics="fetchDiagnostics"
      @close="isDiagOpen = false"
    />

    <WizardModal
      v-if="isWizardOpen"
      :is-open="isWizardOpen"
      :start-wizard="startWizard"
      :stop-wizard="stopWizard"
      :get-wizard-status="getWizardStatus"
      @close="isWizardOpen = false"
    />

    <DemoFeedbackModal
      v-if="isDemoFeedbackOpen"
      :is-open="isDemoFeedbackOpen"
      :trigger-feedback="triggerFakeFeedback"
      @close="isDemoFeedbackOpen = false"
    />

    <DynamicsModal
      v-if="isDynamicsOpen"
      :is-open="isDynamicsOpen"
      :fetch-dynamics="fetchDynamicsSuggestions"
      @close="isDynamicsOpen = false"
    />

    <ConnectModal
      v-if="isConnectOpen"
      :is-open="isConnectOpen"
      :mixer-status="mixerStatus"
      :mixer-model="mixerModel"
      :connect-mixer="connectMixer"
      :disconnect-mixer="disconnectMixer"
      :discover-mixers="discoverMixers"
      :list-audio-devices="listAudioDevices"
      :start-audio-capture="startAudioCapture"
      :stop-audio-capture="stopAudioCapture"
      @close="isConnectOpen = false"
    />
    </template>
  </div>
</template>

<style scoped>
.app-root {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background-color: var(--bg-primary);
  background-image: radial-gradient(circle at 50% 0%, rgba(56, 189, 248, 0.04) 0%, transparent 60%);
}

.advanced-banner {
  background: rgba(245, 158, 11, 0.15);
  border-bottom: 1px solid var(--accent-amber);
  color: #fbbf24;
  padding: 8px 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  font-weight: 700;
}

.btn-return-easy {
  background: var(--accent-cyan);
  color: #000;
  border: none;
  font-weight: 800;
  font-size: 12px;
  padding: 6px 14px;
  border-radius: 6px;
  cursor: pointer;
  transition: transform 0.1s ease;
}

.btn-return-easy:hover {
  transform: scale(1.03);
}

main.dashboard {
  display: grid;
  grid-template-columns: 1fr 380px;
  gap: 12px;
  padding: 12px 16px;
  max-width: 1920px;
  width: 100%;
  margin: 0 auto;
  flex: 1;
}

.dash-left {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

.dash-right {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

@media (max-width: 1200px) {
  main.dashboard {
    grid-template-columns: 1fr;
  }
}
</style>
