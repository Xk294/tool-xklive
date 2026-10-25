<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  METER_CLIP_THRESHOLD_DB,
  METER_ACTIVE_THRESHOLD_DB,
  METER_FLOOR_DB,
  METER_SPAN_DB,
  linearToDb,
  getMixerChannelCount,
  formatFrequency,
  formatFriendlyTarget,
  extractSuspectHint,
  isNotchAttributedToMic,
  translateEventMessage
} from '~/utils/eventTranslator'
import type {
  OperationMode,
  Proposal,
  LogEntry,
  ActiveNotch,
  ChannelInfo,
  ClipAlert
} from '~/composables/useCompanionSocket'

const props = defineProps<{
  friendlyStatus: {
    color: 'green' | 'amber' | 'red'
    badgeText: string
    headline: string
    subline: string
  }
  mixerModel?: string
  currentMode: OperationMode
  activeNotches?: ActiveNotch[]
  pendingProposals: Proposal[]
  channels?: ChannelInfo[]
  meters?: number[]
  clipAlerts?: ClipAlert[]
  talkoverEnabled?: boolean
  talkoverIsDucked?: boolean
  talkoverMicChannel?: number
  eventLogs: LogEntry[]
  canUndoPanic: boolean
}>()

const emit = defineEmits<{
  (e: 'panic'): void
  (e: 'undoPanic'): void
  (e: 'setMode', mode: OperationMode): void
  (e: 'setTalkoverConfig', enabled: boolean, micChannel?: number): void
  (e: 'toggleWhitelist', channel: number): void
  (e: 'releaseChannelNotches', channel: number): void
  (e: 'approveProposal', id: string): void
  (e: 'rejectProposal', id: string): void
  (e: 'endShow'): void
}>()

const showAllChannels = ref(false)

const latestLogs = computed(() => props.eventLogs.slice(0, 3))

const totalChannels = computed(() =>
  getMixerChannelCount(props.mixerModel || 'XR18', props.channels?.length)
)

const liveChannelRows = computed(() => {
  const notches = props.activeNotches || []
  const alerts = props.clipAlerts || []
  const rows = Array.from({ length: totalChannels.value }, (_, idx) => {
    const chNum = idx + 1
    const chInfo = props.channels?.[idx]
    const db = linearToDb(props.meters?.[idx] ?? chInfo?.level ?? 0)
    const isClip = db > METER_CLIP_THRESHOLD_DB
    const isActive = db > METER_ACTIVE_THRESHOLD_DB
    const hasClipAlert = alerts.some(a => a.channel === chNum)
    const fillPct = Math.min(100, Math.max(0, ((db - METER_FLOOR_DB) / METER_SPAN_DB) * 100))
    const chNotches = notches.filter(n => isNotchAttributedToMic(n, chNum))
    const deepNotchesCount = chNotches.filter(n => (n.gain_db ?? -3) <= -9.0).length
    const whitelisted = chInfo?.whitelisted !== false
    const isMuted = !!chInfo?.is_muted
    const rawName = chInfo?.name
    const label = rawName && !/^CH\d+$/i.test(rawName)
      ? `Mic ${chNum} (${rawName})`
      : `Mic ${chNum}`

    return {
      chNum,
      label,
      isMuted,
      whitelisted,
      isClip: isClip || hasClipAlert,
      isActive,
      fillPct,
      notchesCount: chNotches.length,
      deepNotchesCount,
      latestNotchFreq: chNotches.length > 0 ? chNotches[chNotches.length - 1]?.freq_hz : null
    }
  })

  if (showAllChannels.value) {
    return rows
  }
  const interesting = rows.filter(
    r => !r.isMuted && (r.isActive || r.isClip || r.notchesCount > 0 || !r.whitelisted || r.chNum <= 4)
  )
  return interesting.length > 0 ? interesting : rows.slice(0, 4)
})

