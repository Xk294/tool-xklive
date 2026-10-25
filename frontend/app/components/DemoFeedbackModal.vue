<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from '~/composables/useI18n'

const { t } = useI18n()

const props = defineProps<{
  isOpen: boolean
  triggerFeedback: (channel: number, freqHz: number, gainDb: number) => Promise<void>
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const channel = ref(1)
const frequency = ref(2500)
const gain = ref(-6.0)
const sentAlert = ref(false)

const presetFreqs = [500, 1000, 1600, 2500, 3150, 4000, 6300, 8000]

async function handleTrigger() {
  await props.triggerFeedback(channel.value, frequency.value, gain.value)
  sentAlert.value = true
  setTimeout(() => {
    sentAlert.value = false
    emit('close')
  }, 1000)
}
</script>

<template>
  <div v-if="isOpen" class="modal-overlay" @click.self="emit('close')">
    <div class="modal-card demo-modal-card">
      <div class="modal-header">
        <h3 class="demo-header-title">{{ t('demo.title') }}</h3>
        <button class="close-btn" @click="emit('close')">✕</button>
      </div>

      <div class="modal-body">
        <div class="demo-form">
          <div class="form-row">
            <label>{{ t('demo.channel') }}</label>
            <select v-model.number="channel" class="form-input">
              <option v-for="ch in 16" :key="ch" :value="ch">CH {{ ch.toString().padStart(2, '0') }}</option>
            </select>
          </div>

          <div class="form-row">
            <label>{{ t('demo.frequency') }}</label>
            <input v-model.number="frequency" type="number" step="10" min="20" max="20000" class="form-input" />
          </div>

          <div class="presets-row">
            <button
              v-for="f in presetFreqs"
              :key="f"
              :class="['preset-btn', { active: frequency === f }]"
              @click="frequency = f"
            >
              {{ f }} Hz
            </button>
          </div>

          <div class="form-row">
            <label>{{ t('demo.gain') }}</label>
            <input v-model.number="gain" type="number" step="0.5" min="-12" max="-3" class="form-input" />
          </div>

          <div v-if="sentAlert" class="success-banner">
            ✓ {{ t('demo.success', { channel, freq: frequency }) }}
          </div>
        </div>

        <button class="fire-btn" @click="handleTrigger">
          {{ t('demo.trigger') }}
        </button>
      </div>

      <div class="modal-footer">
        <button class="c-btn-secondary" @click="emit('close')">{{ t('common.close') }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.demo-modal-card {
  max-width: 440px;
}

.demo-header-title {
  color: #c084fc !important;
}

.demo-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.form-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.form-row label {
  font-size: 12px;
  color: var(--text-dim);
}

.form-input {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  color: var(--text-main);
  padding: 6px 10px;
  border-radius: 4px;
  font-size: 13px;
  font-family: var(--font-mono);
  width: 140px;
  text-align: right;
}

.presets-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.preset-btn {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  color: var(--text-dim);
  font-size: 11px;
  font-family: var(--font-mono);
  padding: 4px 8px;
  border-radius: 4px;
  cursor: pointer;
}

.preset-btn.active {
  border-color: #c084fc;
  color: #c084fc;
  background: rgba(192, 132, 252, 0.1);
}

.fire-btn {
  width: 100%;
  padding: 10px;
  background: #a855f7;
  color: #fff;
  font-weight: 700;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  box-shadow: 0 4px 12px rgba(168, 85, 247, 0.3);
}

.fire-btn:hover {
  background: #9333ea;
}

.success-banner {
  background: rgba(34, 197, 94, 0.15);
  border: 1px solid var(--accent-green);
  color: var(--accent-green);
  padding: 8px;
  border-radius: 4px;
  font-size: 12px;
  text-align: center;
}
</style>
