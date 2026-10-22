import { ref, onMounted, onUnmounted } from 'vue'
import { useI18n } from '~/composables/useI18n'

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
}

export interface LogEntry {
  id: number
  time: string
  text?: string
  text_code?: string
  params?: Record<string, string | number>
  type: 'normal' | 'panic' | 'approved' | 'warning'
}

export function useCompanionSocket() {
  const { t } = useI18n()

  const mixerStatus = ref<'CONNECTED' | 'RECONNECTING' | 'DISCONNECTED' | 'MOCK'>('DISCONNECTED')
  const isMockMode = ref(false)
  const dryRun = ref(false)
  const mixerModel = ref('XR18 v1.18')
  const latencyMs = ref(64.0)
  const rttMs = ref<number | null>(null)
  const dspLatencyMs = ref<number>(42.7)
  const firmwareReason = ref('')
  const xruns = ref(0)
  const isLanRta = ref(false)
  const currentMode = ref<'auto' | 'semi' | 'manual'>('semi')

  const activeNotches = ref<ActiveNotch[]>([])
  const pendingProposals = ref<Proposal[]>([])
  const channels = ref<ChannelInfo[]>([])
  const meters = ref<number[]>(new Array(16).fill(0))
  const rtaBins = ref<number[]>(new Array(100).fill(-60))
  const peakHoldBins = ref<number[]>(new Array(100).fill(-60))
  const eventLogs = ref<LogEntry[]>([])

  let ws: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let logIdCounter = 1

  function playAlertChime() {
    try {
      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext
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
      // AudioContext policy
    }
  }

  function addLog(
    text: string,
    type: 'normal' | 'panic' | 'approved' | 'warning' = 'normal',
    text_code?: string,
    params?: Record<string, string | number>
  ) {
    const d = new Date()
    const timeStr = d.toTimeString().split(' ')[0]
    eventLogs.value.unshift({
      id: logIdCounter++,
      time: timeStr,
      text,
      text_code,
      params,
      type
    })
    if (eventLogs.value.length > 200) {
      eventLogs.value.pop()
    }
  }

  function clearLogs() {
    eventLogs.value = []
  }

  let pollInterval: ReturnType<typeof setInterval> | null = null

  function isTauriEnv(): boolean {
    return typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window)
  }

  function updateFromSnapshot(snapshot: any) {
    if (!snapshot) return
    mixerStatus.value = snapshot.mixer_status
    mixerModel.value = snapshot.mixer_model
    currentMode.value = snapshot.current_mode as any
    dryRun.value = !!snapshot.dry_run
    rttMs.value = snapshot.rtt_ms ?? null
    dspLatencyMs.value = snapshot.dsp_latency_ms ?? 4.2
    latencyMs.value = snapshot.latency_ms ?? 12.5

    activeNotches.value = snapshot.active_notches || []
    pendingProposals.value = snapshot.pending_proposals || []
    channels.value = snapshot.channels || []
    if (snapshot.meters && snapshot.meters.length > 0) {
      meters.value = snapshot.meters.slice(0, 16)
    }
    if (snapshot.rta_bins && snapshot.rta_bins.length > 0) {
      rtaBins.value = snapshot.rta_bins
      for (let i = 0; i < snapshot.rta_bins.length; i++) {
        peakHoldBins.value[i] = Math.max((peakHoldBins.value[i] || -60) - 0.4, snapshot.rta_bins[i])
      }
    }
    if (snapshot.event_logs && snapshot.event_logs.length > 0) {
      eventLogs.value = snapshot.event_logs
    }
  }

  async function checkAndInitTauri(): Promise<boolean> {
    if (!isTauriEnv()) return false
    try {
      const { invoke } = await import('@tauri-apps/api/core')
      const snapshot: any = await invoke('get_state')
      updateFromSnapshot(snapshot)

      if (!pollInterval) {
        pollInterval = setInterval(async () => {
          try {
            const s: any = await invoke('get_state')
            updateFromSnapshot(s)
          } catch (e) {
            console.error('Tauri state poll error', e)
          }
        }, 60)
      }
      addLog(t('log.connected') || 'Tauri Desktop Engine connected', 'approved')
      return true
    } catch (e) {
      console.warn('Tauri init failed, falling back to WebSocket', e)
      return false
    }
  }

  async function connect() {
    if (import.meta.server) return

    const isTauri = await checkAndInitTauri()
    if (isTauri) return

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.port === '3000' ? `${window.location.hostname}:8000` : window.location.host
    const wsUrl = `${proto}//${host}/ws`

    ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      mixerStatus.value = isMockMode.value ? 'MOCK' : 'CONNECTED'
      addLog(t('log.connected'), 'approved', 'log.connected')
    }

    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data)
        handleMessage(msg)
      } catch (err) {
        console.error('WS message error', err)
      }
    }

    ws.onclose = () => {
      mixerStatus.value = isMockMode.value ? 'MOCK' : 'RECONNECTING'
      addLog(t('log.disconnected'), 'warning', 'log.disconnected')
      reconnectTimer = setTimeout(connect, 1500)
    }

    ws.onerror = () => {
      mixerStatus.value = isMockMode.value ? 'MOCK' : 'DISCONNECTED'
    }
  }

  function handleMessage(msg: any) {
    if (msg.type === 'state_snapshot') {
      currentMode.value = msg.status.mode
      isMockMode.value = !!msg.status.mock_mode
      dryRun.value = !!msg.status.dry_run
      rttMs.value = msg.status.rtt_ms ?? null
      dspLatencyMs.value = msg.status.dsp_latency_ms ?? 42.7
      firmwareReason.value = msg.status.firmware_reason ?? ''
      mixerStatus.value = isMockMode.value ? 'MOCK' : msg.status.mixer_state
      mixerModel.value = msg.status.firmware ? `${msg.status.model} v${msg.status.firmware}` : msg.status.model
      latencyMs.value = msg.status.latency_ms ?? msg.status.dsp_latency_ms ?? 42.7
      xruns.value = msg.status.xruns
      isLanRta.value = msg.status.lan_rta_mode
      activeNotches.value = msg.notches || []

      const prevCount = pendingProposals.value.length
      pendingProposals.value = msg.proposals || []
      if (currentMode.value === 'semi' && pendingProposals.value.length > prevCount) {
        playAlertChime()
      }
    } else if (msg.type === 'telemetry_frame') {
      if (msg.meters) {
        meters.value = msg.meters.slice(0, 16)
      }
      if (msg.rta && msg.rta.length > 0) {
        rtaBins.value = msg.rta
        for (let i = 0; i < msg.rta.length; i++) {
          peakHoldBins.value[i] = Math.max((peakHoldBins.value[i] || -60) - 0.4, msg.rta[i])
        }
      }
    } else if (msg.type === 'panic_event') {
      const count = msg.released_count ?? 0
      addLog(t('log.panicTriggered', { count }), 'panic', 'log.panicTriggered', { count })
      refreshNotches()
    } else if (msg.type === 'log_event') {
      if (msg.record) {
        const lvl = msg.record.level
        const logType = lvl === 'CRITICAL' || lvl === 'ERROR' ? 'panic' : (lvl === 'WARNING' ? 'warning' : 'normal')
        addLog(msg.record.message, logType)
      }
    } else if (['proposal_resolved', 'notch_updated', 'mode_updated'].includes(msg.type)) {
      refreshStatus()
      refreshNotches()
      refreshProposals()
      refreshChannels()
    }
  }

  function getApiBase(): string {
    if (import.meta.server) return ''
    return window.location.port === '3000' ? `http://${window.location.hostname}:8000` : ''
  }

  async function setMode(mode: 'auto' | 'semi' | 'manual') {
    if (mode === 'auto') {
      const ok = confirm(t('modes.confirmAuto'))
      if (!ok) return
    }
    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        await invoke('set_mode', { mode })
        currentMode.value = mode
        const modeLabel = mode.toUpperCase()
        addLog(t('log.modeChanged', { mode: modeLabel }), 'approved', 'log.modeChanged', { mode: modeLabel })
        return
      } catch (e: any) {
        alert(t('errors.modeChange', { msg: e.message }))
        return
      }
    }
    try {
      const res = await fetch(`${getApiBase()}/api/v1/mode`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode, confirm: true })
      })
      const data = await res.json()
      if (!res.ok || !data.success) {
        throw new Error(data.detail || 'Failed to change mode')
      }
      currentMode.value = mode
      const modeLabel = mode.toUpperCase()
      addLog(t('log.modeChanged', { mode: modeLabel }), 'approved', 'log.modeChanged', { mode: modeLabel })
    } catch (e: any) {
      alert(t('errors.modeChange', { msg: e.message }))
    }
  }

  async function toggleDryRun(enabled?: boolean) {
    const target = enabled !== undefined ? enabled : !dryRun.value
    try {
      const res = await fetch(`${getApiBase()}/api/v1/dry_run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dry_run: target })
      })
      const data = await res.json()
      if (data.success) {
        dryRun.value = data.dry_run
        const msg = dryRun.value ? t('dryRun.enabled') : t('dryRun.disabled')
        addLog(msg, dryRun.value ? 'warning' : 'approved')
      }
    } catch (e) {
      console.error('Failed to toggle dry-run', e)
    }
  }

  async function triggerPanic() {
    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        await invoke('panic_reset')
        addLog(t('log.panicTriggered', { count: activeNotches.value.length }) || 'PANIC RESET', 'panic')
        return
      } catch (e: any) {
        alert(t('errors.panic', { msg: e.message }))
        return
      }
    }
    try {
      const res = await fetch(`${getApiBase()}/api/v1/panic`, { method: 'POST' })
      const data = await res.json()
      if (!res.ok || !data.success) {
        throw new Error(data.detail || 'PANIC failed')
      }
      const count = data.released_count ?? 0
      addLog(t('log.panicTriggered', { count }), 'panic', 'log.panicTriggered', { count })
      refreshNotches()
    } catch (e: any) {
      alert(t('errors.panic', { msg: e.message }))
    }
  }

  async function undoPanic() {
    try {
      const res = await fetch(`${getApiBase()}/api/v1/panic/undo`, { method: 'POST' })
      const data = await res.json()
      if (!res.ok || !data.success) {
        throw new Error(data.detail || 'Undo PANIC failed')
      }
      const count = data.restored_count ?? 0
      addLog(t('reasons.undo_panic'), 'approved', 'reasons.undo_panic', { count })
      refreshNotches()
    } catch (e: any) {
      alert(t('errors.undoPanic', { msg: e.message }))
    }
  }

  async function approveProposal(id: string) {
    if (isTauriEnv()) {
      const p = pendingProposals.value.find(item => item.id === id)
      if (p) {
        try {
          const { invoke } = await import('@tauri-apps/api/core')
          await invoke('approve_proposal', { channel: p.channel, freqHz: p.freq_hz })
          return
        } catch (e) {
          console.error(e)
          return
        }
      }
    }
    try {
      await fetch(`${getApiBase()}/api/v1/proposals/${id}/approve`, { method: 'POST' })
      refreshProposals()
      refreshNotches()
    } catch (e) {
      console.error(e)
    }
  }

  async function rejectProposal(id: string) {
    if (isTauriEnv()) {
      const p = pendingProposals.value.find(item => item.id === id)
      if (p) {
        try {
          const { invoke } = await import('@tauri-apps/api/core')
          await invoke('reject_proposal', { channel: p.channel, freqHz: p.freq_hz })
          return
        } catch (e) {
          console.error(e)
          return
        }
      }
    }
    try {
      await fetch(`${getApiBase()}/api/v1/proposals/${id}/reject`, { method: 'POST' })
      refreshProposals()
    } catch (e) {
      console.error(e)
    }
  }

  async function snoozeProposal(id: string) {
    try {
      await fetch(`${getApiBase()}/api/v1/proposals/${id}/snooze`, { method: 'POST' })
      refreshProposals()
    } catch (e) {
      console.error(e)
    }
  }

  async function releaseNotch(channel: number, band: number, target: string, bus?: number | null) {
    try {
      await fetch(`${getApiBase()}/api/v1/notches/release`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ channel, band, target, bus: bus ?? null })
      })
      refreshNotches()
    } catch (e) {
      console.error(e)
    }
  }

  async function undoNotch(channel: number, band: number, target: string = 'channel', bus?: number | null) {
    try {
      const res = await fetch(`${getApiBase()}/api/v1/notches/undo`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ channel, band, target, bus: bus ?? null })
      })
      const data = await res.json()
      if (data.success) {
        addLog(t('notches.released', { band }) || `Released Band ${band}`, 'approved')
        refreshNotches()
      }
    } catch (e) {
      console.error('Failed to undo notch', e)
    }
  }

  async function releaseAllNotches() {
    if (confirm(t('panic.confirmReleaseAll'))) {
      await triggerPanic()
    }
  }

  async function takeSnapshot() {
    try {
      const res = await fetch(`${getApiBase()}/api/v1/snapshot/take`, { method: 'POST' })
      const data = await res.json()
      if (!res.ok || !data.success) {
        throw new Error(data.detail || 'Take snapshot failed')
      }
      const count = data.bands_count ?? 0
      addLog(t('log.snapshotTaken', { count }), 'approved', 'log.snapshotTaken', { count })
    } catch (e: any) {
      alert(t('errors.snapshot', { msg: e.message }))
    }
  }

  async function rollbackSnapshot() {
    if (!confirm(t('snapshot.confirmRollback'))) return
    try {
      const res = await fetch(`${getApiBase()}/api/v1/snapshot/rollback`, { method: 'POST' })
      const data = await res.json()
      if (!res.ok || !data.success) {
        throw new Error(data.detail || 'Rollback snapshot failed')
      }
      const msgCode = data.message_code ? `messages.${data.message_code}` : ''
      const msgText = msgCode ? t(msgCode, data.params) : data.message
      addLog(msgText, data.partial_failure ? 'warning' : 'approved', msgCode, data.params)
    } catch (e: any) {
      alert(t('errors.rollback', { msg: e.message }))
    }
  }

  async function triggerFakeFeedback(channel: number = 1, freqHz: number = 2500, gain: number = -6.0) {
    if (isTauriEnv()) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        await invoke('trigger_demo_feedback', { channel, freqHz })
        addLog(t('demo.success', { channel, freq: freqHz }) || `Feedback demo triggered on CH${channel}`, 'warning')
        return
      } catch (e) {
        console.error('Failed to trigger fake feedback in Tauri', e)
        return
      }
    }
    try {
      const res = await fetch(`${getApiBase()}/api/v1/demo/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ channel, freq_hz: freqHz, gain })
      })
      const data = await res.json()
      if (data.success) {
        addLog(t('demo.success', { channel, freq: freqHz }), 'warning')
      }
    } catch (e) {
      console.error('Failed to trigger fake feedback', e)
    }
  }

  function exportReport(format: 'json' | 'csv' = 'json') {
    const url = `${getApiBase()}/api/v1/report/export?format=${format}`
    window.open(url, '_blank')
  }

  async function fetchDiagnostics() {
    try {
      const res = await fetch(`${getApiBase()}/api/v1/diagnostics`)
      return await res.json()
    } catch (e) {
      console.error('Failed to fetch diagnostics', e)
      return null
    }
  }

  async function fetchRoutingCheck() {
    try {
      const res = await fetch(`${getApiBase()}/api/v1/audio/routing-check`)
      return await res.json()
    } catch (e) {
      console.error('Failed to fetch routing check', e)
      return null
    }
  }

  async function fetchDynamicsSuggestions() {
    try {
      const res = await fetch(`${getApiBase()}/api/v1/dynamics/suggestions`)
      return await res.json()
    } catch (e) {
      console.error('Failed to fetch dynamics suggestions', e)
      return null
    }
  }

  async function startWizard(channel: number = 1, maxBoost: number = 3.0, dwellTime: number = 1.5) {
    try {
      const res = await fetch(`${getApiBase()}/api/v1/wizard/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          target: 'main',
          channel,
          max_boost_db: maxBoost,
          step_interval_s: dwellTime,
          dwell_time_s: dwellTime
        })
      })
      return await res.json()
    } catch (e) {
      console.error('Failed to start wizard', e)
      return { success: false, detail: String(e) }
    }
  }

  async function stopWizard() {
    try {
      const res = await fetch(`${getApiBase()}/api/v1/wizard/stop`, { method: 'POST' })
      return await res.json()
    } catch (e) {
      console.error('Failed to stop wizard', e)
      return { success: false }
    }
  }

  async function getWizardStatus() {
    try {
      const res = await fetch(`${getApiBase()}/api/v1/wizard/status`)
      return await res.json()
    } catch (e) {
      console.error('Failed to get wizard status', e)
      return null
    }
  }

  async function refreshStatus() {
    try {
      const res = await fetch(`${getApiBase()}/api/v1/status`)
      const data = await res.json()
      xruns.value = data.xruns
      isMockMode.value = !!data.mock_mode
      dryRun.value = !!data.dry_run
      rttMs.value = data.rtt_ms ?? null
      dspLatencyMs.value = data.dsp_latency_ms ?? 42.7
    } catch (e) {
      console.error(e)
    }
  }

  async function refreshNotches() {
    try {
      const res = await fetch(`${getApiBase()}/api/v1/notches`)
      const data = await res.json()
      activeNotches.value = data.notches || []
    } catch (e) {
      console.error(e)
    }
  }

  async function refreshProposals() {
    try {
      const res = await fetch(`${getApiBase()}/api/v1/proposals`)
      const data = await res.json()
      pendingProposals.value = data.proposals || []
    } catch (e) {
      console.error(e)
    }
  }

  async function refreshChannels() {
    try {
      const res = await fetch(`${getApiBase()}/api/v1/channels`)
      const data = await res.json()
      channels.value = data.channels || []
    } catch (e) {
      console.error(e)
    }
  }

  onMounted(() => {
    connect()
    refreshChannels()
  })

  onUnmounted(() => {
    if (pollInterval) clearInterval(pollInterval)
    if (reconnectTimer) clearTimeout(reconnectTimer)
    if (ws) ws.close()
  })

  return {
    mixerStatus,
    isMockMode,
    dryRun,
    mixerModel,
    latencyMs,
    rttMs,
    dspLatencyMs,
    firmwareReason,
    xruns,
    isLanRta,
    currentMode,
    channels,
    activeNotches,
    pendingProposals,
    meters,
    rtaBins,
    peakHoldBins,
    eventLogs,
    setMode,
    toggleDryRun,
    triggerPanic,
    undoPanic,
    approveProposal,
    rejectProposal,
    snoozeProposal,
    releaseNotch,
    undoNotch,
    releaseAllNotches,
    takeSnapshot,
    rollbackSnapshot,
    triggerFakeFeedback,
    exportReport,
    fetchDiagnostics,
    fetchRoutingCheck,
    fetchDynamicsSuggestions,
    startWizard,
    stopWizard,
    getWizardStatus,
    clearLogs,
    addLog
  }
}
