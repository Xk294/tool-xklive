<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import type { ActiveNotch } from '~/composables/useCompanionSocket'
import { useI18n } from '~/composables/useI18n'

const { t } = useI18n()

const props = defineProps<{
  rtaBins: number[]
  peakHoldBins: number[]
  activeNotches: ActiveNotch[]
}>()

const emit = defineEmits<{
  (e: 'selectFreq', freq: number): void
}>()

type RtaView = 'curve' | 'bars' | 'waterfall'
type DecaySpeed = 'fast' | 'med' | 'slow' | 'peak'

const currentView = ref<RtaView>('curve')
const decaySpeed = ref<DecaySpeed>('fast')
const sensitivityThreshold = ref(-36) // dBFS threshold line

const canvasRef = ref<HTMLCanvasElement | null>(null)
const waterfallCanvasRef = ref<HTMLCanvasElement | null>(null)

// Mouse cursor tracking
const isHovering = ref(false)
const hoverX = ref(0)
const hoverY = ref(0)
const hoverFreq = ref(1000)
const hoverDb = ref(-60)

// Musical Pitch lookup
const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

const hoverNote = computed(() => {
  if (hoverFreq.value <= 20) return '—'
  const midiNum = 12 * Math.log2(hoverFreq.value / 440) + 69
  const roundedMidi = Math.round(midiNum)
  const cents = Math.round((midiNum - roundedMidi) * 100)
  const noteIndex = ((roundedMidi % 12) + 12) % 12
  const octave = Math.floor(roundedMidi / 12) - 1
  const sign = cents >= 0 ? `+${cents}` : `${cents}`
  return `${NOTE_NAMES[noteIndex]}${octave} (${sign}c)`
})

// Standard 31 ISO 1/3 Octave Frequencies
const ISO_31_FREQS = [
  20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160,
  200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600,
  2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000, 20000
]

// Grid frequencies for logarithmic scale
const GRID_FREQS = [30, 60, 120, 250, 500, 1000, 2000, 4000, 8000, 16000]

function freqToX(freq: number, width: number): number {
  const minLog = Math.log10(20)
  const maxLog = Math.log10(20000)
  const curLog = Math.log10(Math.max(20, Math.min(20000, freq)))
  return ((curLog - minLog) / (maxLog - minLog)) * width
}

function xToFreq(x: number, width: number): number {
  const norm = Math.max(0, Math.min(1, x / width))
  return 20 * Math.pow(1000, norm)
}

function dbToY(db: number, height: number): number {
  const norm = Math.max(0, Math.min(1, (db + 90.0) / 90.0))
  return height * (1.0 - norm)
}

function yToDb(y: number, height: number): number {
  const norm = 1.0 - Math.max(0, Math.min(1, y / height))
  return -90 + norm * 90
}

// Waterfall history buffer (thermal map) and smoothed spectrum buffer
const WATERFALL_ROWS = 140
let waterfallHistory: number[][] = []
let smoothedBins: number[] = []

function getThermalColor(valDb: number): string {
  // Normalize -90dB (0) to 0dB (1)
  const norm = Math.max(0, Math.min(1, (valDb + 85) / 85))
  if (norm < 0.25) {
    const t = norm / 0.25
    return `rgb(6, 12, ${Math.floor(20 + t * 120)})`
  } else if (norm < 0.5) {
    const t = (norm - 0.25) / 0.25
    return `rgb(0, ${Math.floor(t * 200)}, ${Math.floor(140 + t * 80)})`
  } else if (norm < 0.75) {
    const t = (norm - 0.5) / 0.25
    return `rgb(${Math.floor(t * 240)}, ${Math.floor(200 + t * 40)}, 20)`
  } else {
    const t = (norm - 0.75) / 0.25
    return `rgb(${Math.floor(240 + t * 15)}, ${Math.floor(240 * (1 - t))}, ${Math.floor(30 * (1 - t))})`
  }
}

