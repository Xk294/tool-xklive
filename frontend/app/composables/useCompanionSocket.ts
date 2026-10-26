import { ref, onMounted, onUnmounted } from 'vue'
import { useI18n } from '~/composables/useI18n'
import { isNotchAttributedToMic } from '~/utils/eventTranslator'

export type MixerConnectionStatus = 'CONNECTED' | 'CONNECTING' | 'RECONNECTING' | 'DISCONNECTED' | 'MOCK'
export type OperationMode = 'auto' | 'semi' | 'manual'

export interface ActiveNotch {
  channel: number
  channel_name?: string
  bus: number | null
  band: number
  freq_hz: number
  gain_db: number
  q: number
  target: string
  age_s: number
  is_locked: boolean
  step_count: number
  reason?: string
  suspected_channel?: number | null
  status_code?: string
  status_params?: Record<string, string | number>
}

export interface Proposal {
  id: string
  channel: number
  channel_name?: string
  bus: number | null
  target: string
  freq_hz: number
  gain_db: number
  q: number
  confidence_score: number
  created_at: number
  ttl_remaining_s: number
  reason: string
  suspected_channel?: number | null
  reason_code?: string
  reason_params?: Record<string, string | number>
}

export interface ChannelInfo {
  channel: number
  name: string
  color: number
  is_muted: boolean
  level: number
  is_locked: boolean
  whitelisted: boolean
  hpf_enabled?: boolean
}

export interface ClipAlert {
  channel: number
  channel_name?: string
  clip_duration_ms?: number
  current_gain_db?: number
  suggested_reduction_db?: number
  peak_db?: number
  rms_db?: number
  crest_factor_db?: number
  timestamp: number
  advice?: string
}

export interface GainCalibrationSession {
  channel: number
  state: 'measuring' | 'completed' | 'cancelled' | string
  duration_s: number
  current_headamp_gain_db?: number
  proposed_gain_db?: number | null
  proposed_gain_change_db: number
  target_rms_dbfs?: number
  max_peak_dbfs?: number
  advice: string
}

export interface LogEntry {
  id: number
  time: string
  text?: string
  text_code?: string
  params?: Record<string, string | number>
  type: 'normal' | 'panic' | 'approved' | 'warning'
}

export interface DiscoveredMixer {
  ip: string
  model: string
  name: string
  firmware?: string
}

export interface AudioDeviceItem {
  name: string
  max_channels: number
  is_default: boolean
}

export interface WizardStartResult {
  success: boolean
  detail?: string
}

export interface WizardStopResult {
  success?: boolean
  status?: string
  message?: string
}

export interface WizardStatusSnapshot {
  state: 'idle' | 'running' | 'paused' | 'completed' | 'aborted' | string
  target_type?: string
  target_id?: number
  current_gain_added: number
  detected_notches: number
  detected_frequencies?: number[]
  status_message?: string
}

export interface DiagnosticsData {
  mixer?: {
    status?: MixerConnectionStatus | string
    mock_mode?: boolean
    model?: string
    firmware?: string
    firmware_reason?: string
    ip?: string
    port?: number
    rta_registered?: boolean
    osc_tx_count?: number
    osc_rx_count?: number
    last_error?: string | null
  }
  latency?: {
    rtt_ms?: number | null
    dsp_latency_ms?: number
    total_latency_ms?: number
  }
  audio?: {
    device_name?: string
    sample_rate?: number
    channels?: number
    audio_mode?: string
  }
  routing?: {
    valid?: boolean
    detail?: string
  }
  log_file?: string
}

export interface DynamicsSuggestionItem {
  channel: number
  current_peak_db?: number
  gain_advice?: string
  comp_threshold_db?: number
  gate_threshold_db?: number
}

export interface DynamicsResponse {
  suggestions: DynamicsSuggestionItem[]
}

export interface FullStateSnapshot {
  mixer_status?: MixerConnectionStatus
  dry_run?: boolean
  mixer_model?: string
  latency_ms?: number
  rtt_ms?: number | null
  dsp_latency_ms?: number
  current_mode?: OperationMode
  current_preset?: string
  audio_mode?: 'usb' | 'lan_rta' | 'none'
  talkover_enabled?: boolean
  talkover_is_ducked?: boolean
  talkover_mic_channel?: number
  clip_alerts?: ClipAlert[]
  gain_sessions?: Record<number, GainCalibrationSession>
  active_notches?: ActiveNotch[]
  pending_proposals?: Proposal[]
  channels?: ChannelInfo[]
  meters?: number[]
  rta_bins?: number[]
  event_logs?: LogEntry[]
}