const exhaustedWarnings = computed(() => {
  const notches = props.activeNotches || []
  const warnings: string[] = []
  for (let ch = 1; ch <= totalChannels.value; ch++) {
    const deep = notches.filter(
      n => n.target !== 'bus' && n.channel === ch && (n.gain_db ?? -3) <= -9.0
    )
    if (deep.length >= 2) {
      warnings.push(
        `Mic ${ch} đã cắt sâu ${deep.length} điểm (-9 dB đến -12 dB) mà vẫn sát ngưỡng hú. Hãy kéo nhỏ Fader Mic ${ch} xuống một chút hoặc nhắc người cầm mic đứng xa loa hơn.`
      )
    }
  }
  for (let b = 1; b <= 6; b++) {
    const busDeep = notches.filter(
      n => n.target === 'bus' && (n.bus === b || (!n.bus && n.channel === b)) && (n.gain_db ?? -3) <= -9.0
    )
    if (busDeep.length >= 2) {
      warnings.push(
        `Loa Monitor Bus ${b} đang phải cắt sâu ${busDeep.length} băng tần. Hãy giảm nhẹ âm lượng Bus ${b} để tránh nghẹt tiếng.`
      )
    }
  }
  const mainDeep = notches.filter(
    n => n.target !== 'bus' && n.channel === 0 && (n.gain_db ?? -3) <= -9.0
  )
  if (mainDeep.length >= 2) {
    warnings.push(
      `Đường Loa Tổng (Main LR) đang phải cắt sâu ${mainDeep.length} băng tần. Hãy giảm nhẹ âm lượng tổng để tránh nghẹt tiếng.`
    )
  }
  return warnings
})
</script>

