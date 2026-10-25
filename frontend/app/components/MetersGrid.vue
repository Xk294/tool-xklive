<script setup lang="ts">
import { ref, computed } from 'vue'
import type { ChannelInfo } from '~/composables/useCompanionSocket'
import { useI18n } from '~/composables/useI18n'
import {
  METER_CLIP_THRESHOLD_DB,
  METER_FLOOR_DB,
  METER_SPAN_DB,
  linearToDb,
  getMixerChannelCount
} from '~/utils/eventTranslator'

const { t } = useI18n()

const props = defineProps<{
  mixerModel?: string
  meters: number[]
  channels?: ChannelInfo[]
}>()

const emit = defineEmits<{
  (e: 'toggleLock', ch: number): void
}>()

const selectedCh = ref<number | null>(null)

function formatName(name?: string, ch?: number): string {
  if (!name) return `CH${ch ?? ''}`
  const match = name.match(/^(?:K\u00eanh|Ch)\s*0?(\d+)$/i)
  if (match && match[1]) {
    return t('meters.channel', { n: match[1] })
  }
  return name
}

const totalChannels = computed(() =>
  getMixerChannelCount(props.mixerModel || 'XR18', props.channels?.length)
)

const meterStrips = computed(() =>
  Array.from({ length: totalChannels.value }, (_, idx) => {
    const ch = idx + 1
    const chInfo = props.channels?.[idx]
    const linVal = props.meters[idx] ?? chInfo?.level ?? 0
    const db = linVal > 1e-4 ? Math.max(-90, Math.min(0, linearToDb(linVal))) : -90.0
    const heightPct = Math.min(100, Math.max(0, ((db - METER_FLOOR_DB) / METER_SPAN_DB) * 100))
    const isClip = db >= METER_CLIP_THRESHOLD_DB
    const readout = db > -59 ? String(Math.round(db)) : '-inf'
    const isMuted = !!chInfo?.is_muted
    const isLocked = !!chInfo?.is_locked
    const rawName = chInfo?.name

    return {
      ch,
      badge: ch.toString().padStart(2, '0'),
      readout,
      heightPct,
      isClip,
      isMuted,
      isLocked,
      tooltip: rawName || `CH ${ch}`,
      displayName: formatName(rawName, ch)
    }
  })
)

function handleSelect(ch: number) {
  selectedCh.value = selectedCh.value === ch ? null : ch
}
</script>

