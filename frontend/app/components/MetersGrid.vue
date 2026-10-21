<script setup lang="ts">
defineProps<{
  meters: number[]
}>()
</script>

<template>
  <div class="c-card">
    <div class="c-card-title">
      <span>Mức Tín Hiệu 16 Kênh Micro (Analog In / Pre-EQ)</span>
      <span class="meter-hint">🔒: Đang tạm khóa chỉnh tay</span>
    </div>
    <div class="meters-grid">
      <div
        v-for="ch in 16"
        :key="ch"
        class="meter-col"
      >
        <div class="meter-bar-bg">
          <div
            class="meter-fill"
            :style="{ height: Math.min(100, Math.max(0, (meters[ch - 1] || 0) * 100)) + '%' }"
          />
        </div>
        <span class="meter-label">{{ ch }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.meter-hint {
  font-size: 11px;
  color: var(--text-dim);
}

.meters-grid {
  display: grid;
  grid-template-columns: repeat(16, 1fr);
  gap: 4px;
  height: 70px;
  background: #080a0f;
  padding: 6px;
  border-radius: 6px;
  border: 1px solid var(--border-color);
}

.meter-col {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  height: 100%;
}

.meter-bar-bg {
  width: 100%;
  height: 50px;
  background: #131722;
  border-radius: 2px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
}

.meter-fill {
  width: 100%;
  background: linear-gradient(to top, var(--accent-green), var(--accent-amber) 75%, var(--accent-red) 90%);
  transition: height 0.08s ease;
}

.meter-label {
  font-size: 9px;
  font-family: var(--font-mono);
  color: var(--text-dim);
  margin-top: 3px;
}
</style>
