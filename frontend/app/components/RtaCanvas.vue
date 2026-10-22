<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import type { ActiveNotch } from '~/composables/useCompanionSocket'
import { useI18n } from '~/composables/useI18n'

const { t } = useI18n()

const props = defineProps<{
  rtaBins: number[]
  peakHoldBins: number[]
  activeNotches: ActiveNotch[]
}>()

const canvasRef = ref<HTMLCanvasElement | null>(null)

function renderCanvas() {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const w = canvas.width
  const h = canvas.height
  ctx.clearRect(0, 0, w, h)

  // 1. dB Grid
  ctx.strokeStyle = '#1a2230'
  ctx.lineWidth = 1
  for (let db = -10; db >= -90; db -= 20) {
    const y = h * (-db / 90.0)
    ctx.beginPath()
    ctx.moveTo(0, y)
    ctx.lineTo(w, y)
    ctx.stroke()
    ctx.fillStyle = '#475569'
    ctx.font = '9px monospace'
    ctx.fillText(`${db}dB`, 4, y - 3)
  }

  // 2. Real-time RTA
  if (props.rtaBins.length > 0) {
    ctx.beginPath()
    ctx.strokeStyle = '#38bdf8'
    ctx.lineWidth = 2
    for (let i = 0; i < props.rtaBins.length; i++) {
      const x = (i / (props.rtaBins.length - 1)) * w
      const norm = Math.max(0, Math.min(1, (props.rtaBins[i] + 90.0) / 90.0))
      const y = h * (1.0 - norm)
      if (i === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    }
    ctx.stroke()
  }

  // 3. Peak Hold
  if (props.peakHoldBins.length > 0) {
    ctx.beginPath()
    ctx.strokeStyle = 'rgba(245, 158, 11, 0.7)'
    ctx.lineWidth = 1.5
    for (let i = 0; i < props.peakHoldBins.length; i++) {
      const x = (i / (props.peakHoldBins.length - 1)) * w
      const norm = Math.max(0, Math.min(1, (props.peakHoldBins[i] + 90.0) / 90.0))
      const y = h * (1.0 - norm)
      if (i === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    }
    ctx.stroke()
  }

  // 4. Active Notches Markers
  for (const notch of props.activeNotches) {
    const freq = notch.freq_hz
    const logPos = (Math.log10(freq) - Math.log10(20)) / (Math.log10(20000) - Math.log10(20))
    const x = Math.max(0, Math.min(w, logPos * w))

    ctx.strokeStyle = 'rgba(239, 68, 68, 0.8)'
    ctx.lineWidth = 2
    ctx.setLineDash([4, 3])
    ctx.beginPath()
    ctx.moveTo(x, 0)
    ctx.lineTo(x, h)
    ctx.stroke()
    ctx.setLineDash([])

    // Notch label
    ctx.fillStyle = '#ef4444'
    ctx.font = '10px monospace'
    ctx.fillText(`-${Math.abs(notch.gain_db).toFixed(0)}dB`, x + 3, 20)
  }
}

onMounted(() => {
  renderCanvas()
})

watch(() => [props.rtaBins, props.activeNotches], () => {
  renderCanvas()
}, { deep: true })
</script>

<template>
  <div class="c-card">
    <div class="c-card-title">
      <span>{{ t('rta.title') }}</span>
      <span class="rta-source">{{ t('rta.source') }}</span>
    </div>
    <div class="rta-container">
      <canvas ref="canvasRef" width="900" height="260" />
      <div class="rta-legend">
        <div class="legend-item"><div class="legend-color bg-cyan" /> {{ t('rta.instant') }}</div>
        <div class="legend-item"><div class="legend-color bg-amber" /> {{ t('rta.peak') }}</div>
        <div class="legend-item"><div class="legend-color bg-red" /> {{ t('rta.notchZone') }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.rta-source {
  font-family: var(--font-mono);
  color: var(--accent-cyan);
}

.rta-container {
  position: relative;
  width: 100%;
  height: 260px;
  background: #07090e;
  border-radius: 6px;
  overflow: hidden;
  border: 1px solid #1a2230;
}

canvas {
  width: 100%;
  height: 100%;
  display: block;
}

.rta-legend {
  position: absolute;
  top: 8px;
  right: 8px;
  display: flex;
  gap: 10px;
  font-size: 11px;
  font-family: var(--font-mono);
  background: rgba(11, 14, 20, 0.7);
  padding: 4px 8px;
  border-radius: 4px;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.legend-color {
  width: 10px;
  height: 3px;
  border-radius: 1px;
}

.bg-cyan { background: #38bdf8; }
.bg-amber { background: #f59e0b; }
.bg-red { background: #ef4444; }
</style>