<template>
  <div class="c-card meters-card">
    <div class="c-card-title">
      <div class="title-left">
        <span>🎚️ {{ t('meters.title') }}</span>
      </div>
      <div class="meter-legend">
        <span class="legend-chip"><b class="icon-lock">🔒</b>: {{ t('meters.hint') }}</span>
        <span class="legend-chip"><b class="icon-mute">M</b>: {{ t('meters.hintMute') }}</span>
      </div>
    </div>

    <!-- CHANNEL METERS RACK -->
    <div class="meters-rack" :style="{ gridTemplateColumns: `repeat(${totalChannels}, 1fr)` }">
      <div
        v-for="strip in meterStrips"
        :key="strip.ch"
        :class="[
          'meter-strip',
          {
            'is-muted': strip.isMuted,
            'is-locked': strip.isLocked,
            'is-selected': selectedCh === strip.ch
          }
        ]"
        @click="handleSelect(strip.ch)"
      >
        <!-- DB PEAK READOUT -->
        <div class="peak-val font-mono">
          {{ strip.readout }}
        </div>

        <!-- VU / PEAK LED BAR -->
        <div class="meter-bar-track">
          <!-- CLIP LED (Red Top) -->
          <div
            :class="['clip-led', { active: strip.isClip }]"
            :title="t('meters.clipWarning')"
          />

          <!-- GRADIENT FILL BAR -->
          <div
            class="meter-bar-fill"
            :style="{ height: strip.heightPct + '%' }"
          />

          <!-- SUBTLE DB SCALE MARKINGS -->
          <div class="meter-scale-marks">
            <span class="mark m-0" />
            <span class="mark m-6" />
            <span class="mark m-18" />
            <span class="mark m-36" />
          </div>
        </div>

        <!-- CHANNEL FOOTER INFO & ACTIONS -->
        <div class="strip-footer">
          <span class="ch-badge font-mono">{{ strip.badge }}</span>

          <div class="ch-status-icons">
            <button
              type="button"
              :class="['tag-lock-btn', { locked: strip.isLocked }]"
              :title="strip.isLocked ? t('meters.locked') : t('meters.hint')"
              @click.stop="emit('toggleLock', strip.ch)"
            >
              {{ strip.isLocked ? '🔒' : '🔓' }}
            </button>
            <span
              v-if="strip.isMuted"
              class="tag-mute"
              :title="t('meters.muted')"
            >
              M
            </span>
          </div>

          <span
            class="ch-custom-name"
            :title="strip.tooltip"
          >
            {{ strip.displayName }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.meters-card {
  margin-bottom: 12px;
}

.meter-legend {
  display: flex;
  gap: 12px;
  font-size: 11px;
  color: var(--text-dim);
}

.legend-chip b {
  font-family: var(--font-mono);
}

.icon-lock { color: var(--accent-amber); }
.icon-mute { color: var(--accent-red); }
.icon-solo { color: var(--accent-cyan); }

.meters-rack {
  display: grid;
  grid-template-columns: repeat(16, 1fr);
  gap: 6px;
  height: 124px;
  background: #06080d;
  padding: 8px 6px;
  border-radius: 6px;
  border: 1px solid var(--border-color);
}

.meter-strip {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: space-between;
  height: 100%;
  cursor: pointer;
  border-radius: 4px;
  padding: 2px;
  transition: background 0.15s ease, border-color 0.15s ease;
}

.meter-strip:hover {
  background: rgba(255, 255, 255, 0.04);
}

.meter-strip.is-selected {
  background: rgba(56, 189, 248, 0.1);
  border: 1px solid var(--accent-cyan);
}

.meter-strip.is-muted {
  opacity: 0.45;
}

.peak-val {
  font-size: 9px;
  color: var(--text-dim);
  height: 12px;
  line-height: 12px;
}

.meter-bar-track {
  position: relative;
  width: 100%;
  max-width: 14px;
  height: 68px;
  background: #111622;
  border-radius: 2px;
  overflow: hidden;
  border: 1px solid #1a2332;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
}

.clip-led {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 4px;
  background: #450a0a;
  transition: background 0.1s ease;
}

.clip-led.active {
  background: #ef4444;
  box-shadow: 0 0 6px #ef4444;
}

.meter-bar-fill {
  width: 100%;
  background: linear-gradient(to top, #0284c7 0%, #10b981 50%, #f59e0b 80%, #ef4444 100%);
  border-radius: 1px;
  transition: height 0.06s linear;
}

.meter-scale-marks {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  right: 0;
  pointer-events: none;
}

.meter-scale-marks .mark {
  position: absolute;
  left: 0;
  right: 0;
  height: 1px;
  background: rgba(255, 255, 255, 0.12);
}

.m-0 { top: 4px; }
.m-6 { top: 18px; }
.m-18 { top: 38px; }
.m-36 { top: 52px; }

.strip-footer {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
  margin-top: 2px;
}

.ch-badge {
  font-size: 10px;
  font-weight: 700;
  color: var(--text-main);
}

.ch-status-icons {
  display: flex;
  gap: 2px;
  height: 12px;
}

.tag-lock-btn {
  background: none;
  border: none;
  padding: 0;
  font-size: 9px;
  line-height: 1;
  cursor: pointer;
  opacity: 0.35;
  transition: opacity 0.15s ease;
}

.meter-strip:hover .tag-lock-btn,
.tag-lock-btn.locked {
  opacity: 1;
}

.tag-mute {
  font-size: 8px;
  font-weight: 900;
  color: var(--accent-red);
}

.ch-custom-name {
  font-size: 9px;
  color: var(--text-dim);
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
