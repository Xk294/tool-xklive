<script setup lang="ts">
import { ref, onUnmounted } from 'vue'
import { useI18n } from '~/composables/useI18n'

const { t } = useI18n()

defineProps<{
  isOpen: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

type SignalType = 'pink' | 'white' | 'sine1k' | 'sweep'

const activeType = ref<SignalType>('pink')
const isPlaying = ref(false)
const volumeDb = ref(-18)

let audioCtx: AudioContext | null = null
let masterGain: GainNode | null = null
let sourceNode: AudioScheduledSourceNode | null = null
let sweepOsc: OscillatorNode | null = null
let sweepTimer: ReturnType<typeof setInterval> | null = null

function getAudioContext(): AudioContext {
  if (!audioCtx || audioCtx.state === 'closed') {
    const AudioContextClass =
      window.AudioContext
      || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!AudioContextClass) {
      throw new Error('Web Audio API is not supported in this browser')
    }
    audioCtx = new AudioContextClass()
  }
  if (audioCtx.state === 'suspended') {
    audioCtx.resume()
  }
  return audioCtx
}

function updateGain() {
  if (!masterGain || !audioCtx) return
  const linear = Math.pow(10, volumeDb.value / 20)
  masterGain.gain.setTargetAtTime(linear, audioCtx.currentTime, 0.05)
}

function stopCurrent() {
  if (sweepTimer) {
    clearInterval(sweepTimer)
    sweepTimer = null
  }
  if (sweepOsc) {
    try {
      sweepOsc.stop()
      sweepOsc.disconnect()
    } catch {}
    sweepOsc = null
  }
  if (sourceNode) {
    try {
      sourceNode.stop()
      sourceNode.disconnect()
    } catch {}
    sourceNode = null
  }
  isPlaying.value = false
}

function startSignal() {
  stopCurrent()
  const ctx = getAudioContext()

  if (!masterGain) {
    masterGain = ctx.createGain()
    masterGain.connect(ctx.destination)
  }
  updateGain()

  if (activeType.value === 'sine1k') {
    const osc = ctx.createOscillator()
    osc.type = 'sine'
    osc.frequency.setValueAtTime(1000, ctx.currentTime)
    osc.connect(masterGain)
    osc.start()
    sourceNode = osc
  } else if (activeType.value === 'white') {
    const bufferSize = ctx.sampleRate * 2
    const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate)
    const data = buffer.getChannelData(0)
    for (let i = 0; i < bufferSize; i++) {
      data[i] = Math.random() * 2 - 1
    }
    const noise = ctx.createBufferSource()
    noise.buffer = buffer
    noise.loop = true
    noise.connect(masterGain)
    noise.start()
    sourceNode = noise
  } else if (activeType.value === 'pink') {
    // Paul Kellet's filtered noise algorithm for Pink Noise (-3dB/octave)
    const bufferSize = ctx.sampleRate * 2
    const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate)
    const data = buffer.getChannelData(0)
    let b0 = 0, b1 = 0, b2 = 0, b3 = 0, b4 = 0, b5 = 0, b6 = 0
    for (let i = 0; i < bufferSize; i++) {
      const white = Math.random() * 2 - 1
      b0 = 0.99886 * b0 + white * 0.0555179
      b1 = 0.99332 * b1 + white * 0.0750759
      b2 = 0.96900 * b2 + white * 0.1538520
      b3 = 0.86650 * b3 + white * 0.3104856
      b4 = 0.55000 * b4 + white * 0.5329522
      b5 = -0.7616 * b5 - white * 0.0168980
      data[i] = (b0 + b1 + b2 + b3 + b4 + b5 + b6 + white * 0.5362) * 0.11
      b6 = white * 0.115926
    }
    const noise = ctx.createBufferSource()
    noise.buffer = buffer
    noise.loop = true
    noise.connect(masterGain)
    noise.start()
    sourceNode = noise
  } else if (activeType.value === 'sweep') {
    const osc = ctx.createOscillator()
    osc.type = 'sine'
    osc.connect(masterGain)
    const duration = 5.0
    const runSweep = () => {
      const t = ctx.currentTime
      osc.frequency.setValueAtTime(20, t)
      osc.frequency.exponentialRampToValueAtTime(20000, t + duration)
    }
    runSweep()
    osc.start()
    sweepOsc = osc
    sourceNode = osc
    sweepTimer = setInterval(runSweep, (duration + 0.5) * 1000)
  }

  isPlaying.value = true
}

function togglePlay() {
  if (isPlaying.value) {
    stopCurrent()
  } else {
    startSignal()
  }
}

