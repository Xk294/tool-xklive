<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from '~/composables/useI18n'
import type { MixerConnectionStatus } from '~/composables/useCompanionSocket'

const { lang, setLang, t } = useI18n()

const props = defineProps<{
  mixerStatus: MixerConnectionStatus
  isMockMode: boolean
  dryRun: boolean
  mixerModel: string
  rttMs: number | null
  dspLatencyMs: number
  xruns: number
  currentMode: 'auto' | 'semi' | 'manual'
  currentPreset?: string
}>()

const emit = defineEmits<{
  (e: 'setMode', mode: 'auto' | 'semi' | 'manual'): void
  (e: 'setPreset', preset: string): void
  (e: 'toggleDryRun'): void
  (e: 'openDiagnostics'): void
  (e: 'openWizard'): void
  (e: 'openDemoFeedback'): void
  (e: 'openDynamics'): void
  (e: 'openConnect'): void
  (e: 'openSignalGen'): void
}>()

const selectedPreset = ref(props.currentPreset || 'monitor')

watch(
  () => props.currentPreset,
  (val) => {
    if (val) {
      selectedPreset.value = val
    }
  }
)

function onPresetChange(e: Event) {
  const target = e.target as HTMLSelectElement
  selectedPreset.value = target.value
  emit('setPreset', target.value)
}
</script>

<template>
  <header class="status-bar">
    <!-- ROW 1: TELEMETRY & SYSTEM HARDWARE -->
    <div class="bar-row bar-top">
      <div class="row-left">
        <!-- BRAND -->
        <div class="brand-wrapper" :title="t('header.title')">
          <div class="brand">⚡ {{ t('header.brand') }}</div>
          <div class="brand-sub">{{ t('header.subtitle') }}</div>
        </div>

        <!-- CONNECTION BADGE -->
        <button
          v-if="isMockMode"
          type="button"
          class="badge mock cursor-pointer"
          :title="t('connection.mock')"
          @click="emit('openConnect')"
        >
          <span class="pulse-dot" />
          <span>{{ t('connection.mock') }}</span>
        </button>
        <button
          v-else
          type="button"
          :class="['badge', mixerStatus.toLowerCase(), 'cursor-pointer']"
          :title="t('connection.' + mixerStatus.toLowerCase())"
          @click="emit('openConnect')"
        >
          <span class="pulse-dot" />
          <span>{{ t(`connection.${mixerStatus.toLowerCase()}`) }}</span>
        </button>

        <!-- DRY RUN BADGE -->
        <button
          type="button"
          :class="['badge', dryRun ? 'dry-run-active' : 'dry-run-inactive']"
          :title="dryRun ? t('dryRun.enabled') : t('dryRun.disabled')"
          @click="emit('toggleDryRun')"
        >
          <span>🧪 {{ dryRun ? t('dryRun.badge') : t('dryRun.toggle') }}</span>
        </button>
      </div>

      <!-- CENTER TELEMETRY -->
      <div class="telemetry">
        <span class="tel-item" :title="mixerModel">
          {{ t('device.mixer') }}: <b>{{ mixerModel }}</b>
        </span>
        <span class="tel-item" title="OSC Network Ping Latency">
          {{ t('device.rtt') }}: <b class="font-mono text-cyan">{{ rttMs !== null ? `${rttMs.toFixed(1)}ms` : '—' }}</b>
        </span>
        <span class="tel-item" title="DSP FFT Latency">
          {{ t('device.dspLatency') }}: <b class="font-mono">{{ dspLatencyMs.toFixed(1) }}ms</b>
        </span>
        <span class="tel-item">
          {{ t('device.xruns') }}: <b class="font-mono" :class="{ 'text-red': xruns > 0 }">{{ xruns }}</b>
        </span>
      </div>

      <div class="row-right">
        <!-- PRESET SELECTOR -->
        <div class="preset-wrapper">
          <select class="preset-select" :value="selectedPreset" @change="onPresetChange">
            <option value="monitor">{{ t('header.presetMonitor') }}</option>
            <option value="foh">{{ t('header.presetFoh') }}</option>
            <option value="acoustic">{{ t('header.presetAcoustic') }}</option>
            <option value="speech">{{ t('header.presetSpeech') }}</option>
          </select>
        </div>

        <!-- LANGUAGE TOGGLE -->
        <div class="lang-pill" role="group" :aria-label="t('header.langSwitcher')">
          <button
            type="button"
            :class="['lang-btn', { active: lang === 'vi' }]"
            :aria-label="t('header.vietnamese')"
            @click="setLang('vi')"
          >
            VI
          </button>
          <button
            type="button"
            :class="['lang-btn', { active: lang === 'en' }]"
            :aria-label="t('header.english')"
            @click="setLang('en')"
          >
            EN
          </button>
        </div>
      </div>
    </div>

    <!-- ROW 2: MISSION CONTROL, AUDIO TOOLS & MODES -->
    <div class="bar-row bar-bottom">
      <!-- LEFT TOOLS -->
      <div class="quick-tools">
        <button
          class="tool-btn btn-signal"
          :title="t('header.signalGen')"
          @click="emit('openSignalGen')"
        >
          🎵 {{ t('header.signalGen') }}
        </button>
        <button
          class="tool-btn mock-btn"
          :title="t('demo.title')"
          @click="emit('openDemoFeedback')"
        >
          ⚡ {{ t('demo.btn') }}
        </button>
        <button
          class="tool-btn"
          :title="t('diagnostics.title')"
          @click="emit('openDiagnostics')"
        >
          🩺 {{ t('diagnostics.btn') }}
        </button>
        <button
          class="tool-btn"
          :title="t('wizard.title')"
          @click="emit('openWizard')"
        >
          🎛️ {{ t('wizard.btn') }}
        </button>
        <button
          class="tool-btn"
          :title="t('dynamics.title')"
          @click="emit('openDynamics')"
        >
          🎚️ {{ t('dynamics.btn') }}
        </button>
      </div>

      <!-- CENTER: MODE SELECTOR -->
      <div class="mode-selector" role="group" :aria-label="t('modes.label')">
        <button
          type="button"
          :class="['mode-btn', { active: currentMode === 'auto' }]"
          @click="emit('setMode', 'auto')"
        >
          {{ t('modes.auto') }}
        </button>
        <button
          type="button"
          :class="['mode-btn', { active: currentMode === 'semi' }]"
          @click="emit('setMode', 'semi')"
        >
          {{ t('modes.semi') }}
        </button>
        <button
          type="button"
          :class="['mode-btn', { active: currentMode === 'manual' }]"
          @click="emit('setMode', 'manual')"
        >
          {{ t('modes.manual') }}
        </button>
      </div>

      <!-- RIGHT: COMPACT PANIC -->
      <slot name="panic" />
    </div>
  </header>
