<script setup lang="ts">
import { ref } from 'vue'
import type { DiscoveredMixer, AudioDeviceItem } from '~/composables/useCompanionSocket'

const props = defineProps<{
  isScanning: boolean
  discoveredMixers: DiscoveredMixer[]
  audioDevices?: AudioDeviceItem[]
  selectedAudioDevice?: string
  connectingIp: string | null
  connectError: string
}>()

const emit = defineEmits<{
  (e: 'scan'): void
  (e: 'connect', ip: string, model?: string, audioDevice?: string): void
  (e: 'selectAudioDevice', deviceName: string): void
  (e: 'startDemo'): void
}>()

const check1 = ref(false)
const check2 = ref(false)
const check3 = ref(false)
const manualIp = ref('')
const showManualIp = ref(false)

function submitManualIp() {
  const ip = manualIp.value.trim()
  if (!ip) return
  emit('connect', ip, undefined, props.selectedAudioDevice)
}
</script>

<template>
  <section class="easy-step-card">
    <div class="easy-step-header">
      <h2>Bước 1: Kết Nối Với Bàn Mixer</h2>
      <p class="easy-step-desc">
        Phần mềm tự động dò tìm các bàn mixer Behringer XR / Midas MR trong cùng mạng Wi-Fi hoặc cáp LAN.
      </p>
    </div>

    <div v-if="connectError" class="easy-error-banner">
      ⚠️ {{ connectError }}
    </div>

    <!-- Scanning Indicator -->
    <div v-if="isScanning" class="scanning-box">
      <div class="spinner" />
      <p class="scan-text">Đang quét tìm bàn mixer trong mạng LAN…</p>
    </div>

    <!-- Discovered List -->
    <div v-else-if="discoveredMixers.length > 0" class="discovered-section">
      <p class="section-label">Đã tìm thấy thiết bị:</p>
      <div class="mixer-cards-grid">
        <div
          v-for="mix in discoveredMixers"
          :key="mix.ip"
          class="mixer-found-card"
        >
          <div class="mixer-info">
            <span class="mixer-badge">{{ mix.model }}</span>
            <span class="mixer-name">{{ mix.name || 'Bàn Mixer' }}</span>
            <span class="mixer-ip">Địa chỉ IP: {{ mix.ip }}</span>
          </div>
          <button
            type="button"
            class="easy-btn-primary"
            :disabled="connectingIp === mix.ip"
            @click="emit('connect', mix.ip, mix.model, props.selectedAudioDevice)"
          >
            {{ connectingIp === mix.ip ? 'Đang kết nối…' : 'KẾT NỐI NGAY' }}
          </button>
        </div>
      </div>
      <button type="button" class="easy-btn-secondary" @click="emit('scan')">
        🔄 Quét lại mạng
      </button>
    </div>

    <!-- Not Found Checklist -->
    <div v-else class="not-found-section">
      <div class="alert-box-warning">
        <h3>⚠️ Chưa tìm thấy bàn mixer nào trong mạng</h3>
        <p>Vui lòng kiểm tra nhanh 3 điều sau:</p>
        <ul class="checklist">
          <li :class="{ checked: check1 }" @click="check1 = !check1">
            <input type="checkbox" :checked="check1" />
            <span>1. Bàn mixer đã bật nguồn và đèn mạng Ethernet / Wi-Fi sáng xanh?</span>
          </li>
          <li :class="{ checked: check2 }" @click="check2 = !check2">
            <input type="checkbox" :checked="check2" />
            <span>2. Máy tính và mixer đã kết nối chung một bộ phát Wi-Fi hoặc cắm dây LAN?</span>
          </li>
          <li :class="{ checked: check3 }" @click="check3 = !check3">
            <input type="checkbox" :checked="check3" />
            <span>3. Tránh dùng Wi-Fi khách sạn / quán cà phê công cộng (vì chặn nhìn thấy nhau). Nên dùng 1 cục phát Wi-Fi riêng cho show.</span>
          </li>
        </ul>
      </div>

      <div class="actions-row">
        <button type="button" class="easy-btn-primary" @click="emit('scan')">
          🔄 Thử quét lại
        </button>
        <button type="button" class="btn-demo" @click="emit('startDemo')">
          🎮 Thử không cần mixer (Chạy Demo)
        </button>
        <button type="button" class="easy-btn-text" @click="showManualIp = !showManualIp">
          {{ showManualIp ? 'Ẩn nhập tay' : 'Nhập địa chỉ IP thủ công' }}
        </button>
      </div>

      <!-- Manual IP Box -->
      <div v-if="showManualIp" class="manual-ip-box">
        <label for="manual-ip-input">Địa chỉ IP bàn mixer (Tự động nhận diện dòng máy XR12/XR16/XR18/MR12/MR18):</label>
        <div class="ip-input-row">
          <input
            id="manual-ip-input"
            v-model="manualIp"
            type="text"
            placeholder="Ví dụ: 192.168.1.10"
            class="c-input"
            @keyup.enter="submitManualIp"
          />
          <button
            type="button"
            class="easy-btn-secondary"
            :disabled="!manualIp.trim()"
            @click="submitManualIp"
          >
            Kết nối
          </button>
        </div>
      </div>
    </div>

    <!-- Optional USB Soundcard Selector (P3.1) -->
    <div v-if="audioDevices && audioDevices.length > 0" class="usb-device-box">
      <label for="usb-device-select" class="section-label">
        🔌 Cổng thu âm USB (Tùy chọn cho XR18/MR18 khi máy tính cắm nhiều soundcard):
      </label>
      <select
        id="usb-device-select"
        :value="selectedAudioDevice || ''"
        class="c-input"
        @change="emit('selectAudioDevice', ($event.target as HTMLSelectElement).value)"
      >
        <option value="">Tự động nhận diện soundcard mixer (Khuyên dùng)</option>
        <option
          v-for="dev in audioDevices"
          :key="dev.name"
          :value="dev.name"
        >
          {{ dev.name }} ({{ dev.max_channels }} kênh){{ dev.is_default ? ' — Mặc định' : '' }}
        </option>
      </select>
    </div>
  </section>
