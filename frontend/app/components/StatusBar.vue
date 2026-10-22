<script setup lang="ts">
import { useI18n } from '~/composables/useI18n'

const { lang, setLang, t } = useI18n()

defineProps<{
  mixerStatus: 'CONNECTED' | 'RECONNECTING' | 'DISCONNECTED' | 'MOCK'
  isMockMode: boolean
  dryRun: boolean
  mixerModel: string
  rttMs: number | null
  dspLatencyMs: number
  xruns: number
  isLanRta: boolean
  currentMode: 'auto' | 'semi' | 'manual'
}>()

const emit = defineEmits<{
  (e: 'setMode', mode: 'auto' | 'semi' | 'manual'): void
  (e: 'toggleDryRun'): void
  (e: 'openDiagnostics'): void
  (e: 'openWizard'): void
  (e: 'openDemoFeedback'): void
  (e: 'openDynamics'): void
}>()
</script>

<template>
  <header class="status-bar">
    <div class="status-group">
      <div class="brand-wrapper" :title="t('header.title')">
        <div class="brand">⚡ {{ t('header.brand') }}</div>
        <div class="brand-sub">{{ t('header.subtitle') }}</div>
      </div>

      <div
        class="lang-pill"
        role="group"
        :aria-label="t('header.langSwitcher')"
      >
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

      <!-- CONNECTION STATUS BADGE -->
      <div v-if="isMockMode" class="badge mock" :title="t('connection.mock')">
        <span class="pulse-dot" />
        <span>{{ t('connection.mock') }}</span>
      </div>
      <div v-else :class="['badge', mixerStatus.toLowerCase()]">
        <span class="pulse-dot" />
        <span>{{ t(`connection.${mixerStatus.toLowerCase()}`) }}</span>
      </div>

      <!-- DRY RUN BADGE / TOGGLE -->
      <button
        type="button"
        :class="['badge', dryRun ? 'dry-run-active' : 'dry-run-inactive']"
        :title="dryRun ? t('dryRun.enabled') : t('dryRun.disabled')"
        @click="emit('toggleDryRun')"
      >
        {{ dryRun ? `🧪 ${t('dryRun.badge')}` : `🧪 ${t('dryRun.toggle')}` }}
      </button>

      <span v-if="isLanRta" class="badge lan-rta">{{ t('device.lanRta') }}</span>

      <!-- SEPARATED TELEMETRY -->
      <div class="telemetry">
        <span :title="mixerModel">{{ t('device.mixer') }}: <b>{{ mixerModel }}</b></span>
        <span title="OSC Network Ping Latency">{{ t('device.rtt') }}: <b>{{ rttMs !== null ? `${rttMs.toFixed(1)} ms` : '—' }}</b></span>
        <span title="DSP FFT Analysis Latency">{{ t('device.dspLatency') }}: <b>{{ dspLatencyMs.toFixed(1) }} ms</b></span>
        <span>{{ t('device.xruns') }}: <b>{{ xruns }}</b></span>
      </div>
    </div>

    <div class="status-group actions-group">
      <!-- QUICK ACTION TOOLS -->
      <div class="quick-tools">
        <button
          v-if="isMockMode"
          class="tool-btn mock-btn"
          :title="t('demo.title')"
          @click="emit('openDemoFeedback')"
        >
          {{ t('demo.btn') }}
        </button>
        <button
          class="tool-btn"
          :title="t('diagnostics.title')"
          @click="emit('openDiagnostics')"
        >
          {{ t('diagnostics.btn') }}
        </button>
        <button
          class="tool-btn"
          :title="t('wizard.title')"
          @click="emit('openWizard')"
        >
          {{ t('wizard.btn') }}
        </button>
        <button
          class="tool-btn"
          :title="t('dynamics.title')"
          @click="emit('openDynamics')"
        >
          {{ t('dynamics.btn') }}
        </button>
      </div>

      <!-- MODE SELECTOR -->
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
  align-items: center;
  justify-content: space-between;
  background: var(--bg-secondary);
  border-bottom: 2px solid var(--border-color);
  padding: 8px 16px;
  gap: 12px;
  flex-wrap: wrap;
}

.status-group {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.actions-group {
  gap: 12px;
}

.brand-wrapper {
  display: flex;
  flex-direction: column;
}

.brand {
  font-weight: 800;
  font-size: 15px;
  letter-spacing: 0.8px;
  color: var(--accent-cyan);
  line-height: 1.1;
}

.brand-sub {
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 1.2px;
  color: var(--accent-amber);
  opacity: 0.9;
  line-height: 1.2;
}

.lang-pill {
  display: inline-flex;
  align-items: center;
  background: var(--bg-tertiary);
  border-radius: 9999px;
  padding: 2px;
  border: 1px solid var(--border-color);
  gap: 2px;
}

.lang-btn {
  padding: 4px 10px;
  border-radius: 9999px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-dim);
  font-weight: 700;
  font-size: 11px;
  font-family: var(--font-mono);
  cursor: pointer;
  transition: all 0.2s ease;
  line-height: 1;
}

.lang-btn.active {
  background: rgba(245, 158, 11, 0.15);
  border-color: var(--accent-amber);
  color: #d97706;
  box-shadow: 0 1px 3px rgba(245, 158, 11, 0.2);
}

.badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  font-family: var(--font-mono);
  text-transform: uppercase;
  border: 1px solid transparent;
  cursor: default;
}

.badge.connected {
  background: rgba(34, 197, 94, 0.15);
  color: var(--accent-green);
  border-color: var(--accent-green);
}

.badge.reconnecting {
  background: rgba(245, 158, 11, 0.15);
  color: var(--accent-amber);
  border-color: var(--accent-amber);
}

.badge.disconnected {
  background: rgba(239, 68, 68, 0.15);
  color: var(--accent-red);
  border-color: var(--accent-red);
}

.badge.mock {
  background: rgba(168, 85, 247, 0.15);
  color: #c084fc;
  border-color: #a855f7;
  font-weight: 700;
}

.badge.dry-run-active {
  background: rgba(234, 179, 8, 0.2);
  color: #eab308;
  border-color: #eab308;
  cursor: pointer;
  font-weight: 700;
}

.badge.dry-run-inactive {
  background: transparent;
  color: var(--text-dim);
  border: 1px dashed var(--border-color);
  cursor: pointer;
}

.badge.dry-run-inactive:hover {
  border-color: var(--accent-cyan);
  color: var(--accent-cyan);
}

.badge.lan-rta {
  background: rgba(245, 158, 11, 0.25);
  color: var(--accent-amber);
  border: 1px dashed var(--accent-amber);
}

.pulse-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}

.telemetry {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-dim);
  display: flex;
  gap: 10px;
}

.telemetry span b {
  color: var(--text-main);
}

.quick-tools {
  display: flex;
  gap: 6px;
}

.tool-btn {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  color: var(--text-main);
  padding: 5px 9px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}

.tool-btn:hover {
  background: var(--border-color);
}

.tool-btn.mock-btn {
  border-color: #a855f7;
  color: #c084fc;
  background: rgba(168, 85, 247, 0.1);
}

.mode-selector {
  display: flex;
  background: var(--bg-tertiary);
  border-radius: 6px;
  padding: 2px;
  border: 1px solid var(--border-color);
}

.mode-btn {
  padding: 5px 12px;
  border-radius: 4px;
  border: none;
  background: transparent;
  color: var(--text-dim);
  font-weight: 600;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.mode-btn.active {
  background: var(--accent-cyan);
  color: #000;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
}
</style>