function selectType(type: SignalType) {
  activeType.value = type
  if (isPlaying.value) {
    startSignal()
  }
}

onUnmounted(() => {
  stopCurrent()
  if (audioCtx) {
    audioCtx.close()
    audioCtx = null
  }
})
</script>

<template>
  <div v-if="isOpen" class="modal-overlay" @click.self="emit('close')">
    <div class="modal-card">
      <div class="modal-header">
        <h3>🎵 {{ t('generator.title') }}</h3>
        <button class="close-btn" @click="emit('close')">✕</button>
      </div>

      <div class="modal-body">
        <p class="gen-desc">{{ t('generator.desc') }}</p>

        <div class="warning-box">
          ⚠️ {{ t('generator.warning') }}
        </div>

        <div class="signal-selector">
          <label class="section-label">{{ t('generator.type') }}:</label>
          <div class="type-grid">
            <button
              :class="['type-btn', { active: activeType === 'pink' }]"
              @click="selectType('pink')"
            >
              <span class="icon">🌸</span>
              <span class="text">{{ t('generator.pinkNoise') }}</span>
            </button>
            <button
              :class="['type-btn', { active: activeType === 'white' }]"
              @click="selectType('white')"
            >
              <span class="icon">⚪</span>
              <span class="text">{{ t('generator.whiteNoise') }}</span>
            </button>
            <button
              :class="['type-btn', { active: activeType === 'sine1k' }]"
              @click="selectType('sine1k')"
            >
              <span class="icon">〰️</span>
              <span class="text">{{ t('generator.sine1k') }}</span>
            </button>
            <button
              :class="['type-btn', { active: activeType === 'sweep' }]"
              @click="selectType('sweep')"
            >
              <span class="icon">📈</span>
              <span class="text">{{ t('generator.sineSweep') }}</span>
            </button>
          </div>
        </div>

        <div class="volume-control">
          <div class="vol-header">
            <span>{{ t('generator.volume') }}:</span>
            <span class="vol-val font-mono">{{ volumeDb > -60 ? `${volumeDb} dBFS` : '-inf dB' }}</span>
          </div>
          <input
            v-model.number="volumeDb"
            type="range"
            min="-48"
            max="-6"
            step="1"
            class="vol-slider"
            @input="updateGain"
          />
        </div>

        <div class="action-footer">
          <button
            :class="['play-btn', { 'is-playing': isPlaying }]"
            @click="togglePlay"
          >
            <span>{{ isPlaying ? '⏹️ ' + t('common.stop') : '▶️ ' + t('common.start') }}</span>
          </button>
          <span class="status-badge" :class="{ active: isPlaying }">
            {{ isPlaying ? t('generator.running') : t('generator.stopped') }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.gen-desc {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.4;
}

.warning-box {
  background: rgba(239, 68, 68, 0.12);
  border: 1px solid rgba(239, 68, 68, 0.4);
  color: #fca5a5;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
}

.section-label {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  color: var(--text-dim);
  margin-bottom: 6px;
  display: block;
}

.type-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.type-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  color: var(--text-secondary);
  cursor: pointer;
  text-align: left;
  font-size: 12px;
  font-weight: 500;
  transition: all 0.15s ease;
}

.type-btn:hover {
  background: var(--border-color);
  color: #fff;
}

.type-btn.active {
  background: rgba(56, 189, 248, 0.15);
  border-color: var(--accent-cyan);
  color: var(--accent-cyan);
}

.type-btn .icon {
  font-size: 16px;
}

.volume-control {
  background: var(--bg-tertiary);
  padding: 12px;
  border-radius: 6px;
  border: 1px solid var(--border-color);
}

.vol-header {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 8px;
}

.vol-slider {
  width: 100%;
  accent-color: var(--accent-cyan);
  cursor: pointer;
}

.action-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 6px;
  padding-top: 10px;
  border-top: 1px solid var(--border-color);
}

.play-btn {
  min-width: 140px;
  padding: 10px 20px;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  background: linear-gradient(135deg, #059669, #047857);
  border: 1px solid #10b981;
  color: #fff;
  transition: all 0.15s ease;
  box-shadow: 0 4px 12px rgba(5, 150, 105, 0.4);
}

.play-btn.is-playing {
  background: linear-gradient(135deg, #dc2626, #b91c1c);
  border-color: #ef4444;
  box-shadow: 0 4px 12px rgba(220, 38, 38, 0.5);
}

.status-badge {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-dim);
}

.status-badge.active {
  color: var(--accent-green);
  font-weight: 700;
}
</style>
