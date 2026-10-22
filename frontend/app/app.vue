<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useHead } from '#imports'
import { useI18n } from '~/composables/useI18n'
import { useCompanionSocket } from '~/composables/useCompanionSocket'
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

const { lang } = useI18n()

useHead({
  htmlAttrs: {
    lang: computed(() => lang.value)
  }
})

const {
  mixerStatus,
  isMockMode,
  dryRun,
  mixerModel,
  latencyMs,
  rttMs,
  dspLatencyMs,
  xruns,
  isLanRta,
  currentMode,
  channels,
  activeNotches,
  pendingProposals,
  meters,
  rtaBins,
  peakHoldBins,
  eventLogs,
  setMode,
  toggleDryRun,
  triggerPanic,
  undoPanic,
  approveProposal,
  rejectProposal,
  snoozeProposal,
  releaseNotch,
  undoNotch,
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
  clearLogs
} = useCompanionSocket()

const isDiagOpen = ref(false)
const isWizardOpen = ref(false)
const isDemoFeedbackOpen = ref(false)
const isDynamicsOpen = ref(false)

function handleKeyDown(e: KeyboardEvent) {
  if (e.key === 'p' || e.key === 'P' || e.key === 'Escape') {
    triggerPanic()
  } else if (e.code === 'Space' && pendingProposals.value.length > 0) {
    e.preventDefault()
    approveProposal(pendingProposals.value[0].id)
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
    <!-- TOP STICKY STATUS BAR -->
    <StatusBar
      :mixer-status="mixerStatus"
      :is-mock-mode="isMockMode"
      :dry-run="dryRun"
      :mixer-model="mixerModel"
      :rtt-ms="rttMs"
      :dsp-latency-ms="dspLatencyMs"
      :latency-ms="latencyMs"
      :xruns="xruns"
      :is-lan-rta="isLanRta"
      :current-mode="currentMode"
      @set-mode="setMode"
      @toggle-dry-run="toggleDryRun()"
      @open-diagnostics="isDiagOpen = true"
      @open-wizard="isWizardOpen = true"
      @open-demo-feedback="isDemoFeedbackOpen = true"
      @open-dynamics="isDynamicsOpen = true"
    >
      <template #panic>
        <PanicControl
          :has-active-notches="activeNotches.length > 0"
          @panic="triggerPanic"
          @undo="undoPanic"
        />
      </template>
    </StatusBar>

    <!-- MAIN DASHBOARD -->
    <main class="dashboard">
      <!-- LEFT COLUMN -->
      <div class="dash-left">
        <RtaCanvas
          :rta-bins="rtaBins"
          :peak-hold-bins="peakHoldBins"
          :active-notches="activeNotches"
        />

        <MetersGrid
          :meters="meters"
          :channels="channels"
        />

        <NotchesTable
          :notches="activeNotches"
          @release="releaseNotch"
          @undo="undoNotch"
          @release-all="releaseAllNotches"
          @export="exportReport"
        />
      </div>

      <!-- RIGHT COLUMN -->
      <div class="dash-right">
        <ProposalsQueue
          :proposals="pendingProposals"
          @approve="approveProposal"
          @reject="rejectProposal"
          @snooze="snoozeProposal"
        />

        <SnapshotSection
          @take="takeSnapshot"
          @rollback="rollbackSnapshot"
        />

        <EventLogBox
          :logs="eventLogs"
          @clear="clearLogs"
        />
      </div>
    </main>

    <!-- MODALS -->
    <DiagnosticsModal
      :is-open="isDiagOpen"
      :fetch-diagnostics="fetchDiagnostics"
      @close="isDiagOpen = false"
    />

    <WizardModal
      :is-open="isWizardOpen"
      :start-wizard="startWizard"
      :stop-wizard="stopWizard"
      :get-wizard-status="getWizardStatus"
      @close="isWizardOpen = false"
    />

    <DemoFeedbackModal
      :is-open="isDemoFeedbackOpen"
      :trigger-feedback="triggerFakeFeedback"
      @close="isDemoFeedbackOpen = false"
    />

    <DynamicsModal
      :is-open="isDynamicsOpen"
      :fetch-dynamics="fetchDynamicsSuggestions"
      @close="isDynamicsOpen = false"
    />
  </div>
</template>

<style scoped>
.app-root {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

main.dashboard {
  display: grid;
  grid-template-columns: 1fr 340px;
  gap: 16px;
  padding: 16px;
  max-width: 1600px;
  width: 100%;
  margin: 0 auto;
}

@media (max-width: 1024px) {
  main.dashboard {
    grid-template-columns: 1fr;
  }
}
</style>
