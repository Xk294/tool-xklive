<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '~/composables/useI18n'
import type { ChannelInfo, GainCalibrationSession } from '~/composables/useCompanionSocket'
import {
  METER_CLIP_THRESHOLD_DB,
  METER_ACTIVE_THRESHOLD_DB,
  METER_FLOOR_DB,
  METER_SPAN_DB,
  linearToDb,
  getMixerChannelCount
} from '~/utils/eventTranslator'

const props = defineProps<{
  mixerModel: string
  currentPreset: string
  meters: number[]
  channels: ChannelInfo[]
  gainSessions?: Record<number, GainCalibrationSession>
}>()

const emit = defineEmits<{
  (e: 'setPreset', preset: string): void
  (e: 'toggleWhitelist', channel: number): void
  (e: 'applyChannelHpf', channel: number, enabled: boolean, freqHz?: number): void
  (e: 'startGainCalibration', channel: number): void
  (e: 'cancelGainCalibration', channel: number): void
  (e: 'prevStep'): void
  (e: 'skipToShow'): void
  (e: 'nextStep'): void
}>()

const { t } = useI18n()

const totalChannels = computed(() =>
  getMixerChannelCount(props.mixerModel, props.channels.length)
)

const channelCards = computed(() => {
  return Array.from({ length: totalChannels.value }, (_, idx) => {
    const chNum = idx + 1
    const chInfo = props.channels[idx]
    const db = linearToDb(props.meters[idx] ?? chInfo?.level ?? 0)
    const isClip = db > METER_CLIP_THRESHOLD_DB
    const isGood = db > METER_ACTIVE_THRESHOLD_DB && db <= METER_CLIP_THRESHOLD_DB
    const fillPct = Math.min(100, Math.max(0, ((db - METER_FLOOR_DB) / METER_SPAN_DB) * 100))
    const rawName = chInfo?.name
    const displayName = rawName && !/^CH\d+$/i.test(rawName)
      ? `Mic ${chNum} (${rawName})`
      : `Micro ${chNum}`
    const whitelisted = chInfo?.whitelisted !== false
    const hpfEnabled = !!chInfo?.hpf_enabled
    const gainSession = props.gainSessions?.[chNum]

    return {
      chNum,
      displayName,
      isMuted: !!chInfo?.is_muted,
      whitelisted,
      hpfEnabled,
      gainSession,
      isClip,
      isGood,
      statusText: isClip ? 'QUÁ TO!' : isGood ? 'TỐT' : 'Đang chờ',
      fillPct
    }
  })
})
</script>

<template>
  <section class="easy-step-card">
    <div class="easy-step-header">
      <h2>Bước 2: Kiểm Tra Tín Hiệu Micro ({{ totalChannels }} Kênh) & Chọn Loại Show</h2>
      <p class="easy-step-desc">
        Nói hoặc hát thử vào từng micro. Đèn xanh lá là đẹp, nếu đỏ hãy vặn bớt nút Gain trên bàn mixer.
      </p>
    </div>

    <!-- Preset Selector -->
    <div class="preset-selector-box">
      <span class="preset-label">Bạn đang làm sự kiện gì?</span>
      <div class="preset-buttons">
        <button
          type="button"
          class="preset-btn"
          :class="{ selected: currentPreset === 'monitor' }"
          @click="emit('setPreset', 'monitor')"
        >
          {{ t('header.presetMonitor') }}
        </button>
        <button
          type="button"
          class="preset-btn"
          :class="{ selected: currentPreset === 'foh' }"
          @click="emit('setPreset', 'foh')"
        >
          {{ t('header.presetFoh') }}
        </button>
        <button
          type="button"
          class="preset-btn"
          :class="{ selected: currentPreset === 'acoustic' }"
          @click="emit('setPreset', 'acoustic')"
        >
          {{ t('header.presetAcoustic') }}
        </button>
        <button
          type="button"
          class="preset-btn"
          :class="{ selected: currentPreset === 'speech' }"
          @click="emit('setPreset', 'speech')"
        >
          {{ t('header.presetSpeech') }}
        </button>
      </div>
    </div>

    <!-- Mic Meters Grid -->
    <div class="mic-meters-container">
      <div
        v-for="ch in channelCards"
        :key="ch.chNum"
        class="mic-meter-card"
        :class="{
          'level-clip': ch.isClip,
          'level-good': ch.isGood,
          'is-muted': ch.isMuted
        }"
      >
        <div class="mic-card-top">
          <span class="mic-title">{{ ch.displayName }}</span>
          <span
            class="mic-status-tag"
            :class="{
              'tag-red': ch.isClip,
              'tag-green': ch.isGood,
              'tag-idle': !ch.isClip && !ch.isGood
            }"
          >
            {{ ch.isMuted ? 'TẮT TIẾNG' : ch.statusText }}
          </span>
        </div>

        <div class="meter-bar-track">
          <div
            class="meter-bar-fill"
            :style="{ width: `${ch.fillPct}%` }"
          />
        </div>

        <div class="mic-quick-tools">
          <button
            type="button"
            class="mic-tool-btn"
            :class="ch.whitelisted ? 'role-mic' : 'role-music'"
            :title="ch.whitelisted ? 'Đang bảo vệ chống hú. Bấm để chuyển sang Kênh Nhạc nền (Khóa EQ)' : 'Đang khóa EQ cho nhạc nền. Bấm để chuyển lại thành Mic'"
            @click="emit('toggleWhitelist', ch.chNum)"
          >
            {{ ch.whitelisted ? '🎤 Mic Hát/MC' : '🎵 Nhạc nền (Khóa EQ)' }}
          </button>

          <button
            type="button"
            class="mic-tool-btn"
            :class="{ 'hpf-active': ch.hpfEnabled }"
            title="Lọc ù trầm và tiếng bụp môi dưới 80Hz cho micro"
            @click="emit('applyChannelHpf', ch.chNum, !ch.hpfEnabled, 80)"
          >
            {{ ch.hpfEnabled ? '🛡️ Đã lọc ù 80Hz' : '🛡️ Lọc ù/bụp 80Hz' }}
          </button>

          <button
            v-if="ch.gainSession?.state !== 'measuring'"
            type="button"
            class="mic-tool-btn"
            title="Đo thử giọng 10 giây để gợi ý mức vặn Gain chuẩn"
            @click="emit('startGainCalibration', ch.chNum)"
          >
            ⚖️ Đo Gain 10s
          </button>
          <button
            v-else
            type="button"
            class="mic-tool-btn measuring-active"
            @click="emit('cancelGainCalibration', ch.chNum)"
          >
            ⏳ Đang đo... (Hủy)
          </button>
        </div>

        <p v-if="ch.gainSession?.state === 'measuring'" class="mic-calib-tip">
          🎙️ Hãy nói hoặc hát đều vào Mic {{ ch.chNum }} trong 10 giây...
        </p>
        <p v-else-if="ch.gainSession?.state === 'completed' && ch.gainSession.advice" class="mic-calib-done">
          ✅ {{ ch.gainSession.advice }}
        </p>
        <p v-if="ch.isClip" class="mic-warning-tip">
          ⚠️ Mic quá to! Vui lòng vặn nhỏ Gain trên mixer.
        </p>
      </div>
    </div>

    <!-- Navigation Buttons -->
    <div class="easy-step-nav-footer">
      <button type="button" class="easy-btn-secondary" @click="emit('prevStep')">
        ← Quay lại bước 1
      </button>
      <div class="next-group">
        <button type="button" class="easy-btn-text" @click="emit('skipToShow')">
          Bỏ qua cân phòng, vào show luôn
        </button>
        <button type="button" class="easy-btn-primary-big" @click="emit('nextStep')">
          TIẾP TỤC: CÂN PHÒNG TRƯỚC SHOW →
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.preset-selector-box {
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: var(--bg-secondary);
  padding: 16px 20px;
  border-radius: 10px;
  border: 1px solid var(--border-color);
}