</template>

<style scoped>
.status-bar {
  position: sticky;
  top: 0;
  z-index: 100;
  display: flex;
  flex-direction: column;
  background: rgba(13, 18, 26, 0.98);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: 2px solid var(--border-color);
  padding: 6px 16px;
  gap: 6px;
}

.bar-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  gap: 12px;
}

.row-left, .row-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.brand-wrapper {
  display: flex;
  flex-direction: column;
  margin-right: 6px;
}

.brand {
  font-weight: 800;
  font-size: 13px;
  letter-spacing: 0.8px;
  color: var(--accent-cyan);
}

.brand-sub {
  font-size: 8px;
  font-weight: 600;
  color: var(--text-dim);
  letter-spacing: 0.5px;
}

/* Language Pill */
.lang-pill {
  display: flex;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  overflow: hidden;
}

.lang-btn {
  background: none;
  border: none;
  padding: 3px 8px;
  font-size: 10px;
  font-weight: 700;
  color: var(--text-dim);
  cursor: pointer;
  transition: all 0.15s ease;
}

.lang-btn.active {
  background: var(--accent-cyan);
  color: #000;
}

/* Status Badges */
.badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 700;
  border: 1px solid transparent;
  background: var(--bg-tertiary);
  color: var(--text-main);
  transition: all 0.15s ease;
}

.badge.connected {
  background: rgba(16, 185, 129, 0.15);
  color: var(--accent-green);
  border-color: rgba(16, 185, 129, 0.4);
}

.badge.connecting,
.badge.reconnecting {
  background: rgba(245, 158, 11, 0.15);
  color: var(--accent-amber);
  border-color: rgba(245, 158, 11, 0.4);
}

.badge.disconnected {
  background: rgba(239, 68, 68, 0.15);
  color: var(--accent-red);
  border-color: rgba(239, 68, 68, 0.4);
}

.badge.mock {
  background: rgba(168, 85, 247, 0.15);
  color: var(--accent-purple);
  border-color: rgba(168, 85, 247, 0.4);
}

.dry-run-active {
  background: rgba(245, 158, 11, 0.15);
  color: var(--accent-amber);
  border-color: var(--accent-amber);
}

.dry-run-inactive {
  background: var(--bg-tertiary);
  color: var(--text-dim);
  border-color: var(--border-color);
}

/* Preset Dropdown */
.preset-select {
  background: #090e17;
  border: 1px solid var(--border-color);
  color: var(--accent-cyan);
  font-size: 11px;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 4px;
  cursor: pointer;
  outline: none;
}

/* Telemetry */
.telemetry {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 11px;
  color: var(--text-dim);
  background: var(--bg-primary);
  padding: 3px 12px;
  border-radius: 4px;
  border: 1px solid var(--border-color);
}

.tel-item b {
  color: var(--text-main);
}

/* Quick Tools */
.quick-tools {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: nowrap;
}

.tool-btn {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  color: var(--text-secondary);
  padding: 5px 10px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.tool-btn:hover {
  background: var(--border-highlight);
  color: #fff;
  border-color: var(--accent-cyan);
}

/* Mode Selector */
.mode-selector {
  display: flex;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  overflow: hidden;
}

.mode-btn {
  background: none;
  border: none;
  padding: 5px 12px;
  font-size: 11px;
  font-weight: 700;
  color: var(--text-dim);
  cursor: pointer;
  transition: all 0.15s ease;
  white-space: nowrap;
}

.mode-btn:hover {
  color: var(--text-main);
}

.mode-btn.active {
  background: var(--accent-cyan);
  color: #000;
  box-shadow: 0 0 10px rgba(56, 189, 248, 0.5);
}
</style>