</template>

<style scoped>
.scanning-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  gap: 16px;
}

.spinner {
  width: 44px;
  height: 44px;
  border: 4px solid var(--border-color);
  border-top-color: var(--accent-cyan);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.scan-text {
  font-size: 16px;
  color: var(--text-dim);
}

.discovered-section,
.not-found-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.section-label {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-secondary);
}

.mixer-cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 16px;
}

.mixer-found-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-highlight);
  border-radius: 10px;
  padding: 18px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.mixer-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.mixer-badge {
  background: rgba(56, 189, 248, 0.15);
  color: var(--accent-cyan);
  font-weight: 800;
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 4px;
  width: fit-content;
}

.mixer-name {
  font-size: 16px;
  font-weight: 700;
}

.mixer-ip {
  font-size: 12px;
  color: var(--text-dim);
}

.alert-box-warning {
  background: rgba(245, 158, 11, 0.08);
  border: 1px solid rgba(245, 158, 11, 0.3);
  border-radius: 10px;
  padding: 18px 22px;
}

.alert-box-warning h3 {
  color: var(--accent-amber);
  font-size: 16px;
  font-weight: 800;
  margin-bottom: 8px;
}

.checklist {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 12px;
}

.checklist li {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  color: var(--text-secondary);
  cursor: pointer;
  user-select: none;
}

.checklist li.checked {
  color: var(--text-main);
  text-decoration: line-through;
  opacity: 0.6;
}

.actions-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: center;
}

.btn-demo {
  background: var(--bg-tertiary);
  color: var(--accent-cyan);
  border: 1px solid var(--accent-cyan);
  border-radius: 8px;
  padding: 10px 18px;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
}

.manual-ip-box {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  padding: 14px 18px;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.ip-input-row {
  display: flex;
  gap: 10px;
}

.usb-device-box {
  margin-top: 16px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  padding: 12px 16px;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
</style>