<template>
  <section class="easy-step-card live-show-card">
    <!-- HUGE STATUS ORB -->
    <div
      class="status-orb-container"
      :class="{
        'orb-green': friendlyStatus.color === 'green',
        'orb-amber': friendlyStatus.color === 'amber',
        'orb-red': friendlyStatus.color === 'red'
      }"
    >
      <div class="status-orb">
        <span class="orb-badge">{{ friendlyStatus.badgeText }}</span>
      </div>
      <h2 class="status-headline">{{ friendlyStatus.headline }}</h2>
      <p class="status-subline">{{ friendlyStatus.subline }}</p>
    </div>

    <!-- GIANT PANIC & UNDO BUTTONS -->
    <div class="panic-wrapper">
      <button
        type="button"
        class="giant-panic-btn"
        @click="emit('panic')"
      >
        <span class="panic-icon">🚨</span>
        <div class="panic-text-col">
          <span class="panic-main-text">DỪNG KHẨN / TRẢ LẠI NHƯ CŨ</span>
          <span class="panic-hint-text">Phím tắt: bấm nút ESC trên bàn phím</span>
        </div>
      </button>

      <button
        v-if="canUndoPanic"
        type="button"
        class="easy-undo-panic-btn"
        @click="emit('undoPanic')"
      >
        ↩️ Hoàn tác lệnh dừng khẩn (Khôi phục các điểm chống hú vừa xóa)
      </button>

      <p class="panic-explainer">
        Bấm nút này bất cứ lúc nào nếu tiếng bị đổi màu hoặc muốn trả lại nguyên trạng ban đầu.
      </p>
    </div>

    <!-- CONTROL & PRESET ROW -->
    <div class="show-controls-row">
      <!-- Mode toggle -->
      <div class="control-box">
        <span class="control-title">Chế độ dập hú:</span>
        <div class="mode-toggles">
          <button
            type="button"
            class="mode-btn"
            :class="{ active: currentMode === 'auto' }"
            @click="emit('setMode', 'auto')"
          >
            ⚡ Tự động dập ngay (Khuyên dùng)
          </button>
          <button
            type="button"
            class="mode-btn"
            :class="{ active: currentMode === 'semi' }"
            @click="emit('setMode', 'semi')"
          >
            ✋ Hỏi tôi trước khi dập
          </button>
        </div>
      </div>

      <!-- End show button -->
      <div class="end-show-box">
        <button
          type="button"
          class="btn-end-show"
          @click="emit('endShow')"
        >
          🏁 Kết thúc show & Xem báo cáo
        </button>
      </div>
    </div>

    <!-- BAND EXHAUSTION WARNING BANNER -->
    <div v-if="exhaustedWarnings.length > 0" class="exhaustion-warning-box">
      <div v-for="(warn, idx) in exhaustedWarnings" :key="idx" class="exhaustion-row">
        🚨 <strong>Cảnh báo giới hạn vật lý:</strong> {{ warn }}
      </div>
    </div>

    <!-- MC AUTO TALKOVER / REVERB DUCKING BAR -->
    <div class="talkover-card">
      <div class="talkover-info">
        <span class="talkover-title">🎙️ Trợ lý MC phát biểu (Tự ngắt tiếng Vang/Reverb khi MC nói)</span>
        <span class="talkover-sub">
          Giúp tiếng MC rõ chữ, không bị nhòe đuôi reverb; tự mở lại vang khi ca sĩ hát.
        </span>
      </div>
      <div class="talkover-controls">
        <label class="talkover-mic-label">
          Mic MC:
          <select
            :value="talkoverMicChannel || 1"
            class="talkover-select"
            @change="emit('setTalkoverConfig', !!talkoverEnabled, Number(($event.target as HTMLSelectElement).value))"
          >
            <option v-for="m in totalChannels" :key="m" :value="m">Mic {{ m }}</option>
          </select>
        </label>
        <button
          type="button"
          class="btn-talkover-toggle"
          :class="{ active: talkoverEnabled }"
          @click="emit('setTalkoverConfig', !talkoverEnabled, talkoverMicChannel || 1)"
        >
          {{ talkoverEnabled ? '✅ ĐANG BẬT TỰ NGẮT VANG' : 'Bật tự ngắt vang cho MC' }}
        </button>
        <span v-if="talkoverEnabled && talkoverIsDucked" class="ducked-live-pill">
          🔇 Đang dìm Vang (MC đang nói)
        </span>
      </div>
    </div>

    <!-- COMPACT LIVE CHANNEL STRIP -->
    <div class="live-strip-box">
      <div class="live-strip-header">
        <span class="events-title">🎛️ Bảng Giám Sát Kênh Trực Tiếp (Chống vỡ tiếng · Khóa EQ Nhạc · Nhả từng Mic)</span>
        <button
          type="button"
          class="btn-strip-filter"
          @click="showAllChannels = !showAllChannels"
        >
          {{ showAllChannels ? 'Thu gọn (Chỉ hiện kênh chính)' : `Xem tất cả ${totalChannels} kênh` }}
        </button>
      </div>

      <div class="live-strip-grid">
        <div
          v-for="ch in liveChannelRows"
          :key="ch.chNum"
          class="live-ch-row"
          :class="{
            'ch-clip': ch.isClip,
            'ch-muted': ch.isMuted
          }"
        >
          <div class="live-ch-left">
            <span class="live-ch-name">{{ ch.label }}</span>
            <button
              type="button"
              class="live-role-pill"
              :class="ch.whitelisted ? 'pill-mic' : 'pill-music'"
              @click="emit('toggleWhitelist', ch.chNum)"
            >
              {{ ch.whitelisted ? '🎤 Mic' : '🎵 Nhạc (Khóa EQ)' }}
            </button>
          </div>

          <div class="live-ch-meter-wrap">
            <div class="live-ch-meter-track">
              <div class="live-ch-meter-fill" :style="{ width: `${ch.fillPct}%` }" />
            </div>
            <span v-if="ch.isClip" class="clip-badge">⚠️ VỠ TIẾNG! Giảm Gain</span>
          </div>

          <div class="live-ch-right">
            <span v-if="ch.notchesCount > 0" class="notch-count-pill">
              Đang cắt {{ ch.notchesCount }} điểm
              <template v-if="ch.latestNotchFreq">({{ formatFrequency(ch.latestNotchFreq) }})</template>
            </span>
            <span v-else class="notch-clean-pill">Nguyên bản</span>

            <button
              v-if="ch.notchesCount > 0"
              type="button"
              class="btn-release-single"
              @click="emit('releaseChannelNotches', ch.chNum)"
            >
              ↩️ Nhả riêng mic này
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- PENDING PROPOSALS (IF IN SEMI-AUTO MODE) -->
    <div v-if="pendingProposals.length > 0" class="proposals-alert-box">
      <div class="proposals-header">
        <span class="alert-icon">⚠️</span>
        <span class="alert-title">Có {{ pendingProposals.length }} điểm hú đang chờ bạn đồng ý:</span>
      </div>
      <div
        v-for="prop in pendingProposals"
        :key="prop.id"
        class="proposal-item-card"
      >
        <div>
          <strong>{{ formatFriendlyTarget(prop) }}</strong> có nguy cơ hú ở
          <strong>{{ formatFrequency(prop.freq_hz) }}</strong>
          <span v-if="extractSuspectHint(prop.reason)">
            — {{ extractSuspectHint(prop.reason) }}
          </span>.
        </div>
        <div class="proposal-actions">
          <button
            type="button"
            class="btn-approve"
            @click="emit('approveProposal', prop.id)"
          >
            Đồng ý dập
          </button>
          <button
            type="button"
            class="btn-reject"
            @click="emit('rejectProposal', prop.id)"
          >
            Bỏ qua
          </button>
        </div>
      </div>
    </div>

    <!-- RECENT MESSAGES -->
    <div class="recent-events-box">
      <span class="events-title">Nhật ký hoạt động gần nhất:</span>
      <div v-if="latestLogs.length === 0" class="no-events">
        Chưa có sự cố nào. Hệ thống đang bảo vệ bình thường.
      </div>
      <ul v-else class="events-list">
        <li
          v-for="log in latestLogs"
          :key="log.id"
          class="event-row"
        >
          <span class="event-time">[{{ log.time }}]</span>
          <span class="event-text">{{ translateEventMessage(log) }}</span>
        </li>
      </ul>
    </div>
  </section>
