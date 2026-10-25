<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from '~/composables/useI18n'
import type {
  MixerConnectionStatus,
  DiscoveredMixer,
  AudioDeviceItem
} from '~/composables/useCompanionSocket'

const { t } = useI18n()

const props = defineProps<{
  isOpen: boolean
  mixerStatus: MixerConnectionStatus
  mixerModel: string
  connectMixer: (ip: string, port: number) => Promise<boolean>
  disconnectMixer: () => Promise<void>
  discoverMixers: () => Promise<DiscoveredMixer[]>
  listAudioDevices: () => Promise<AudioDeviceItem[]>
  startAudioCapture: (deviceName?: string) => Promise<boolean>
  stopAudioCapture: () => Promise<void>
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const ip = ref('192.168.1.1')
const port = ref(10024)
const isConnecting = ref(false)
const isScanning = ref(false)
const discoveredMixers = ref<DiscoveredMixer[]>([])
const audioDevices = ref<AudioDeviceItem[]>([])
const selectedAudioDevice = ref<string>('')
const isAudioRunning = ref(false)
const errorMessage = ref('')

async function handleConnect(targetIp?: string, targetPort?: number) {
  isConnecting.value = true
  errorMessage.value = ''
  try {
    const connIp = targetIp || ip.value
    const connPort = targetPort || port.value
    const ok = await props.connectMixer(connIp, connPort)
    if (ok) {
      emit('close')
    } else {
      errorMessage.value = `${t('hardwareModal.connecting')} (${connIp}:${connPort})`
    }
  } catch (e: unknown) {
    errorMessage.value = e instanceof Error ? e.message : String(e)
  } finally {
    isConnecting.value = false
  }
}

async function handleDisconnect() {
  await props.disconnectMixer()
}

async function scanMixers() {
  isScanning.value = true
  errorMessage.value = ''
  try {
    const list = await props.discoverMixers()
    discoveredMixers.value = list || []
    if (discoveredMixers.value.length === 0) {
      errorMessage.value = t('hardwareModal.noMixersFound')
    }
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    errorMessage.value = t('hardwareModal.connectError', { msg })
  } finally {
    isScanning.value = false
  }
}

async function loadAudioDevices() {
  try {
    const list = await props.listAudioDevices()
    audioDevices.value = list || []
    const def = audioDevices.value.find(d => d.is_default)
    if (def) {
      selectedAudioDevice.value = def.name
    } else if (audioDevices.value[0]) {
      selectedAudioDevice.value = audioDevices.value[0].name
    }
  } catch (e) {
    console.error('Failed to list audio devices', e)
  }
}

async function toggleAudio() {
  if (isAudioRunning.value) {
    await props.stopAudioCapture()
    isAudioRunning.value = false
  } else {
    const ok = await props.startAudioCapture(selectedAudioDevice.value || undefined)
    isAudioRunning.value = !!ok
  }
}

onMounted(() => {
  loadAudioDevices()
})
</script>

<template>
  <div v-if="isOpen" class="modal-overlay" @click.self="emit('close')">
    <div class="modal-card">
      <div class="modal-header">
        <h3>🔌 {{ t('hardwareModal.title') }}</h3>
        <button class="close-btn" @click="emit('close')">✕</button>
      </div>

      <div class="modal-body">
        <!-- STATUS BANNER -->
        <div class="conn-status-banner" :class="mixerStatus.toLowerCase()">
          <div class="status-indicator">
            <span class="status-dot" />
            <span>{{ t('hardwareModal.bannerStatus') }}: <b>{{ mixerStatus }}</b> — {{ mixerModel }}</span>
          </div>
          <button
            v-if="mixerStatus === 'CONNECTED'"
            class="c-btn-small btn-disconnect"
            @click="handleDisconnect"
          >
            {{ t('hardwareModal.disconnectBtn') }}
          </button>
        </div>

        <!-- OSC UDP CONNECTION FORM -->
        <div class="section-box">
          <h4>{{ t('hardwareModal.oscSectionTitle') }}</h4>
          <p class="section-desc">{{ t('hardwareModal.oscSectionDesc') }}</p>

          <div class="form-grid">
            <div class="form-group">
              <label>{{ t('hardwareModal.ipLabel') }}</label>
              <input v-model="ip" type="text" class="c-input" placeholder="192.168.1.1" />
            </div>
            <div class="form-group">
              <label>{{ t('hardwareModal.portLabel') }}</label>
              <input v-model.number="port" type="number" class="c-input" placeholder="10024" />
            </div>
          </div>

          <div class="btn-row">
            <button
              class="c-btn-primary"
              :disabled="isConnecting"
              @click="handleConnect()"
            >
              {{ isConnecting ? t('hardwareModal.connecting') : t('hardwareModal.directConnectBtn') }}
            </button>
            <button
              class="c-btn-secondary"
              :disabled="isScanning"
              @click="scanMixers"
            >
              {{ isScanning ? t('hardwareModal.scanning') : t('hardwareModal.scanLanBtn') }}
            </button>
          </div>

          <div v-if="discoveredMixers.length > 0" class="discovered-list">
            <div class="list-title">{{ t('hardwareModal.foundTitle') }}</div>
            <div
              v-for="m in discoveredMixers"
              :key="m.ip"
              class="discovered-item"
              @click="handleConnect(m.ip, 10024)"
            >
              <span class="mixer-name">🎛️ {{ m.name }} ({{ m.model }})</span>
              <span class="mixer-ip font-mono">{{ m.ip }}:10024</span>
              <button class="c-btn-small">{{ t('hardwareModal.selectBtn') }}</button>
            </div>
          </div>
        </div>

        <!-- AUDIO ENGINE SETTINGS -->
        <div class="section-box">
          <h4>{{ t('hardwareModal.audioSectionTitle') }}</h4>
          <p class="section-desc">{{ t('hardwareModal.audioSectionDesc') }}</p>

          <div class="form-group">
            <label>{{ t('hardwareModal.deviceLabel') }}</label>
            <select v-model="selectedAudioDevice" class="c-input">
              <option v-for="d in audioDevices" :key="d.name" :value="d.name">
                {{ d.name }} {{ d.is_default ? t('hardwareModal.defaultTag') : '' }}
              </option>
            </select>
          </div>

          <div class="btn-row">
            <button
              :class="['c-btn-secondary', isAudioRunning ? 'btn-stop-audio' : 'btn-start-audio']"
              @click="toggleAudio"
            >
              {{ isAudioRunning ? t('hardwareModal.stopAudioBtn') : t('hardwareModal.startAudioBtn') }}
            </button>
          </div>
        </div>

        <div v-if="errorMessage" class="error-banner">
          ⚠️ {{ errorMessage }}
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.conn-status-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  border-radius: 6px;
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
}