.preset-label {
  font-size: 14px;
  font-weight: 700;
}

.preset-buttons {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 10px;
}

.preset-btn {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  color: var(--text-secondary);
  padding: 12px 14px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  text-align: left;
}

.preset-btn.selected {
  background: rgba(56, 189, 248, 0.15);
  border-color: var(--accent-cyan);
  color: var(--accent-cyan);
  font-weight: 800;
}

.mic-meters-container {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}

.mic-meter-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: border-color 0.2s ease;
}

.mic-meter-card.level-clip {
  border-color: var(--accent-red);
  background: rgba(239, 68, 68, 0.08);
}

.mic-meter-card.is-muted {
  opacity: 0.6;
}

.mic-card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.mic-title {
  font-weight: 700;
  font-size: 14px;
}

.mic-status-tag {
  font-size: 11px;
  font-weight: 800;
  padding: 2px 8px;
  border-radius: 4px;
}

.tag-red {
  background: var(--accent-red);
  color: #fff;
}

.tag-green {
  background: var(--accent-green);
  color: #000;
}

.tag-idle {
  background: var(--bg-tertiary);
  color: var(--text-dim);
}

.meter-bar-track {
  height: 10px;
  background: var(--bg-primary);
  border-radius: 5px;
  overflow: hidden;
  border: 1px solid var(--border-color);
}

.meter-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--accent-green), var(--accent-amber) 75%, var(--accent-red) 95%);
  transition: width 0.1s linear;
}

.mic-warning-tip {
  font-size: 12px;
  color: var(--accent-red);
  font-weight: 600;
}

.mic-quick-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 2px;
}

.mic-tool-btn {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  color: var(--text-secondary);
  border-radius: 6px;
  padding: 4px 8px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}

.mic-tool-btn:hover {
  border-color: var(--accent-cyan);
  color: var(--text-main);
}

.mic-tool-btn.role-mic {
  border-color: rgba(16, 185, 129, 0.4);
  color: #34d399;
}

.mic-tool-btn.role-music {
  background: rgba(245, 158, 11, 0.14);
  border-color: var(--accent-amber);
  color: #fbbf24;
}

.mic-tool-btn.hpf-active {
  background: rgba(56, 189, 248, 0.16);
  border-color: var(--accent-cyan);
  color: var(--accent-cyan);
}

.mic-tool-btn.measuring-active {
  background: rgba(245, 158, 11, 0.2);
  border-color: var(--accent-amber);
  color: #fef08a;
}

.mic-calib-tip {
  font-size: 11px;
  color: #fbbf24;
  margin: 0;
  font-weight: 600;
}

.mic-calib-done {
  font-size: 11px;
  color: #34d399;
  margin: 0;
  font-weight: 600;
}

.next-group {
  display: flex;
  align-items: center;
  gap: 16px;
}
</style>
