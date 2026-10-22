<script setup lang="ts">
import type { ChannelInfo } from '~/composables/useCompanionSocket'
import { useI18n } from '~/composables/useI18n'

const { t } = useI18n()

defineProps<{
  meters: number[]
  channels?: ChannelInfo[]
}>()

function formatName(name?: string, ch?: number): string {
  if (!name) return String(ch ?? '')
  const match = name.match(/^(?:K\u00eanh|Ch)\s*0?(\d+)$/i)
  if (match) {
    return t('meters.channel', { n: match[1] })
  }
  return name
}

function formatTooltip(name?: string, ch?: number): string {
  if (name) {
    const match = name.match(/^(?:K\u00eanh|Ch)\s*0?(\d+)$/i)
    if (!match) {
      return `${name} (${t('meters.channelTooltip', { n: ch ?? '' })})`
    }
  }
  return t('meters.channelTooltip', { n: ch ?? '' })
}
</script>

<template>
  <div class="c-card">
    <div class="c-card-title">
      <span>{{ t('meters.title') }}</span>
      <span class="meter-hint">{{ t('meters.hint') }} | <b style="color: var(--accent-red)">M</b>: {{ t('meters.hintMute') }}</span>
    </div>
    <div class="meters-grid">
      <div
        v-for="ch in 16"
        :key="ch"
        :class="['meter-col', { 'is-muted': channels?.[ch - 1]?.is_muted }]"
      >
        <div class="meter-bar-bg">
          <div
            class="meter-fill"
            :style="{ height: Math.min(100, Math.max(0, (meters[ch - 1] || 0) * 100)) + '%' }"
          />
        </div>
        <span
          class="meter-label"
          :title="formatTooltip(channels?.[ch - 1]?.name, ch)"
        >
          <span v-if="channels?.[ch - 1]?.is_muted" class="mute-tag">M</span>
          <span v-else-if="channels?.[ch - 1]?.name" class="name-tag">{{ formatName(channels[ch - 1].name, ch) }}</span>
          <span v-else>{{ ch }}</span>
        </span>
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
  height: 74px;
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

.meter-col.is-muted .meter-bar-bg {
  opacity: 0.4;
  border: 1px dashed var(--accent-red);
}

.meter-bar-bg {
  width: 100%;
  height: 48px;
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
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: inline-block;
  text-align: center;
}

.mute-tag {
  color: var(--accent-red);
  font-weight: 800;
}

.name-tag {
  color: var(--accent-cyan);
}
</style>
