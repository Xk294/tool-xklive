<script setup lang="ts">
defineProps<{
  mixerStatus: 'CONNECTED' | 'RECONNECTING' | 'DISCONNECTED'
  mixerModel: string
  latencyMs: number
  xruns: number
  isLanRta: boolean
  currentMode: 'auto' | 'semi' | 'manual'
}>()

const emit = defineEmits<{
  (e: 'setMode', mode: 'auto' | 'semi' | 'manual'): void
}>()
</script>

<template>
  <header class="status-bar">
    <div class="status-group">
      <div class="brand">
        <span>⚡ AUTO SOUND</span>
      </div>

      <div :class="['badge', mixerStatus.toLowerCase()]">
        <span class="pulse-dot" />
        <span>{{ mixerStatus === 'CONNECTED' ? 'MIXER SẴN SÀNG' : (mixerStatus === 'RECONNECTING' ? 'ĐANG KẾT NỐI LẠI' : 'MẤT KẾT NỐI') }}</span>
      </div>

      <span v-if="isLanRta" class="badge lan-rta">[THỬ NGHIỆM: LAN RTA]</span>

      <div class="telemetry">
        <span>Mixer: <b>{{ mixerModel }}</b></span>
        <span>Trễ: <b>{{ latencyMs.toFixed(1) }} ms</b></span>
        <span>xruns: <b>{{ xruns }}</b></span>
      </div>
    </div>

    <div class="status-group">
      <div class="mode-selector">
        <button
          :class="['mode-btn', { active: currentMode === 'auto' }]"
          @click="emit('setMode', 'auto')"
        >
          AUTO
        </button>
        <button
          :class="['mode-btn', { active: currentMode === 'semi' }]"
          @click="emit('setMode', 'semi')"
        >
          SEMI
        </button>
        <button
          :class="['mode-btn', { active: currentMode === 'manual' }]"
          @click="emit('setMode', 'manual')"
        >
          MANUAL
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
  gap: 12px;
}

.brand {
  font-weight: 700;
  font-size: 16px;
  letter-spacing: 0.5px;
  color: var(--accent-cyan);
  display: flex;
  align-items: center;
  gap: 6px;
}

.badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  font-family: var(--font-mono);
  text-transform: uppercase;
}

.badge.connected {
  background: rgba(34, 197, 94, 0.15);
  color: var(--accent-green);
  border: 1px solid var(--accent-green);
}

.badge.reconnecting {
  background: rgba(245, 158, 11, 0.15);
  color: var(--accent-amber);
  border: 1px solid var(--accent-amber);
}

.badge.disconnected {
  background: rgba(239, 68, 68, 0.15);
  color: var(--accent-red);
  border: 1px solid var(--accent-red);
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
  font-size: 12px;
  color: var(--text-dim);
  display: flex;
  gap: 12px;
}

.telemetry span b {
  color: var(--text-main);
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
