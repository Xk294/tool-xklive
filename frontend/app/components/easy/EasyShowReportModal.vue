<script setup lang="ts">
import { computed } from 'vue'
import type { MixerConnectionStatus } from '~/composables/useCompanionSocket'

const props = defineProps<{
  isOpen: boolean
  showDurationMinutes: number
  activeNotchesCount: number
  mixerModel: string
  mixerStatus: MixerConnectionStatus
  isDemoMode: boolean
  hadConnectionDrop: boolean
}>()

const emit = defineEmits<{
  (e: 'export', format: 'json' | 'csv'): void
  (e: 'close'): void
}>()

const isCurrentlyDisconnected = computed(
  () => !props.isDemoMode && (props.mixerStatus === 'DISCONNECTED' || props.mixerStatus === 'RECONNECTING')
)

const reportHeader = computed(() => {
  if (isCurrentlyDisconnected.value) {
    return '⚠️ BÁO CÁO KẾT THÚC (ĐANG MẤT KẾT NỐI MIXER)'
  }
  if (props.isDemoMode) {
    return '🎮 BÁO CÁO PHIÊN CHẠY THỬ (DEMO)'
  }
  return '🎉 BÁO CÁO SHOW HOÀN TẤT'
})

const reportSummary = computed(() => {
  if (isCurrentlyDisconnected.value) {
    return 'Kết nối điều khiển tới bàn mixer hiện đang bị gián đoạn (âm thanh phần cứng trên sân khấu vẫn hoạt động độc lập). Dưới đây là số liệu ghi nhận:'
  }
  if (props.hadConnectionDrop) {
    return 'Show đã kết thúc (có ghi nhận gián đoạn kết nối mạng tạm thời trong phiên). Dưới đây là kết quả bảo vệ:'
  }
  return 'Show đã kết thúc an toàn! Dưới đây là kết quả bảo vệ của hệ thống:'
})

const reportFooter = computed(() => {
  if (isCurrentlyDisconnected.value) {
    return 'Lưu ý: Vui lòng kiểm tra lại cáp mạng LAN / Wi-Fi nếu cần tiếp tục điều khiển PEQ trên mixer.'
  }
  if (props.isDemoMode) {
    return 'Phiên mô phỏng hoàn tất. Kết nối bàn mixer thật ở Bước 1 khi vào sự kiện thực tế.'
  }
  if (props.hadConnectionDrop) {
    return 'Luồng âm thanh trực tiếp trên mixer luôn tách biệt an toàn ngay cả khi mạng điều khiển chập chờn.'
  }
  return 'Âm thanh được bảo vệ hoàn toàn không gián đoạn bởi Auto Sound Companion.'
})
</script>

<template>
  <div v-if="isOpen" class="report-modal-overlay" @click.self="emit('close')">
    <div class="report-modal-card">
      <h2 :class="{ 'text-amber': isCurrentlyDisconnected }">{{ reportHeader }}</h2>
      <p class="report-summary-text">
        {{ reportSummary }}
      </p>

      <div class="report-stats-grid">
        <div class="stat-card">
          <span class="stat-value">{{ showDurationMinutes }}</span>
          <span class="stat-label">Phút chạy show</span>
        </div>
        <div class="stat-card">
          <span class="stat-value">{{ activeNotchesCount }}</span>
          <span class="stat-label">Điểm chống hú đang bật</span>
        </div>
        <div class="stat-card">
          <span class="stat-value">{{ isDemoMode ? 'XR18 (Demo)' : mixerModel }}</span>
          <span class="stat-label">Mixer điều khiển</span>
        </div>
      </div>

      <p class="report-thanks">
        {{ reportFooter }}
      </p>

      <div class="report-actions">
        <button
          type="button"
          class="easy-btn-primary"
          @click="emit('export', 'json')"
        >
          📥 Xuất file báo cáo
        </button>
        <button
          type="button"
          class="easy-btn-secondary"
          @click="emit('close')"
        >
          Đóng
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.report-modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.75);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 20px;
}

.report-modal-card {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 14px;
  padding: 30px;
  max-width: 500px;
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 18px;
  text-align: center;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.6);
}

.report-modal-card h2 {
  font-size: 20px;
  font-weight: 900;
  color: var(--accent-cyan);
}

.report-summary-text {
  font-size: 14px;
  color: var(--text-secondary);
}

.report-stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}

.stat-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  padding: 14px 10px;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stat-value {
  font-size: 20px;
  font-weight: 900;
  color: var(--accent-green);
}

.stat-label {
  font-size: 11px;
  color: var(--text-dim);
}

.report-thanks {
  font-size: 13px;
  color: var(--text-dim);
}

.report-actions {
  display: flex;
  gap: 12px;
  justify-content: center;
}
</style>
