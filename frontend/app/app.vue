<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useCompanionSocket } from '~/composables/useCompanionSocket'
import StatusBar from '~/components/StatusBar.vue'
import PanicControl from '~/components/PanicControl.vue'
import RtaCanvas from '~/components/RtaCanvas.vue'
import MetersGrid from '~/components/MetersGrid.vue'
import ProposalsQueue from '~/components/ProposalsQueue.vue'
import NotchesTable from '~/components/NotchesTable.vue'
import SnapshotSection from '~/components/SnapshotSection.vue'
import EventLogBox from '~/components/EventLogBox.vue'

const {
  mixerStatus,
  mixerModel,
  latencyMs,
  xruns,
  isLanRta,
  currentMode,
  activeNotches,
  pendingProposals,
  meters,
  rtaBins,
  peakHoldBins,
  eventLogs,
  setMode,
  triggerPanic,
  undoPanic,
  approveProposal,
  rejectProposal,
  snoozeProposal,
  releaseNotch,
  releaseAllNotches,
  takeSnapshot,
  rollbackSnapshot,
  clearLogs
} = useCompanionSocket()

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
      :mixer-model="mixerModel"
      :latency-ms="latencyMs"
      :xruns="xruns"
      :is-lan-rta="isLanRta"
      :current-mode="currentMode"
      @set-mode="setMode"
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

        <MetersGrid :meters="meters" />

        <NotchesTable
          :notches="activeNotches"
          @release="releaseNotch"
          @release-all="releaseAllNotches"
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