.conn-status-banner.connected {
  background: rgba(16, 185, 129, 0.12);
  border-color: rgba(16, 185, 129, 0.4);
  color: var(--accent-green);
}

.conn-status-banner.connecting,
.conn-status-banner.reconnecting {
  background: rgba(245, 158, 11, 0.12);
  border-color: rgba(245, 158, 11, 0.4);
  color: var(--accent-amber);
}

.conn-status-banner.mock {
  background: rgba(168, 85, 247, 0.12);
  border-color: rgba(168, 85, 247, 0.4);
  color: var(--accent-purple);
}

.conn-status-banner.disconnected {
  background: rgba(239, 68, 68, 0.12);
  border-color: rgba(239, 68, 68, 0.4);
  color: var(--accent-red);
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
}

.btn-disconnect {
  color: var(--accent-red);
  border-color: rgba(239, 68, 68, 0.3);
}

.section-box {
  background: #090d14;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.section-box h4 {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-main);
  margin: 0;
}

.section-desc {
  font-size: 11px;
  color: var(--text-dim);
  margin: 0;
  line-height: 1.4;
}

.form-grid {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 10px;
}

.form-group label {
  display: block;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-dim);
  margin-bottom: 4px;
}

.btn-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.discovered-list {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  padding: 8px;
}

.list-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-dim);
  margin-bottom: 6px;
}

.discovered-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 8px;
  border-radius: 4px;
  cursor: pointer;
  background: var(--bg-tertiary);
  margin-bottom: 4px;
}

.discovered-item:hover {
  background: var(--border-color);
}

.mixer-name {
  font-size: 12px;
  font-weight: 600;
}

.mixer-ip {
  font-size: 11px;
  color: var(--accent-cyan);
}

.btn-start-audio {
  color: var(--accent-cyan);
  border-color: rgba(56, 189, 248, 0.4);
}

.btn-stop-audio {
  color: var(--accent-red);
  border-color: rgba(239, 68, 68, 0.4);
}

.error-banner {
  background: rgba(239, 68, 68, 0.12);
  border: 1px solid rgba(239, 68, 68, 0.4);
  color: #fca5a5;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 11px;
}
</style>