function handleMouseMove(e: MouseEvent) {
  const canvas = canvasRef.value
  if (!canvas) return
  const rect = canvas.getBoundingClientRect()
  const x = (e.clientX - rect.left) * (canvas.width / rect.width)
  const y = (e.clientY - rect.top) * (canvas.height / rect.height)
  hoverX.value = x
  hoverY.value = y
  hoverFreq.value = Math.round(xToFreq(x, canvas.width))
  hoverDb.value = Math.round(yToDb(y, canvas.height) * 10) / 10
  isHovering.value = true
}

function handleMouseLeave() {
  isHovering.value = false
}

function handleCanvasClick() {
  if (hoverFreq.value > 20) {
    emit('selectFreq', hoverFreq.value)
  }
}

function renderCanvas() {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const w = canvas.width
  const h = canvas.height
  ctx.clearRect(0, 0, w, h)

  // 1. Draw dB Horizontal Grid
  ctx.strokeStyle = '#151d28'
  ctx.lineWidth = 1
  for (let db = 0; db >= -90; db -= 15) {
    const y = dbToY(db, h)
    ctx.beginPath()
    ctx.moveTo(0, y)
    ctx.lineTo(w, y)
    ctx.stroke()

    ctx.fillStyle = db === 0 ? '#ef4444' : '#475569'
    ctx.font = '10px monospace'
    ctx.fillText(`${db}dB`, 6, y - 4)
  }

  // 2. Draw Frequency Vertical Log Grid & Labels
  for (const f of GRID_FREQS) {
    const x = freqToX(f, w)
    ctx.strokeStyle = f === 1000 ? '#263548' : '#141c28'
    ctx.beginPath()
    ctx.moveTo(x, 0)
    ctx.lineTo(x, h)
    ctx.stroke()

    ctx.fillStyle = '#64748b'
    ctx.font = '10px monospace'
    const label = f >= 1000 ? `${f / 1000}k` : `${f}`
    ctx.fillText(label, x + 3, h - 8)
  }

  // 3. Sensitivity Threshold Line
  const threshY = dbToY(sensitivityThreshold.value, h)
  ctx.strokeStyle = 'rgba(239, 68, 68, 0.45)'
  ctx.lineWidth = 1
  ctx.setLineDash([4, 4])
  ctx.beginPath()
  ctx.moveTo(0, threshY)
  ctx.lineTo(w, threshY)
  ctx.stroke()
  ctx.setLineDash([])
  ctx.fillStyle = '#ef4444'
  ctx.font = '9px monospace'
  ctx.fillText(`THRES: ${sensitivityThreshold.value}dB`, w - 105, threshY - 4)

  const rawBins = props.rtaBins
  if (smoothedBins.length !== rawBins.length) {
    smoothedBins = [...rawBins]
  } else if (decaySpeed.value === 'slow') {
    for (let i = 0; i < rawBins.length; i++) {
      const cur = rawBins[i] ?? -85
      const prev = smoothedBins[i] ?? cur
      smoothedBins[i] = cur > prev ? cur : prev * 0.78 + cur * 0.22
    }
  } else {
    smoothedBins = [...rawBins]
  }
  const bins = smoothedBins
  const peakBins = props.peakHoldBins

  // VIEW MODE: 31-BAND ISO BARS
  if (currentView.value === 'bars') {
    const barWidth = (w / ISO_31_FREQS.length) - 2
    for (let i = 0; i < ISO_31_FREQS.length; i++) {
      const freq = ISO_31_FREQS[i]
      const binIdx = Math.min(bins.length - 1, Math.floor((i / ISO_31_FREQS.length) * bins.length))
      const val = bins[binIdx] ?? -85
      const peakVal = peakBins[binIdx] ?? -85

      const x = i * (barWidth + 2) + 2
      const y = dbToY(val, h)
      const barHeight = Math.max(2, h - y)

      // Bar gradient fill
      const grad = ctx.createLinearGradient(0, y, 0, h)
      if (val > -6) {
        grad.addColorStop(0, '#ef4444')
        grad.addColorStop(0.3, '#f59e0b')
        grad.addColorStop(1, '#0284c7')
      } else if (val > -18) {
        grad.addColorStop(0, '#f59e0b')
        grad.addColorStop(1, '#0284c7')
      } else {
        grad.addColorStop(0, '#38bdf8')
        grad.addColorStop(1, '#0f172a')
      }

      ctx.fillStyle = grad
      ctx.fillRect(x, y, barWidth, barHeight)

      // Peak Hold Cap
      const peakY = dbToY(peakVal, h)
      ctx.fillStyle = '#f59e0b'
      ctx.fillRect(x, peakY - 2, barWidth, 2)
    }
  }

  // VIEW MODE: CONTINUOUS SPECTRUM CURVE
  if (currentView.value === 'curve') {
    if (bins.length > 0) {
      // Area gradient under curve
      const areaGrad = ctx.createLinearGradient(0, 0, 0, h)
      areaGrad.addColorStop(0, 'rgba(56, 189, 248, 0.35)')
      areaGrad.addColorStop(0.6, 'rgba(14, 165, 233, 0.12)')
      areaGrad.addColorStop(1, 'rgba(7, 10, 15, 0.0)')

      ctx.beginPath()
      for (let i = 0; i < bins.length; i++) {
        const x = (i / (bins.length - 1)) * w
        const y = dbToY(bins[i], h)
        if (i === 0) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      }
      ctx.lineTo(w, h)
      ctx.lineTo(0, h)
      ctx.closePath()
      ctx.fillStyle = areaGrad
      ctx.fill()

      // Primary Spectrum Line with Cyan Glow
      ctx.beginPath()
      ctx.strokeStyle = '#38bdf8'
      ctx.lineWidth = 2.5
      ctx.shadowColor = 'rgba(0, 240, 255, 0.65)'
      ctx.shadowBlur = 8
      for (let i = 0; i < bins.length; i++) {
        const x = (i / (bins.length - 1)) * w
        const y = dbToY(bins[i], h)
        if (i === 0) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      }
      ctx.stroke()
      ctx.shadowBlur = 0 // Reset shadow
    }

    // Peak Hold Envelope
    if (peakBins.length > 0) {
      ctx.beginPath()
      ctx.strokeStyle = 'rgba(245, 158, 11, 0.85)'
      ctx.lineWidth = 1.5
      for (let i = 0; i < peakBins.length; i++) {
        const x = (i / (peakBins.length - 1)) * w
        const y = dbToY(peakBins[i], h)
        if (i === 0) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      }
      ctx.stroke()
    }
  }

  // 4. Composite PEQ Notch Filters Curve Overlay
  if (props.activeNotches.length > 0) {
    ctx.beginPath()
    ctx.strokeStyle = '#ef4444'
    ctx.lineWidth = 2
    ctx.setLineDash([3, 3])

    const samplePoints = 120
    for (let i = 0; i <= samplePoints; i++) {
      const norm = i / samplePoints
      const freq = 20 * Math.pow(1000, norm)
      let totalAtten = 0

      for (const n of props.activeNotches) {
        const f0 = n.freq_hz
        const q = n.q || 8.0
        const gain = n.gain_db
        // Bell filter transfer attenuation formula
        const ratio = freq / f0 - f0 / freq
        const atten = gain / (1.0 + q * q * ratio * ratio)
        totalAtten += atten
      }

      const x = norm * w
      // Draw attenuation centered around -15dB visual baseline
      const y = dbToY(Math.max(-80, -15 + totalAtten), h)
      if (i === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    }
    ctx.stroke()
    ctx.setLineDash([])

    // Notch cut markers
    for (const notch of props.activeNotches) {
      const nx = freqToX(notch.freq_hz, w)
      ctx.strokeStyle = 'rgba(239, 68, 68, 0.8)'
      ctx.lineWidth = 1.5
      ctx.setLineDash([2, 2])
      ctx.beginPath()
      ctx.moveTo(nx, 0)
      ctx.lineTo(nx, h)
      ctx.stroke()
      ctx.setLineDash([])

      ctx.fillStyle = '#ef4444'
      ctx.font = '10px monospace'
      ctx.fillText(`${notch.freq_hz.toFixed(0)}Hz (${notch.gain_db.toFixed(1)}dB)`, nx + 4, 24)
    }
  }

  // 5. Interactive Mouse Crosshair & Harmonic Inspector
  if (isHovering.value) {
    const hx = hoverX.value
    const hy = hoverY.value
    const f0 = hoverFreq.value

    // Main cursor line
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.65)'
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(hx, 0)
    ctx.lineTo(hx, h)
    ctx.moveTo(0, hy)
    ctx.lineTo(w, hy)
    ctx.stroke()

    // Harmonic Overtones: 2f and 3f
    const f2 = f0 * 2
    const f3 = f0 * 3
    if (f2 <= 20000) {
      const x2 = freqToX(f2, w)
      ctx.strokeStyle = 'rgba(168, 85, 247, 0.5)'
      ctx.setLineDash([2, 4])
      ctx.beginPath()
      ctx.moveTo(x2, 0)
      ctx.lineTo(x2, h)
      ctx.stroke()
      ctx.fillStyle = '#c084fc'
      ctx.font = '9px monospace'
      ctx.fillText('2f', x2 + 2, 40)
    }
    if (f3 <= 20000) {
      const x3 = freqToX(f3, w)
      ctx.strokeStyle = 'rgba(168, 85, 247, 0.4)'
      ctx.setLineDash([2, 4])
      ctx.beginPath()
      ctx.moveTo(x3, 0)
      ctx.lineTo(x3, h)
      ctx.stroke()
      ctx.fillStyle = '#c084fc'
      ctx.font = '9px monospace'
      ctx.fillText('3f', x3 + 2, 52)
    }
    ctx.setLineDash([])
  }
}