</template>

<style scoped>
.live-show-card {
  align-items: center;
  text-align: center;
  padding: 40px 30px;
}

.status-orb-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}

.status-orb {
  width: 140px;
  height: 140px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  transition: all 0.3s ease;
}

.orb-green .status-orb {
  background: radial-gradient(circle, #10b981 0%, #064e3b 80%);
  box-shadow: 0 0 40px rgba(16, 185, 129, 0.5);
}

.orb-amber .status-orb {
  background: radial-gradient(circle, #f59e0b 0%, #78350f 80%);
  box-shadow: 0 0 50px rgba(245, 158, 11, 0.7);
  animation: pulse-amber 1s infinite alternate;
}

@keyframes pulse-amber {
  from { transform: scale(1); }
  to { transform: scale(1.06); }
}

.orb-red .status-orb {
  background: radial-gradient(circle, #ef4444 0%, #7f1d1d 80%);
  box-shadow: 0 0 50px rgba(239, 68, 68, 0.8);
}

.orb-badge {
  font-size: 16px;
  font-weight: 900;
  color: #fff;
  letter-spacing: 0.5px;
}

.status-headline {
  font-size: 26px;
  font-weight: 900;
  margin: 0;
}

.status-subline {
  font-size: 15px;
  color: var(--text-dim);
  max-width: 600px;
  margin: 0;
}

.panic-wrapper {
  width: 100%;
  max-width: 650px;
  margin: 20px auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}

.giant-panic-btn {
  width: 100%;
  background: linear-gradient(135deg, #dc2626, #991b1b);
  border: 2px solid #f87171;
  border-radius: 14px;
  padding: 20px 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 18px;
  color: #fff;
  cursor: pointer;
  box-shadow: 0 8px 30px rgba(220, 38, 38, 0.5);
  transition: transform 0.1s ease, box-shadow 0.2s ease;
}

.giant-panic-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 12px 40px rgba(220, 38, 38, 0.7);
}

.giant-panic-btn:active {
  transform: translateY(1px);
}

.panic-icon {
  font-size: 36px;
}

.panic-text-col {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
}

.panic-main-text {
  font-size: 20px;
  font-weight: 900;
  letter-spacing: 0.5px;
}

.panic-hint-text {
  font-size: 12px;
  opacity: 0.85;
}

.easy-undo-panic-btn {
  background: var(--bg-tertiary);
  border: 1px solid var(--accent-cyan);
  color: var(--accent-cyan);
  border-radius: 8px;
  padding: 8px 16px;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  transition: background 0.15s ease;
}

.easy-undo-panic-btn:hover {
  background: rgba(56, 189, 248, 0.15);
}

.panic-explainer {
  font-size: 12px;
  color: var(--text-dim);
}

.show-controls-row {
  width: 100%;
  max-width: 650px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 14px 20px;
  flex-wrap: wrap;
  gap: 14px;
}

.control-box {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}

.control-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-dim);
}

.mode-toggles {
  display: flex;
  gap: 8px;
}

.mode-btn {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  color: var(--text-dim);
  border-radius: 6px;
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.mode-btn.active {
  background: rgba(56, 189, 248, 0.15);
  border-color: var(--accent-cyan);
  color: var(--accent-cyan);
}

.btn-end-show {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-highlight);
  color: var(--text-main);
  border-radius: 8px;
  padding: 10px 16px;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}

.proposals-alert-box {
  width: 100%;
  max-width: 650px;
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid var(--accent-amber);
  border-radius: 10px;
  padding: 14px 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  text-align: left;
}

.proposals-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 800;
  color: var(--accent-amber);
}

.proposal-item-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--bg-primary);
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 13px;
}

