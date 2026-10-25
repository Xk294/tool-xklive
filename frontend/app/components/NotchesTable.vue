<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import type { ActiveNotch } from '~/composables/useCompanionSocket'
import { useI18n } from '~/composables/useI18n'
import { formatTargetName, getMixerChannelCount } from '~/utils/eventTranslator'

const { t } = useI18n()

const props = defineProps<{
  mixerModel?: string
  notches: ActiveNotch[]
  selectedFreq?: number | null
}>()

const totalChannels = computed(() => getMixerChannelCount(props.mixerModel || 'XR18'))

const emit = defineEmits<{
  (e: 'release', channel: number, band: number, target: string, bus?: number | null): void
  (e: 'releaseAll'): void
  (e: 'export', format: 'json' | 'csv'): void
  (e: 'applyManualNotch', target: string, channel: number, bus: number | null, freqHz: number, gainDb: number, q: number): void
}>()

const tick = ref(0)
let timer: ReturnType<typeof setInterval> | null = null

// Manual Quick Notch Injector State
const isInjectorOpen = ref(false)
const manualTarget = ref<'main' | 'bus' | 'ch'>('main')
const manualChannel = ref(1)
const manualBus = ref(1)
const manualFreq = ref(2500)
const manualGain = ref(-6.0)
const manualQ = ref(8.0)

const COMMON_FEEDBACK_FREQS = [250, 400, 630, 1000, 1600, 2500, 3150, 4000, 6300, 8000]

watch(() => props.selectedFreq, (newFreq) => {
  if (newFreq && newFreq > 20) {
    manualFreq.value = newFreq
    isInjectorOpen.value = true
  }
})

watch(() => props.notches, () => {
  tick.value = 0
}, { deep: false })

function formatAge(ageS: number): string {
  const elapsed = Math.round(tick.value)
  const s = Math.round(ageS) + elapsed
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const rem = s % 60
  if (m < 60) return `${m}m ${rem.toString().padStart(2, '0')}s`
  const h = Math.floor(m / 60)
  const rm = m % 60
  return `${h}h ${rm.toString().padStart(2, '0')}m`
}

function formatTarget(n: ActiveNotch): string {
  return formatTargetName(n, t)
}

function submitManualNotch() {
  emit(
    'applyManualNotch',
    manualTarget.value,
    manualTarget.value === 'ch' ? manualChannel.value : 0,
    manualTarget.value === 'bus' ? manualBus.value : null,
    manualFreq.value,
    manualGain.value,
    manualQ.value
  )
}