function renderWaterfall() {
  const canvas = waterfallCanvasRef.value
  if (!canvas || currentView.value !== 'waterfall') return
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const w = canvas.width
  const h = canvas.height
  const bins = props.rtaBins

  if (bins && bins.length > 0) {
    waterfallHistory.unshift([...bins])
    if (waterfallHistory.length > WATERFALL_ROWS) {
      waterfallHistory.pop()
    }
  }

  ctx.fillStyle = '#07090e'
  ctx.fillRect(0, 0, w, h)

  const rowHeight = h / WATERFALL_ROWS
  for (let r = 0; r < waterfallHistory.length; r++) {
    const row = waterfallHistory[r]
    const y = r * rowHeight
    const colWidth = w / (row.length - 1)

    for (let c = 0; c < row.length - 1; c++) {
      const val = row[c]
      ctx.fillStyle = getThermalColor(val)
      ctx.fillRect(c * colWidth, y, colWidth + 1, rowHeight + 1)
    }
  }
}

let animFrameId: number | null = null

function scheduleRender() {
  if (animFrameId !== null) return
  animFrameId = requestAnimationFrame(() => {
    animFrameId = null
    renderCanvas()
    if (currentView.value === 'waterfall') {
      renderWaterfall()
    }
  })
}

onMounted(() => {
  scheduleRender()
})

