<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted } from 'vue'
import type { ActiveNotch } from '~/composables/useCompanionSocket'
import { useI18n } from '~/composables/useI18n'

const { t } = useI18n()

const props = defineProps<{
  notches: ActiveNotch[]
}>()

const emit = defineEmits<{
  (e: 'release', channel: number, band: number, target: string, bus?: number | null): void
  (e: 'releaseAll'): void
}>()

const tick = ref(0)
let timer: ReturnType<typeof setInterval> | null = null

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
  if (n.target === 'main' || n.channel === 0) {
    return 'Main LR'
  }
  if (n.target === 'bus') {
    return t('notches.bus', { n: n.bus ?? '' })
  }
  if (!n.channel_name) {
    return t('notches.channel', { n: n.channel })
  }
  const match = n.channel_name.match(/^(?:K\u00eanh|Ch)\s*0?(\d+)$/i)
  if (match) {
    return t('notches.channel', { n: match[1] })
  }
  return n.channel_name
}

onMounted(() => {
  timer = setInterval(() => { tick.value++ }, 1000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="c-card">
    <div class="c-card-title">
      <span>{{ t('notches.title') }}</span>
      <button class="c-btn-small" @click="emit('releaseAll')">{{ t('common.releaseAll') }}</button>
    </div>

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
            <th>{{ t('notches.colActions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="notches.length === 0">
            <td colspan="7" class="table-empty">{{ t('notches.empty') }}</td>
          </tr>
          <tr
            v-for="n in notches"
            :key="`${n.target}_${n.channel}_${n.bus}_${n.band}`"
          >
            <td>
              <b>{{ formatTarget(n) }}</b>
            </td>
            <td>{{ n.freq_hz.toFixed(1) }} Hz</td>
            <td class="notch-gain">{{ n.gain_db.toFixed(1) }} dB</td>
            <td>Band {{ n.band }}</td>
            <td>{{ formatAge(n.age_s) }}</td>
            <td>{{ n.status_code ? t(`notches.${n.status_code}`, { n: n.step_count, step: n.step_count }) : (n.step_count > 1 ? t('notches.stepping', { n: n.step_count }) : t('notches.stable')) }}</td>
            <td>
              <button
                class="c-btn-small"
                @click="emit('release', n.channel, n.band, n.target, n.bus)"
              >
                {{ t('common.release') }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.table-responsive {
  width: 100%;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

table.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  font-family: var(--font-mono);
}

table.data-table th {
  text-align: left;
  padding: 8px 6px;
  color: var(--text-dim);
  border-bottom: 1px solid var(--border-color);
  font-size: 11px;
}

table.data-table td {
  padding: 8px 6px;
  border-bottom: 1px solid rgba(43, 53, 68, 0.5);
}

.table-empty {
  text-align: center;
  color: var(--text-dim);
  padding: 20px 0;
  font-style: italic;
}

.notch-gain {
  color: var(--accent-red);
  font-weight: 700;
}
</style>