export function useCompanionSocket() {
  const { t } = useI18n()

  const mixerStatus = ref<MixerConnectionStatus>('DISCONNECTED')
  const isMockMode = ref(false)
  const dryRun = ref(false)
  const mixerModel = ref('Chưa kết nối')
  const latencyMs = ref(42.7)
  const rttMs = ref<number | null>(null)
  const dspLatencyMs = ref<number>(42.7)
  const xruns = ref(0)
  const isLanRta = ref(false)
  const audioMode = ref<'usb' | 'lan_rta' | 'none'>('none')
  const currentMode = ref<OperationMode>('auto')
  const currentPreset = ref<string>('monitor')
  const snapshotBandsCount = ref<number>(0)
  const talkoverEnabled = ref(false)
  const talkoverIsDucked = ref(false)
  const talkoverMicChannel = ref(1)
  const clipAlerts = ref<ClipAlert[]>([])
  const gainSessions = ref<Record<number, GainCalibrationSession>>({})
  const canUndoPanic = ref(false)

  const activeNotches = ref<ActiveNotch[]>([])
  const pendingProposals = ref<Proposal[]>([])
  const channels = ref<ChannelInfo[]>([])
  const meters = ref<number[]>(new Array(16).fill(0))
  const rtaBins = ref<number[]>(new Array(100).fill(-60))
  const peakHoldBins = ref<number[]>(new Array(100).fill(-60))
  const eventLogs = ref<LogEntry[]>([])

  let logIdCounter = 100000
  let pollInterval: ReturnType<typeof setInterval> | null = null
  const isSimulating = ref(false)
  let cachedPreviousNotches: ActiveNotch[] = []
  let cachedPreviousMode: OperationMode = 'auto'
  const clientLogs: LogEntry[] = []
  let mockWizardState: WizardStatusSnapshot = {
    state: 'idle',
    current_gain_added: 0.0,
    detected_notches: 0
  }
  let mockWizardMaxBoost = 3.0

  function playAlertChime() {
    try {
      const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
      if (!AudioCtx) return
      const ctx = new AudioCtx()
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.type = 'sine'
      osc.frequency.setValueAtTime(880, ctx.currentTime)
      gain.gain.setValueAtTime(0.12, ctx.currentTime)
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.25)
      osc.connect(gain)
      gain.connect(ctx.destination)
      osc.start()
      osc.stop(ctx.currentTime + 0.25)
    } catch {
      // Ignore AudioContext autoplay restrictions
    }
  }

  function addLog(
    text: string,
    type: 'normal' | 'panic' | 'approved' | 'warning' = 'normal',
    text_code?: string,
    params?: Record<string, string | number>
  ) {
    const d = new Date()
    const timeStr = d.toTimeString().split(' ')[0] || '00:00:00'
    const entry: LogEntry = {
      id: logIdCounter++,
      time: timeStr,
      text,
      text_code,
      params,
      type
    }
    clientLogs.unshift(entry)
    if (clientLogs.length > 50) {
      clientLogs.pop()
    }
    eventLogs.value.unshift(entry)
    if (eventLogs.value.length > 200) {
      eventLogs.value.pop()
    }
  }

  async function clearLogs() {
    clientLogs.length = 0
    eventLogs.value = []
    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        await invoke('clear_logs')
      } catch (e) {
        console.error('Failed to clear logs in Tauri', e)
      }
    }
  }

  function isTauriEnv(): boolean {
    return typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window)
  }

  function updateFromSnapshot(snapshot: FullStateSnapshot | null | undefined) {
    if (!snapshot) return
    const backendStatus: MixerConnectionStatus = snapshot.mixer_status || 'DISCONNECTED'
    if (backendStatus === 'DISCONNECTED' && (isMockMode.value || isSimulating.value)) {
      mixerStatus.value = 'MOCK'
      if (!mixerModel.value || mixerModel.value === 'Chưa kết nối') {
        mixerModel.value = 'XR18 (Demo)'
      }
    } else {
      mixerStatus.value = backendStatus
      mixerModel.value = snapshot.mixer_model || 'Chưa kết nối'
      if (backendStatus === 'CONNECTED') {
        isMockMode.value = false
      }
    }

    currentMode.value = snapshot.current_mode || 'auto'
    if (snapshot.current_preset) {
      currentPreset.value = snapshot.current_preset
    }
    audioMode.value = snapshot.audio_mode || (isMockMode.value || isSimulating.value ? 'lan_rta' : 'none')
    isLanRta.value = audioMode.value === 'lan_rta'
    if (snapshot.talkover_enabled !== undefined) {
      talkoverEnabled.value = snapshot.talkover_enabled
    }
    if (snapshot.talkover_is_ducked !== undefined) {
      talkoverIsDucked.value = snapshot.talkover_is_ducked
    }
    if (snapshot.talkover_mic_channel !== undefined) {
      talkoverMicChannel.value = snapshot.talkover_mic_channel
    }
    clipAlerts.value = snapshot.clip_alerts || []
    if (Array.isArray(snapshot.gain_sessions)) {
      const mapped: Record<number, GainCalibrationSession> = {}
      for (const s of snapshot.gain_sessions) {
        if (s && typeof s.channel === 'number') {
          mapped[s.channel] = s
        }
      }
      gainSessions.value = mapped
    } else {
      gainSessions.value = snapshot.gain_sessions || {}
    }
    dryRun.value = !!snapshot.dry_run
    rttMs.value = snapshot.rtt_ms ?? null
    dspLatencyMs.value = snapshot.dsp_latency_ms ?? 42.7
    latencyMs.value = snapshot.latency_ms ?? 42.7

    activeNotches.value = (snapshot.active_notches || []).map(n => ({
      ...n,
      gain_db: n.gain_db ?? -3.0,
      step_count: n.step_count ?? 1,
      age_s: n.age_s ?? 0,
      is_locked: !!n.is_locked
    }))

    const incomingProposals: Proposal[] = (snapshot.pending_proposals || []).map(p => ({
      ...p,
      id: p.id || `${p.target || 'ch'}_${p.bus ?? p.channel}_${Math.round(p.freq_hz || 1000)}`,
      confidence_score: p.confidence_score ?? 0.85,
      created_at: p.created_at ?? 0,
      ttl_remaining_s: p.ttl_remaining_s ?? 30
    }))

    if (currentMode.value === 'semi' && incomingProposals.length > pendingProposals.value.length) {
      playAlertChime()
    }
    pendingProposals.value = incomingProposals

    channels.value = snapshot.channels || []
    if (snapshot.meters && snapshot.meters.length > 0) {
      meters.value = snapshot.meters.slice(0, 16)
    }
    if (snapshot.rta_bins && snapshot.rta_bins.length > 0) {
      rtaBins.value = snapshot.rta_bins
      for (let i = 0; i < snapshot.rta_bins.length; i++) {
        peakHoldBins.value[i] = Math.max((peakHoldBins.value[i] || -60) - 0.4, snapshot.rta_bins[i] ?? -60)
      }
    }
    if (Array.isArray(snapshot.event_logs)) {
      const backendReversed = [...snapshot.event_logs].reverse()
      eventLogs.value = [...clientLogs, ...backendReversed].slice(0, 200)
    }
  }

  async function initEngine(): Promise<void> {
    if (import.meta.server) return
    if (!isTauriEnv()) {
      channels.value = Array.from({ length: 16 }, (_, i) => ({
        channel: i + 1,
        name: `CH${(i + 1).toString().padStart(2, '0')}`,
        color: 1,
        is_muted: false,
        level: 0,
        is_locked: false,
        whitelisted: true
      }))
      return
    }

    try {
      const { invoke } = await import('@tauri-apps/api/core')
      const snapshot = await invoke<FullStateSnapshot>('get_state')
      updateFromSnapshot(snapshot)

      if (!pollInterval) {
        pollInterval = setInterval(async () => {
          try {
            const s = await invoke<FullStateSnapshot>('get_state')
            updateFromSnapshot(s)
          } catch (e) {
            console.error('Tauri state poll error', e)
          }
        }, 80)
      }
    } catch (e) {
      console.error('Tauri init failed', e)
    }
  }

  async function setMode(mode: OperationMode) {
    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        await invoke('set_mode', { mode })
        currentMode.value = mode
        return
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e)
        addLog(t('errors.modeChange', { msg }), 'warning', 'errors.modeChange', { msg })
        return
      }
    }
    currentMode.value = mode
    const modeLabel = mode.toUpperCase()
    addLog(t('log.modeChanged', { mode: modeLabel }), 'approved', 'log.modeChanged', { mode: modeLabel })
  }

  async function toggleDryRun(enabled?: boolean) {
    const target = enabled !== undefined ? enabled : !dryRun.value
    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        const val = await invoke<boolean>('toggle_dry_run', { enabled: target })
        dryRun.value = val
        return
      } catch (e) {
        console.error('Failed to toggle dry-run in Tauri', e)
        return
      }
    }
    dryRun.value = target
    const msg = dryRun.value ? t('dryRun.enabled') : t('dryRun.disabled')
    addLog(msg, dryRun.value ? 'warning' : 'approved')
  }

  async function toggleLiveDemo(forceEnable?: boolean) {
    isSimulating.value = forceEnable !== undefined ? forceEnable : !isSimulating.value
    if (isSimulating.value) {
      if (mixerStatus.value === 'CONNECTED' || mixerStatus.value === 'RECONNECTING') {
        await disconnectMixer()
      }
      isMockMode.value = true
      mixerStatus.value = 'MOCK'
      mixerModel.value = 'XR18 (Demo)'
      if (currentMode.value !== 'auto') {
        await setMode('auto')
      }
      await triggerFakeFeedback(1, 2500, -3.0)
    } else if (isMockMode.value) {
      isMockMode.value = false
      mixerStatus.value = 'DISCONNECTED'
      mixerModel.value = 'Chưa kết nối'
      activeNotches.value = []
      pendingProposals.value = []
    }
  }

  async function triggerPanic() {
    const snapshotBeforePanic = [...activeNotches.value]
    const count = snapshotBeforePanic.length
    cachedPreviousMode = currentMode.value

    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        await invoke('panic_reset')
        cachedPreviousNotches = snapshotBeforePanic
        canUndoPanic.value = count > 0
        activeNotches.value = []
        currentMode.value = 'manual'
        return
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e)
        addLog(t('errors.panic', { msg }), 'panic', 'errors.panic', { msg })
        return
      }
    }

    cachedPreviousNotches = snapshotBeforePanic
    canUndoPanic.value = count > 0
    activeNotches.value = []
    currentMode.value = 'manual'
    addLog(t('log.panicTriggered', { count }), 'panic', 'log.panicTriggered', { count })
  }

  async function undoPanic() {
    if (cachedPreviousNotches.length === 0 && !canUndoPanic.value) return
    const toRestore = [...cachedPreviousNotches]

    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        await invoke<number>('undo_panic_reset')
        cachedPreviousNotches = []
        canUndoPanic.value = false
        currentMode.value = cachedPreviousMode
        return
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e)
        addLog(t('errors.undoPanic', { msg }), 'warning', 'errors.undoPanic', { msg })
        return
      }
    }

    cachedPreviousNotches = []
    canUndoPanic.value = false
    activeNotches.value = toRestore
    currentMode.value = cachedPreviousMode
    addLog(
      t('messages.panic_undone', { count: toRestore.length }),
      'approved',
      'messages.panic_undone',
      { count: toRestore.length }
    )
  }

  async function approveProposal(id: string) {
    const idx = pendingProposals.value.findIndex(item => item.id === id)
    if (idx === -1) return
    const p = pendingProposals.value[idx]
    if (!p) return
    pendingProposals.value.splice(idx, 1)

    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        await invoke('approve_proposal', { id: p.id, channel: p.channel, freqHz: p.freq_hz })
      } catch (e) {
        console.error('Failed to approve proposal', e)
      }
      return
    }

    activeNotches.value.push({
      channel: p.channel,
      channel_name: p.channel_name || `CH${p.channel}`,
      bus: p.bus,
      band: activeNotches.value.length + 3,
      freq_hz: p.freq_hz,
      gain_db: p.gain_db,
      q: p.q,
      target: p.target,
      age_s: 0,
      is_locked: false,
      step_count: 1
    })
    addLog(
      t('messages.proposal_approved', { freq_hz: p.freq_hz }),
      'approved',
      'messages.proposal_approved',
      { freq_hz: p.freq_hz }
    )
  }

  async function rejectProposal(id: string) {
    const idx = pendingProposals.value.findIndex(item => item.id === id)
    if (idx === -1) return
    const p = pendingProposals.value[idx]
    if (!p) return
    pendingProposals.value.splice(idx, 1)

    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        await invoke('reject_proposal', { id: p.id, channel: p.channel, freqHz: p.freq_hz })
      } catch (e) {
        console.error('Failed to reject proposal', e)
      }
      return
    }
    addLog(t('messages.proposal_rejected'), 'normal', 'messages.proposal_rejected')
  }

  async function snoozeProposal(id: string) {
    const idx = pendingProposals.value.findIndex(item => item.id === id)
    if (idx === -1) return
    const p = pendingProposals.value[idx]
    if (!p) return
    pendingProposals.value.splice(idx, 1)

    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        await invoke('snooze_proposal', { id: p.id, channel: p.channel, freqHz: p.freq_hz })
      } catch (e) {
        console.error('Failed to snooze proposal', e)
      }
      return
    }
    addLog(
      t('messages.channel_snoozed', { channel: p.channel, duration_s: 60 }),
      'normal',
      'messages.channel_snoozed',
      { channel: p.channel, duration_s: 60 }
    )
  }

  async function toggleLock(channel: number) {
    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        const isLocked = await invoke<boolean>('toggle_lock', { channel })
        const ch = channels.value.find(c => c.channel === channel)
        if (ch) ch.is_locked = isLocked
        return isLocked
      } catch (e) {
        console.error('Failed to toggle lock', e)
      }
    }
    return false
  }

  async function toggleWhitelist(channel: number) {
    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        const isWhitelisted = await invoke<boolean>('toggle_whitelist', { channel })
        const ch = channels.value.find(c => c.channel === channel)
        if (ch) ch.whitelisted = isWhitelisted
        return isWhitelisted
      } catch (e) {
        console.error('Failed to toggle whitelist', e)
      }
    }
    const ch = channels.value.find(c => c.channel === channel)
    if (ch) {
      ch.whitelisted = !ch.whitelisted
      return ch.whitelisted
    }
    return true
  }

  async function releaseChannelNotches(channel: number) {
    const toRelease = activeNotches.value.filter(n => isNotchAttributedToMic(n, channel))
    for (const n of toRelease) {
      await releaseNotch(n.channel, n.band, n.target, n.bus)
    }
  }

  async function releaseNotch(channel: number, band: number, target: string, bus?: number | null) {
    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        await invoke('release_notch', { channel, band, target, bus: bus ?? null })
        const idx = activeNotches.value.findIndex(
          n => n.channel === channel && n.band === band && n.target === target && (n.bus ?? null) === (bus ?? null)
        )
        if (idx !== -1) {
          activeNotches.value.splice(idx, 1)
        }
        return
      } catch (e) {
        console.error('Failed to release notch', e)
        return
      }
    }
    const idx = activeNotches.value.findIndex(
      n => n.channel === channel && n.band === band && n.target === target && (n.bus ?? null) === (bus ?? null)
    )
    if (idx !== -1) {
      activeNotches.value.splice(idx, 1)
    }
    addLog(t('messages.notch_released', { band }), 'approved', 'messages.notch_released', { band })
  }

  async function releaseAllNotches() {
    await triggerPanic()
  }

  async function takeSnapshot() {
    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        const res = await invoke<{ bands_count?: number }>('take_snapshot')
        const count = res?.bands_count ?? 0
        snapshotBandsCount.value = count
        return
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e)
        addLog(t('errors.snapshot', { msg }), 'warning', 'errors.snapshot', { msg })
        return
      }
    }
    snapshotBandsCount.value = activeNotches.value.length
    addLog(
      t('log.snapshotTaken', { count: snapshotBandsCount.value }),
      'approved',
      'log.snapshotTaken',
      { count: snapshotBandsCount.value }
    )
  }

  async function rollbackSnapshot() {
    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        await invoke('rollback_snapshot')
        return
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e)
        addLog(t('errors.rollback', { msg }), 'warning', 'errors.rollback', { msg })
        return
      }
    }
    activeNotches.value = []
    addLog(t('log.snapshotRollback'), 'approved', 'log.snapshotRollback')
  }

  async function triggerFakeFeedback(channel: number = 1, freqHz: number = 2500, gain: number = -6.0) {
    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        await invoke('trigger_demo_feedback', { channel, freqHz, gainDb: gain })
        return
      } catch (e) {
        console.error('Failed to trigger fake feedback in Tauri', e)
        return
      }
    }
    if (currentMode.value === 'auto') {
      activeNotches.value.push({
        channel,
        channel_name: `CH${channel.toString().padStart(2, '0')}`,
        bus: null,
        band: (activeNotches.value.length % 4) + 1,
        freq_hz: freqHz,
        gain_db: gain,
        q: 8.0,
        target: 'ch',
        age_s: 0,
        is_locked: false,
        step_count: 1
      })
      addLog(
        t('log.autoNotch', { target: `Mic ${channel}`, freq_hz: freqHz, gain_db: gain }),
        'approved',
        'log.autoNotch',
        { target: `Mic ${channel}`, channel, freq_hz: freqHz, gain_db: gain }
      )
    } else {
      pendingProposals.value.push({
        id: `demo_${channel}_${freqHz}_${Date.now()}`,
        channel,
        channel_name: `CH${channel.toString().padStart(2, '0')}`,
        bus: null,
        target: 'ch',
        freq_hz: freqHz,
        gain_db: gain,
        q: 8.0,
        confidence_score: 0.92,
        created_at: Date.now() / 1000,
        ttl_remaining_s: 30,
        reason: `Mô phỏng phát hiện hú tại ${freqHz}Hz`
      })
      addLog(
        t('demo.success', { channel, freq: freqHz }),
        'warning',
        'log.feedbackWarning',
        { target: `Mic ${channel}`, channel, freq_hz: freqHz }
      )
    }
  }

  async function exportReport(format: 'json' | 'csv' = 'json') {
    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        const content = await invoke<string>('export_report', { format })
        const blob = new Blob([content], { type: format === 'csv' ? 'text/csv' : 'application/json' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `auto_sound_report_${Date.now()}.${format}`
        a.click()
        URL.revokeObjectURL(url)
        addLog(t('log.exportSuccess', { format: format.toUpperCase() }), 'approved', 'log.exportSuccess', { format: format.toUpperCase() })
      } catch (e) {
        console.error('Failed to export report in Tauri', e)
      }
    }
  }

  async function setPreset(preset: string) {
    currentPreset.value = preset
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem('xklive_last_preset', preset)
    }
    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        await invoke('apply_preset', { preset })
        return
      } catch (e) {
        console.error('Failed to apply preset in Tauri', e)
      }
    }
    if (preset === 'speech') {
      talkoverEnabled.value = true
    } else {
      talkoverEnabled.value = false
    }
    const presetKey = preset === 'foh'
      ? 'presetFoh'
      : preset === 'acoustic'
        ? 'presetAcoustic'
        : preset === 'speech'
          ? 'presetSpeech'
          : 'presetMonitor'
    addLog(t(`header.${presetKey}`), 'approved', 'log.presetApplied', { preset })
  }

  async function setTalkoverConfig(enabled: boolean, micChannel?: number, fxReturn?: number) {
    talkoverEnabled.value = enabled
    if (micChannel !== undefined) {
      talkoverMicChannel.value = micChannel
    }
    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        await invoke('set_talkover_config', {
          enabled,
          micChannel: micChannel ?? null,
          fxReturn: fxReturn ?? null
        })
        return
      } catch (e) {
        console.error('Failed to set talkover config in Tauri', e)
      }
    }
    addLog(
      enabled
        ? `Đã bật Tự động dìm nhạc/vang khi Mic ${talkoverMicChannel.value} nói`
        : 'Đã tắt Tự động dìm nhạc/vang (Talkover)',
      'approved',
      'log.talkoverToggled',
      { status: enabled ? 'ON' : 'OFF', channel: talkoverMicChannel.value }
    )
  }

  async function startGainCalibration(channel: number) {
    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        const raw = await invoke<{ session?: GainCalibrationSession } & GainCalibrationSession>('start_gain_calibration', { channel })
        const session: GainCalibrationSession = raw?.session ? raw.session : raw
        gainSessions.value = { ...gainSessions.value, [channel]: session }
        return session
      } catch (e) {
        console.error('Failed to start gain calibration in Tauri', e)
      }
    }
    const mockSession: GainCalibrationSession = {
      channel,
      state: 'completed',
      status: 'READY',
      duration_s: 10,
      current_headamp_gain_db: 20.0,
      proposed_gain_db: 22.5,
      proposed_gain_change_db: 2.5,
      advice: `Kênh ${channel}: Mức tín hiệu tốt (Peak -14.5 dB). Có thể tăng nhẹ Gain thêm +2.5 dB.`
    }
    gainSessions.value = { ...gainSessions.value, [channel]: mockSession }
    return mockSession
  }

  async function cancelGainCalibration(channel: number) {
    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        await invoke('cancel_gain_calibration', { channel })
      } catch (e) {
        console.error('Failed to cancel gain calibration in Tauri', e)
      }
    }
    const next = { ...gainSessions.value }
    delete next[channel]
    gainSessions.value = next
  }

  async function applyChannelHpf(channel: number, enabled: boolean, freqHz: number = 80): Promise<boolean> {
    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        const state = await invoke<boolean>('apply_channel_hpf', { channel, enabled, freqHz })
        const ch = channels.value.find(c => c.channel === channel)
        if (ch) ch.hpf_enabled = state
        return state
      } catch (e) {
        console.error('Failed to apply channel HPF in Tauri', e)
      }
    }
    const ch = channels.value.find(c => c.channel === channel)
    if (ch) ch.hpf_enabled = enabled
    addLog(
      enabled
        ? `Đã bật lọc ù trầm (Low-Cut ${Math.round(freqHz)}Hz) cho Mic ${channel}`
        : `Đã tắt lọc ù trầm (Low-Cut) cho Mic ${channel}`,
      'approved',
      'log.hpfToggled',
      { channel, status: enabled ? 'ON' : 'OFF', freq_hz: Math.round(freqHz) }
    )
    return enabled
  }

  async function applyManualNotch(
    target: string,
    channel: number,
    bus: number | null,
    freqHz: number,
    gainDb: number = -6.0,
    q: number = 8.0
  ) {
    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        await invoke('apply_manual_notch', {
          target,
          channel,
          bus: bus ?? null,
          freqHz,
          gainDb,
          q
        })
        return
      } catch (e) {
        console.error('Failed to apply manual notch in Tauri', e)
        return
      }
    }

    activeNotches.value.push({
      channel: target === 'ch' ? channel : 0,
      bus: target === 'bus' ? (bus ?? 1) : null,
      band: 3,
      freq_hz: freqHz,
      gain_db: gainDb,
      q,
      target,
      age_s: 0,
      is_locked: false,
      step_count: 1
    })
  }

  async function fetchDiagnostics(): Promise<DiagnosticsData | null> {
    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        return await invoke<DiagnosticsData>('get_diagnostics')
      } catch (e) {
        console.error('Failed to fetch diagnostics in Tauri', e)
        return null
      }
    }
    return null
  }

  async function connectMixer(ip: string, port: number = 10024): Promise<boolean> {
    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        const ok = await invoke<boolean>('connect_mixer', { ip, port })
        if (ok) {
          isMockMode.value = false
          isSimulating.value = false
        }
        return ok
      } catch (e) {
        console.error('Tauri connect mixer error', e)
        return false
      }
    }
    return false
  }

  async function disconnectMixer(): Promise<void> {
    isMockMode.value = false
    isSimulating.value = false
    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        await invoke('disconnect_mixer')
      } catch (e) {
        console.error('Tauri disconnect error', e)
      }
    }
  }

  async function discoverMixers(): Promise<DiscoveredMixer[]> {
    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        const res = await invoke<DiscoveredMixer[]>('discover_mixers_cmd', { timeoutMs: 800, port: 10024 })
        return res || []
      } catch (e) {
        console.error('Tauri discover error', e)
        return []
      }
    }
    return []
  }

  async function listAudioDevices(): Promise<AudioDeviceItem[]> {
    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        const res = await invoke<AudioDeviceItem[]>('list_audio_devices')
        return res || []
      } catch (e) {
        console.error('Tauri list audio devices error', e)
        return []
      }
    }
    return []
  }

  async function startAudioCapture(deviceName?: string): Promise<boolean> {
    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        const ok = await invoke<boolean>('start_audio_capture', { deviceName: deviceName || null })
        return ok
      } catch (e) {
        console.error('Tauri start audio capture error', e)
        return false
      }
    }
    return false
  }

  async function stopAudioCapture(): Promise<void> {
    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        await invoke('stop_audio_capture')
      } catch (e) {
        console.error('Tauri stop audio capture error', e)
      }
    }
  }

  async function fetchDynamicsSuggestions(): Promise<DynamicsResponse> {
    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        return await invoke<DynamicsResponse>('get_dynamics_suggestions')
      } catch (e) {
        console.error('Failed to fetch dynamics suggestions in Tauri', e)
        return { suggestions: [] }
      }
    }
    return { suggestions: [] }
  }

  async function startWizard(
    channel: number = 1,
    maxBoost: number = 3.0,
    dwellTime: number = 1.5
  ): Promise<WizardStartResult> {
    const safeBoost = Math.min(4.0, Math.max(0.5, maxBoost))
    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        return await invoke<WizardStartResult>('start_wizard', {
          channel,
          maxBoostDb: safeBoost,
          dwellTimeS: dwellTime
        })
      } catch (e) {
        console.error('Failed to start wizard in Tauri', e)
        return { success: false, detail: String(e) }
      }
    }
    if (isMockMode.value || isSimulating.value) {
      mockWizardMaxBoost = safeBoost
      mockWizardState = {
        state: 'running',
        target_type: channel === 0 ? 'main' : 'bus',
        target_id: channel,
        current_gain_added: 0.0,
        detected_notches: 0
      }
      return { success: true }
    }
    return { success: false, detail: 'Chưa kết nối tới bàn mixer' }
  }

  async function stopWizard(): Promise<WizardStopResult> {
    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        return await invoke<WizardStopResult>('stop_wizard')
      } catch (e) {
        console.error('Failed to stop wizard in Tauri', e)
        return { success: false }
      }
    }
    mockWizardState = {
      ...mockWizardState,
      state: 'aborted',
      current_gain_added: 0.0
    }
    return { success: true, status: 'aborted' }
  }

  async function getWizardStatus(): Promise<WizardStatusSnapshot> {
    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        return await invoke<WizardStatusSnapshot>('get_wizard_status')
      } catch (e) {
        console.error('Failed to get wizard status in Tauri', e)
        throw e
      }
    }
    if (mockWizardState.state === 'running') {
      const nextGain = Number((mockWizardState.current_gain_added + 1.0).toFixed(1))
      const detected = nextGain >= 2.0 ? 1 : 0
      if (nextGain >= mockWizardMaxBoost) {
        mockWizardState = {
          ...mockWizardState,
          state: 'completed',
          current_gain_added: 0.0,
          detected_notches: detected
        }
      } else {
        mockWizardState = {
          ...mockWizardState,
          current_gain_added: nextGain,
          detected_notches: detected
        }
      }
    }
    return { ...mockWizardState }
  }

  onMounted(() => {
    initEngine()
  })

  onUnmounted(() => {
    if (pollInterval) {
      clearInterval(pollInterval)
      pollInterval = null
    }
  })

  return {
    mixerStatus,
    isMockMode,
    dryRun,
    mixerModel,
    latencyMs,
    rttMs,
    dspLatencyMs,
    xruns,
    isLanRta,
    audioMode,
    currentMode,
    currentPreset,
    snapshotBandsCount,
    talkoverEnabled,
    talkoverIsDucked,
    talkoverMicChannel,
    clipAlerts,
    gainSessions,
    canUndoPanic,
    isSimulating,
    channels,
    activeNotches,
    pendingProposals,
    meters,
    rtaBins,
    peakHoldBins,
    eventLogs,
    setMode,
    setPreset,
    setTalkoverConfig,
    startGainCalibration,
    cancelGainCalibration,
    applyChannelHpf,
    applyManualNotch,
    toggleLiveDemo,
    toggleDryRun,
    triggerPanic,
    undoPanic,
    approveProposal,
    rejectProposal,
    snoozeProposal,
    releaseNotch,
    releaseChannelNotches,
    releaseAllNotches,
    takeSnapshot,
    rollbackSnapshot,
    triggerFakeFeedback,
    exportReport,
    fetchDiagnostics,
    fetchDynamicsSuggestions,
    startWizard,
    stopWizard,
    getWizardStatus,
    connectMixer,
    disconnectMixer,
    discoverMixers,
    listAudioDevices,
    startAudioCapture,
    stopAudioCapture,
    toggleLock,
    toggleWhitelist,
    clearLogs,
    addLog
  }
}
