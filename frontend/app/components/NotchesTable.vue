<script setup lang="ts">
import type { ActiveNotch } from '~/composables/useCompanionSocket'

defineProps<{
  notches: ActiveNotch[]
}>()

const emit = defineEmits<{
  (e: 'release', channel: number, band: number, target: string, bus?: number | null): void
  (e: 'releaseAll'): void
}>()
</script>

<template>
  <div class="c-card">
    <div class="c-card-title">
      <span>Danh Sách Bộ Lọc Notch Đang Hoạt Động</span>
      <button class="c-btn-small" @click="emit('releaseAll')">Nhả Tất Cả</button>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th>ĐÍCH</th>
          <th>TẦN SỐ</th>
          <th>GAIN</th>
          <th>BAND</th>
          <th>TUỔI</th>
          <th>TRẠNG THÁI</th>
          <th>THAO TÁC</th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="notches.length === 0">
          <td colspan="7" class="table-empty">Chưa có notch nào được kích hoạt</td>
        </tr>
        <tr
          v-for="n in notches"
          :key="`${n.target}_${n.channel}_${n.bus}_${n.band}`"
        >
          <td><b>{{ n.target === 'bus' ? `Bus ${n.bus}` : `Kênh ${n.channel}` }}</b></td>
          <td>{{ n.freq_hz.toFixed(1) }} Hz</td>
          <td class="notch-gain">{{ n.gain_db.toFixed(1) }} dB</td>
          <td>Band {{ n.band }}</td>
          <td>{{ n.age_s }}s</td>
          <td>{{ n.step_count > 1 ? `Bước ${n.step_count}` : 'Ổn định' }}</td>
          <td>
            <button
              class="c-btn-small"
              @click="emit('release', n.channel, n.band, n.target, n.bus)"
            >
              Nhả
            </button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
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