.proposal-actions {
  display: flex;
  gap: 8px;
}

.btn-approve {
  background: var(--accent-green);
  color: #000;
  border: none;
  font-weight: 800;
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 4px;
  cursor: pointer;
}

.btn-reject {
  background: var(--bg-tertiary);
  color: var(--text-dim);
  border: 1px solid var(--border-color);
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 4px;
  cursor: pointer;
}

.recent-events-box {
  width: 100%;
  max-width: 650px;
  text-align: left;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 14px 18px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.events-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-dim);
}

.events-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.event-row {
  display: flex;
  gap: 10px;
  font-size: 13px;
}

.event-time {
  color: var(--text-muted);
  font-family: var(--font-mono);
}

.event-text {
  color: var(--text-secondary);
}

.no-events {
  font-size: 13px;
  color: var(--text-muted);
  font-style: italic;
}

.exhaustion-warning-box {
  width: 100%;
  max-width: 650px;
  background: rgba(239, 68, 68, 0.14);
  border: 1px solid var(--accent-red);
  border-radius: 10px;
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  text-align: left;
  color: #fecaca;
  font-size: 13px;
}

.talkover-card {
  width: 100%;
  max-width: 650px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 14px 18px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  text-align: left;
}

.talkover-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
  min-width: 220px;
}

.talkover-title {
  font-size: 13px;
  font-weight: 800;
  color: var(--text-main);
}

.talkover-sub {
  font-size: 12px;
  color: var(--text-dim);
}

.talkover-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.talkover-mic-label {
  font-size: 12px;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: 6px;
}

.talkover-select {
  background: var(--bg-tertiary);
  color: var(--text-main);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 4px 8px;
  font-size: 12px;
}

.btn-talkover-toggle {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  color: var(--text-secondary);
  border-radius: 8px;
  padding: 8px 14px;
  font-size: 12px;
  font-weight: 800;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-talkover-toggle.active {
  background: rgba(16, 185, 129, 0.18);
  border-color: var(--accent-green);
  color: #34d399;
}

.ducked-live-pill {
  background: rgba(245, 158, 11, 0.2);
  border: 1px solid var(--accent-amber);
  color: #fde68a;
  font-size: 11px;
  font-weight: 800;
  padding: 4px 8px;
  border-radius: 6px;
}

.live-strip-box {
  width: 100%;
  max-width: 650px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 14px 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  text-align: left;
}

.live-strip-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.btn-strip-filter {
  background: none;
  border: 1px solid var(--border-color);
  color: var(--accent-cyan);
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
}

.live-strip-grid {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.live-ch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 8px 12px;
  flex-wrap: wrap;
}

.live-ch-row.ch-clip {
  border-color: var(--accent-red);
  background: rgba(239, 68, 68, 0.08);
}

.live-ch-row.ch-muted {
  opacity: 0.55;
}

.live-ch-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 150px;
}

.live-ch-name {
  font-size: 13px;
  font-weight: 800;
}

.live-role-pill {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 6px;
  cursor: pointer;
  border: 1px solid transparent;
}

.pill-mic {
  background: rgba(16, 185, 129, 0.12);
  border-color: rgba(16, 185, 129, 0.35);
  color: #34d399;
}

.pill-music {
  background: rgba(245, 158, 11, 0.15);
  border-color: var(--accent-amber);
  color: #fbbf24;
}

.live-ch-meter-wrap {
  flex: 1;
  min-width: 120px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.live-ch-meter-track {
  flex: 1;
  height: 8px;
  background: var(--bg-secondary);
  border-radius: 4px;
  overflow: hidden;
  border: 1px solid var(--border-color);
}

.live-ch-meter-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--accent-green), var(--accent-amber) 75%, var(--accent-red) 95%);
  transition: width 0.1s linear;
}

.clip-badge {
  background: var(--accent-red);
  color: #fff;
  font-size: 10px;
  font-weight: 800;
  padding: 2px 6px;
  border-radius: 4px;
  white-space: nowrap;
}

.live-ch-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.notch-count-pill {
  font-size: 11px;
  font-weight: 700;
  color: var(--accent-amber);
}

.notch-clean-pill {
  font-size: 11px;
  color: var(--text-muted);
}

.btn-release-single {
  background: var(--bg-tertiary);
  border: 1px solid var(--accent-cyan);
  color: var(--accent-cyan);
  border-radius: 6px;
  padding: 3px 8px;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
}
</style>