onUnmounted(() => {
  if (animFrameId !== null) {
    cancelAnimationFrame(animFrameId)
    animFrameId = null
  }
})

watch(() => [props.rtaBins, props.activeNotches, props.peakHoldBins, currentView.value, decaySpeed.value], () => {
  scheduleRender()
}, { deep: false })
</script>

<template>
  <div class="c-card rta-card">
    <div class="c-card-title">
      <div class="title-group">
        <span class="main-title">📊 {{ t('rta.title') }}</span>
        <span class="rta-source font-mono">{{ t('rta.source') }}</span>
      </div>

      <!-- VIEW & CONTROL TOOLBAR -->
      <div class="view-controls">
        <div class="view-pill">
          <button
            :class="['v-btn', { active: currentView === 'curve' }]"
            @click="currentView = 'curve'"
          >
            {{ t('rta.viewCurve') }}
          </button>
          <button
            :class="['v-btn', { active: currentView === 'bars' }]"
            @click="currentView = 'bars'"
          >
            {{ t('rta.viewBars') }}
          </button>
          <button
            :class="['v-btn', { active: currentView === 'waterfall' }]"
            @click="currentView = 'waterfall'"
          >
            {{ t('rta.viewWaterfall') }}
          </button>
        </div>

        <div class="speed-pill">
          <button
            :class="['v-btn', { active: decaySpeed === 'fast' }]"
            @click="decaySpeed = 'fast'"
          >
            {{ t('rta.speedFast') }}
          </button>
          <button
            :class="['v-btn', { active: decaySpeed === 'slow' }]"
            @click="decaySpeed = 'slow'"
          >
            {{ t('rta.speedSlow') }}
          </button>
        </div>
      </div>
    </div>

    <!-- CANVAS CONTAINER -->
    <div
      class="rta-container"
      @mousemove="handleMouseMove"
      @mouseleave="handleMouseLeave"
      @click="handleCanvasClick"
    >
      <!-- PRIMARY SPECTRUM CANVAS -->
      <canvas
        v-show="currentView !== 'waterfall'"
        ref="canvasRef"
        width="1100"
        height="380"
      />

      <!-- WATERFALL SPECTROGRAM CANVAS -->
      <canvas
        v-show="currentView === 'waterfall'"
        ref="waterfallCanvasRef"
        width="1100"
        height="380"
      />

      <!-- LEGEND / READOUT BADGES -->
      <div class="rta-legend">
        <div class="legend-item"><div class="legend-color bg-cyan" /> {{ t('rta.instant') }}</div>
        <div class="legend-item"><div class="legend-color bg-amber" /> {{ t('rta.peak') }}</div>
        <div class="legend-item"><div class="legend-color bg-red" /> {{ t('rta.peqCurve') }}</div>
      </div>

      <!-- INTERACTIVE HOVER READOUT BAR -->
      <div v-if="isHovering" class="hover-inspector">
        <div class="insp-item">
          <span class="insp-label">{{ t('rta.cursorFreq') }}:</span>
          <b class="insp-val text-cyan font-mono">{{ hoverFreq }} Hz</b>
        </div>
        <div class="insp-item">
          <span class="insp-label">{{ t('rta.cursorNote') }}:</span>
          <b class="insp-val text-amber font-mono">{{ hoverNote }}</b>
        </div>
        <div class="insp-item">
          <span class="insp-label">{{ t('rta.cursorLevel') }}:</span>
          <b class="insp-val text-green font-mono">{{ hoverDb }} dBFS</b>
        </div>
        <div class="insp-hint">
          <span>{{ t('rta.clickToNotch') }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.rta-card {
  margin-bottom: 12px;
}

.title-group {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.main-title {
  color: var(--text-main);
  font-weight: 700;
}

.rta-source {
  font-size: 11px;
  color: var(--accent-cyan);
}

.view-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.view-pill, .speed-pill {
  display: flex;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  overflow: hidden;
}

.v-btn {
  background: none;
  border: none;
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-dim);
  cursor: pointer;
  transition: all 0.15s ease;
}

.v-btn:hover {
  color: var(--text-main);
}

.v-btn.active {
  background: var(--bg-tertiary);
  color: var(--accent-cyan);
}

.rta-container {
  position: relative;
  width: 100%;
  height: 380px;
  background: #06080d;
  border-radius: 6px;
  overflow: hidden;
  border: 1px solid var(--border-color);
  cursor: crosshair;
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
  background: rgba(11, 14, 20, 0.85);
  backdrop-filter: blur(4px);
  padding: 4px 10px;
  border-radius: 4px;
  border: 1px solid var(--border-color);
  pointer-events: none;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 5px;
  color: var(--text-secondary);
}

.legend-color {
  width: 10px;
  height: 3px;
  border-radius: 1px;
}

.bg-cyan { background: #38bdf8; box-shadow: 0 0 6px #38bdf8; }
.bg-amber { background: #f59e0b; }
.bg-red { background: #ef4444; }

.hover-inspector {
  position: absolute;
  bottom: 8px;
  left: 8px;
  right: 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(13, 18, 26, 0.9);
  backdrop-filter: blur(8px);
  border: 1px solid var(--border-highlight);
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 12px;
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.5);
  pointer-events: none;
}

.insp-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.insp-label {
  color: var(--text-dim);
}

.insp-hint {
  font-size: 11px;
  color: var(--text-muted);
  font-style: italic;
}
</style>
