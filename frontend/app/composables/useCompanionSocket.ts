import { ref, onMounted, onUnmounted } from 'vue'

export interface ActiveNotch {
  channel: number
  bus: number | null
  band: number
  freq_hz: number
  gain_db: number
  q: number
  target: string
  age_s: number
  is_locked: boolean
  step_count: number
}

export interface Proposal {
  id: string
  channel: number
  bus: number | null
  target: string
  freq_hz: number
  gain_db: number
  q: number
  confidence_score: number
  created_at: number
  ttl_remaining_s: number
  reason: string
}

export interface LogEntry {
  id: number
  time: string
  text: string
  type: 'normal' | 'panic' | 'approved' | 'warning'
}

export function useCompanionSocket() {
  const mixerStatus = ref<'CONNECTED' | 'RECONNECTING' | 'DISCONNECTED'>('DISCONNECTED')
  const mixerModel = ref('XR18 v1.18')
  const latencyMs = ref(64.0)
  const xruns = ref(0)
  const isLanRta = ref(false)
  const currentMode = ref<'auto' | 'semi' | 'manual'>('semi')

  const activeNotches = ref<ActiveNotch[]>([])
  const pendingProposals = ref<Proposal[]>([])
  const meters = ref<number[]>(new Array(16).fill(0))
  const rtaBins = ref<number[]>(new Array(100).fill(-60))
  const peakHoldBins = ref<number[]>(new Array(100).fill(-60))
  const eventLogs = ref<LogEntry[]>([])

  let ws: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let logIdCounter = 1

  function addLog(text: string, type: 'normal' | 'panic' | 'approved' | 'warning' = 'normal') {
    const d = new Date()
    const timeStr = d.toTimeString().split(' ')[0]
    eventLogs.value.unshift({
      id: logIdCounter++,
      time: timeStr,
      text,
      type
    })
    if (eventLogs.value.length > 200) {
      eventLogs.value.pop()
    }
  }

  function clearLogs() {
    eventLogs.value = []
  }

  function connect() {
    if (import.meta.server) return

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    // Nếu chạy nuxt dev trên port 3000, kết nối tới backend port 8000
    const host = window.location.port === '3000' ? `${window.location.hostname}:8000` : window.location.host
    const wsUrl = `${proto}//${host}/ws`

    ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      mixerStatus.value = 'CONNECTED'
      addLog('Đã kết nối luồng dữ liệu thời gian thực (WebSocket)', 'approved')
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
      mixerStatus.value = 'RECONNECTING'
      addLog('Mất kết nối WebSocket. Đang tự động kết nối lại...', 'warning')
      reconnectTimer = setTimeout(connect, 1500)
    }

    ws.onerror = () => {
      mixerStatus.value = 'DISCONNECTED'
    }
  }

  function handleMessage(msg: any) {
    if (msg.type === 'state_snapshot') {
      currentMode.value = msg.status.mode
      mixerStatus.value = msg.status.mixer_state
      mixerModel.value = `${msg.status.model} v${msg.status.firmware}`
      latencyMs.value = msg.status.latency_ms
      xruns.value = msg.status.xruns
      isLanRta.value = msg.status.lan_rta_mode
      activeNotches.value = msg.notches || []
      pendingProposals.value = msg.proposals || []
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
      addLog(`🚨 PANIC ĐÃ KÍCH HOẠT: Hoàn tác ${msg.released_count} notch về 0 dB`, 'panic')
      refreshNotches()
    } else if (['proposal_resolved', 'notch_updated', 'mode_updated'].includes(msg.type)) {
      refreshStatus()
      refreshNotches()
      refreshProposals()
    }
  }

  function getApiBase(): string {
    if (import.meta.server) return ''
    return window.location.port === '3000' ? `http://${window.location.hostname}:8000` : ''
  }

  async function setMode(mode: 'auto' | 'semi' | 'manual') {
    if (mode === 'auto') {
      const ok = confirm('CẢNH BÁO SÂN KHẤU: Bạn có chắc chắn muốn chuyển sang chế độ AUTO (Hệ thống tự động hạ notch ngay khi phát hiện hú mà không cần soundman duyệt)?')
      if (!ok) return
    }
    try {
      const res = await fetch(`${getApiBase()}/api/v1/mode`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode, confirm: true })
      })
      const data = await res.json()
      if (data.success) {
        currentMode.value = mode
        addLog(`Đã chuyển sang chế độ: ${mode.toUpperCase()}`, 'approved')
      }
    } catch (e: any) {
      alert(`Lỗi đổi chế độ: ${e.message}`)
    }
  }

  async function triggerPanic() {
    try {
      const res = await fetch(`${getApiBase()}/api/v1/panic`, { method: 'POST' })
      const data = await res.json()
      addLog(data.message, 'panic')
      refreshNotches()
    } catch (e: any) {
      alert(`Lỗi thực thi PANIC: ${e.message}`)
    }
  }

  async function undoPanic() {
    try {
      const res = await fetch(`${getApiBase()}/api/v1/panic/undo`, { method: 'POST' })
      const data = await res.json()
      addLog(data.message, 'approved')
      refreshNotches()
    } catch (e: any) {
      alert(`Lỗi hoàn tác PANIC: ${e.message}`)
    }
  }

  async function approveProposal(id: string) {
    try {
      await fetch(`${getApiBase()}/api/v1/proposals/${id}/approve`, { method: 'POST' })
      refreshProposals()
      refreshNotches()
    } catch (e) {
      console.error(e)
    }
  }

  async function rejectProposal(id: string) {
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

  async function releaseAllNotches() {
    if (confirm('Nhả toàn bộ notch đang hoạt động về 0.0 dB?')) {
      await triggerPanic()
    }
  }

  async function takeSnapshot() {
    try {
      const res = await fetch(`${getApiBase()}/api/v1/snapshot/take`, { method: 'POST' })
      const data = await res.json()
      addLog(`📸 Đã chụp snapshot PEQ (${data.bands_count} bands)`, 'approved')
    } catch (e: any) {
      alert(`Lỗi chụp snapshot: ${e.message}`)
    }
  }

  async function rollbackSnapshot() {
    if (!confirm('Khôi phục toàn bộ PEQ về bản chụp snapshot ban đầu?')) return
    try {
      const res = await fetch(`${getApiBase()}/api/v1/snapshot/rollback`, { method: 'POST' })
      const data = await res.json()
      addLog(data.message, data.partial_failure ? 'warning' : 'approved')
    } catch (e: any) {
      alert(`Lỗi hoàn tác snapshot: ${e.message}`)
    }
  }

  async function refreshStatus() {
    try {
      const res = await fetch(`${getApiBase()}/api/v1/status`)
      const data = await res.json()
      xruns.value = data.xruns
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

  onMounted(() => {
    connect()
  })

  onUnmounted(() => {
    if (reconnectTimer) clearTimeout(reconnectTimer)
    if (ws) ws.close()
  })

  return {
    mixerStatus,
    mixerModel,
    latencyMs,
    xruns,
    isLanRta,
    currentMode,
    activeNotches,
    pendingProposals,
    meters,
    rtaBins,
    peakHoldBins,
    eventLogs,
    setMode,
    triggerPanic,
    undoPanic,
    approveProposal,
    rejectProposal,
    snoozeProposal,
    releaseNotch,
    releaseAllNotches,
    takeSnapshot,
    rollbackSnapshot,
    clearLogs,
    addLog
  }
}