onMounted(() => {
  timer = setInterval(() => { tick.value++ }, 1000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="c-card notches-card">
    <div class="c-card-title">
      <div class="title-left">
        <span>🛡️ {{ t('notches.title') }}</span>
        <span class="count-badge font-mono">{{ notches.length }}</span>
      </div>

      <div class="actions-group">
        <button
          class="c-btn-small btn-toggle-injector"
          :class="{ active: isInjectorOpen }"
          @click="isInjectorOpen = !isInjectorOpen"
        >
          {{ isInjectorOpen ? '✕ ' + t('common.close') : '➕ ' + t('notches.quickNotchTitle') }}
        </button>
        <button class="c-btn-small" :title="t('notches.exportCsv')" @click="emit('export', 'csv')">
          📄 {{ t('notches.exportCsv') }}
        </button>
        <button class="c-btn-small" :title="t('notches.exportJson')" @click="emit('export', 'json')">
          📦 {{ t('notches.exportJson') }}
        </button>
        <button
          v-if="notches.length > 0"
          class="c-btn-small btn-release-all"
          @click="emit('releaseAll')"
        >
          🧹 {{ t('common.releaseAll') }}
        </button>
      </div>
    </div>

    <!-- QUICK MANUAL NOTCH INJECTOR DRAWER -->
    <div v-if="isInjectorOpen" class="injector-panel">
      <div class="injector-header">
        <span class="injector-title">⚡ {{ t('notches.quickNotchTitle') }}</span>
      </div>

      <div class="injector-grid">
        <!-- TARGET SELECTION -->
        <div class="inj-field">
          <label>{{ t('notches.targetType') }}</label>
          <div class="target-picker">
            <button
              :class="['t-btn', { active: manualTarget === 'main' }]"
              @click="manualTarget = 'main'"
            >
              Main LR
            </button>
            <button
              :class="['t-btn', { active: manualTarget === 'bus' }]"
              @click="manualTarget = 'bus'"
            >
              Bus
            </button>
            <button
              :class="['t-btn', { active: manualTarget === 'ch' }]"
              @click="manualTarget = 'ch'"
            >
              Ch
            </button>
          </div>
          <select
            v-if="manualTarget === 'ch'"
            v-model.number="manualChannel"
            class="c-input target-subselect"
          >
            <option v-for="ch in totalChannels" :key="ch" :value="ch">CH {{ ch.toString().padStart(2, '0') }}</option>
          </select>
          <select
            v-else-if="manualTarget === 'bus'"
            v-model.number="manualBus"
            class="c-input target-subselect"
          >
            <option v-for="b in 6" :key="b" :value="b">Bus {{ b }}</option>
          </select>
        </div>

        <!-- FREQUENCY INPUT -->
        <div class="inj-field">
          <label>{{ t('notches.freqHz') }}</label>
          <input
            v-model.number="manualFreq"
            type="number"
            min="20"
            max="20000"
            step="1"
            class="c-input"
          />
        </div>

        <!-- GAIN DEPTH -->
        <div class="inj-field">
          <label>{{ t('notches.gainDb') }}</label>
          <select v-model.number="manualGain" class="c-input">
            <option :value="-3.0">-3.0 dB (Thăm dò)</option>
            <option :value="-6.0">-6.0 dB (Chuẩn)</option>
            <option :value="-9.0">-9.0 dB (Sâu)</option>
            <option :value="-12.0">-12.0 dB (Tối đa)</option>
          </select>
        </div>

        <!-- Q FACTOR -->
        <div class="inj-field">
          <label>{{ t('notches.qFactor') }}</label>
          <select v-model.number="manualQ" class="c-input">
            <option :value="5.0">Q = 5.0 (Trung bình)</option>
            <option :value="8.0">Q = 8.0 (Hẹp chuẩn)</option>
            <option :value="10.0">Q = 10.0 (Cực hẹp)</option>
          </select>
        </div>

        <!-- SUBMIT BUTTON -->
        <div class="inj-field submit-field">
          <button class="c-btn-primary btn-apply" @click="submitManualNotch">
            {{ t('notches.applyNotch') }}
          </button>
        </div>
      </div>

      <!-- PRESET FREQUENCIES PILLS -->
      <div class="freq-pills">
        <button
          v-for="f in COMMON_FEEDBACK_FREQS"
          :key="f"
          :class="['f-pill', { active: manualFreq === f }]"
          @click="manualFreq = f"
        >
          {{ f >= 1000 ? `${f / 1000}k` : f }} Hz
        </button>
      </div>
    </div>

    <!-- NOTCHES TABLE -->
    <div class="table-responsive">
      <table class="data-table">
        <thead>
          <tr>
            <th>{{ t('notches.colTarget') }}</th>
            <th>{{ t('notches.colFrequency') }}</th>
            <th>{{ t('notches.colGain') }}</th>
            <th>{{ t('notches.colBand') }}</th>
            <th>{{ t('notches.colAge') }}</th>
            <th>{{ t('notches.colStatus') }}</th>
            <th class="text-right">{{ t('notches.colActions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="notches.length === 0">
            <td colspan="7" class="table-empty">
              <span>{{ t('notches.empty') }}</span>
            </td>
          </tr>
          <tr
            v-for="n in notches"
            :key="`${n.target}_${n.channel}_${n.bus}_${n.band}`"
            class="notch-row"
          >
            <td>
              <span class="target-chip">{{ formatTarget(n) }}</span>
            </td>
            <td class="font-mono text-cyan font-bold">{{ n.freq_hz.toFixed(1) }} Hz</td>
            <td class="font-mono text-red font-bold">{{ n.gain_db.toFixed(1) }} dB</td>
            <td><span class="band-tag font-mono">B{{ n.band }}</span></td>
            <td class="font-mono text-dim">{{ formatAge(n.age_s) }}</td>
            <td>
              <span v-if="n.step_count > 1" class="status-badge stepping">
                {{ t('notches.stepping', { n: n.step_count }) }}
              </span>
              <span v-else class="status-badge stable">
                {{ t('notches.stable') }}
              </span>
            </td>
            <td class="text-right">
              <div class="btn-cell">
                <button
                  class="action-btn btn-release"
                  :title="t('common.release')"
                  @click="emit('release', n.channel, n.band, n.target, n.bus)"
                >
                  {{ t('common.release') }}
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.notches-card {
  margin-bottom: 12px;
}

.title-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.count-badge {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  padding: 1px 6px;
  border-radius: 10px;
  font-size: 11px;
  color: var(--accent-cyan);
}

.actions-group {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.btn-toggle-injector.active {
  background: rgba(56, 189, 248, 0.2);
  border-color: var(--accent-cyan);
  color: var(--accent-cyan);
}

.btn-release-all {
  color: var(--accent-amber);
}

/* INJECTOR PANEL */
.injector-panel {
  background: #090d14;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.injector-title {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  color: var(--accent-cyan);
}

.injector-grid {
  display: grid;
  grid-template-columns: 140px 1fr 1fr 1fr 140px;
  gap: 8px;
  align-items: flex-end;
}

@media (max-width: 900px) {
  .injector-grid {
    grid-template-columns: 1fr 1fr;
  }
}

.inj-field label {
  display: block;
  font-size: 10px;
  font-weight: 600;
  color: var(--text-dim);
  margin-bottom: 4px;
}

.target-picker {
  display: flex;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  overflow: hidden;
}

.t-btn {
  flex: 1;
  background: none;
  border: none;
  padding: 6px 4px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-dim);
  cursor: pointer;
}

.t-btn.active {
  background: var(--bg-tertiary);
  color: var(--accent-cyan);
}

.target-subselect {
  margin-top: 4px;
}

.btn-apply {
  width: 100%;
  padding: 6px;
}

.freq-pills {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.f-pill {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  border-radius: 3px;
  padding: 2px 8px;
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}

.f-pill:hover, .f-pill.active {
  border-color: var(--accent-cyan);
  color: var(--accent-cyan);
}

/* DATA TABLE */
.table-responsive {
  max-height: 320px;
  overflow-y: auto;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.data-table th {
  text-align: left;
  padding: 8px 10px;
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  color: var(--text-dim);
  background: #06090e;
  border-bottom: 1px solid var(--border-color);
  position: sticky;
  top: 0;
  z-index: 2;
}

.data-table td {
  padding: 8px 10px;
  border-bottom: 1px solid #141c28;
}

.notch-row:hover {
  background: rgba(255, 255, 255, 0.02);
}

.table-empty {
  text-align: center;
  color: var(--text-muted);
  font-style: italic;
  padding: 24px 0 !important;
}

.target-chip {
  background: #111722;
  border: 1px solid var(--border-color);
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 600;
}

.band-tag {
  background: rgba(56, 189, 248, 0.1);
  color: var(--accent-cyan);
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 11px;
}

.status-badge {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 3px;
  font-weight: 600;
}

.status-badge.stable {
  background: rgba(16, 185, 129, 0.15);
  color: var(--accent-green);
}

.status-badge.stepping {
  background: rgba(245, 158, 11, 0.15);
  color: var(--accent-amber);
}

.btn-cell {
  display: flex;
  justify-content: flex-end;
  gap: 4px;
}

.action-btn {
  padding: 3px 8px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid var(--border-color);
  background: var(--bg-tertiary);
  color: var(--text-secondary);
  transition: all 0.15s ease;
}

.action-btn:hover {
  background: var(--border-color);
  color: #fff;
}

.btn-release:hover {
  border-color: var(--accent-amber);
  color: var(--accent-amber);
}

.btn-undo:hover {
  border-color: var(--accent-cyan);
  color: var(--accent-cyan);
}

.text-right {
  text-align: right;
}
</style>
