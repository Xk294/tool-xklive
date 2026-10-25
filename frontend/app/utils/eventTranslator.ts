import type { LogEntry, MixerConnectionStatus } from '~/composables/useCompanionSocket'

export const METER_CLIP_THRESHOLD_DB = -3
export const METER_ACTIVE_THRESHOLD_DB = -35
export const METER_FLOOR_DB = -60
export const METER_SPAN_DB = 60

export function linearToDb(lin: number): number {
  return lin > 0 ? 20 * Math.log10(lin) : METER_FLOOR_DB
}

export function getMixerChannelCount(model: string, channelsLen?: number): number {
  const upper = (model || '').toUpperCase()
  if (upper.includes('XR12') || upper.includes('MR12')) {
    return 12
  }
  if (upper.includes('XR16') || upper.includes('XR18') || upper.includes('MR18')) {
    return 16
  }
  if (channelsLen && channelsLen > 0) {
    return channelsLen
  }
  return 16
}

export function formatFrequency(hz: number): string {
  if (hz >= 1000) {
    const khz = (hz / 1000).toFixed(1)
    return `${khz.replace('.0', '')} kHz`
  }
  return `${Math.round(hz)} Hz`
}

export function formatFriendlyTarget(item: {
  target?: string
  channel: number
  bus?: number | null
}): string {
  if (item.target === 'bus') {
    return `Loa Monitor Bus ${item.bus || item.channel || 1}`
  }
  if (item.target === 'main' || item.target === 'lr' || item.channel <= 0) {
    return 'Loa Chính (Main LR)'
  }
  return `Mic ${item.channel}`
}

export function extractSuspectHint(reason?: string | null): string | null {
  if (!reason) return null
  const hintIdx = reason.indexOf('(Nghi ngờ từ Mic')
  return hintIdx !== -1 ? reason.slice(hintIdx) : null
}

export function isNotchAttributedToMic(
  notch: { target?: string; channel: number; suspected_channel?: number | null; reason?: string | null },
  channel: number
): boolean {
  if (notch.target === 'bus') return false
  if (notch.channel === channel) return true
  if (notch.channel === 0) {
    if (notch.suspected_channel === channel) return true
    if (notch.reason) {
      return new RegExp(`\\(Nghi ngờ từ Mic\\s+${channel}\\b`).test(notch.reason)
    }
  }
  return false
}

export function formatTargetName(
  item: { target: string; channel: number; bus?: number | null; channel_name?: string; reason?: string },
  t: (key: string, params?: Record<string, string | number>) => string
): string {
  let base = ''
  if (item.target === 'main' || item.channel === 0) {
    base = t('notches.mainLr')
  } else if (item.target === 'bus') {
    base = t('notches.bus', { n: item.bus ?? '' })
  } else if (!item.channel_name) {
    base = t('notches.channel', { n: item.channel })
  } else {
    const match = item.channel_name.match(/^(?:K\u00eanh|Ch)\s*0?(\d+)$/i)
    if (match && match[1]) {
      base = t('notches.channel', { n: match[1] })
    } else {
      base = item.channel_name
    }
  }
  const suspectHint = extractSuspectHint(item.reason)
  return suspectHint ? `${base} ${suspectHint}` : base
}

type LogFormatter = (params: Record<string, string | number>) => string

const CODED_EVENT_FORMATTERS: Record<string, LogFormatter> = {
  'log.manualOverride': (p) => {
    const target = p.target || (p.channel ? `Mic ${p.channel}` : 'kênh')
    return `Đang có người chỉnh tay ${target}. Tạm dừng can thiệp tự động 10 giây để nhường quyền.`
  },
  'log.mixerConnected': () => 'Đã kết nối thành công với bàn mixer. Sẵn sàng hoạt động.',
  'log.mixerDisconnected': () => 'Đã ngắt kết nối với bàn mixer.',
  'log.panicTriggered': (p) =>
    `ĐÃ DỪNG KHẨN: Trả lại toàn bộ ${p.count ?? ''} điểm cắt hú về trạng thái gốc.`.replace(/\s+/g, ' '),
  'messages.panic_triggered': (p) =>
    `ĐÃ DỪNG KHẨN: Trả lại toàn bộ ${p.count ?? ''} điểm cắt hú về trạng thái gốc.`.replace(/\s+/g, ' '),
  'messages.panic_undone': (p) =>
    `Đã hoàn tác lệnh dừng khẩn: Phục hồi ${p.count ?? 0} điểm chống hú.`,
  'log.modeChanged': (p) => `Đã chuyển chế độ bảo vệ sang: ${p.mode ?? ''}.`,
  'log.autoNotch': (p) => {
    const freq = p.freq_hz ? formatFrequency(Number(p.freq_hz)) : ''
    const target = p.target || (p.channel ? `Mic ${p.channel}` : 'hệ thống')
    return `Đã tự động hạ điểm hú trên ${target} tại ${freq} (${p.gain_db ?? -3} dB).`
  },
  'messages.proposal_approved': (p) => {
    const freq = p.freq_hz ? formatFrequency(Number(p.freq_hz)) : ''
    return `Đã duyệt hạ điểm hú tại ${freq}.`
  },
  'messages.proposal_rejected': () => 'Đã bỏ qua đề xuất cắt hú.',
  'messages.channel_snoozed': (p) =>
    `Đã tạm khóa Kênh ${p.channel ?? ''} trong ${p.duration_s ?? 60} giây.`,
  'messages.notch_released': (p) =>
    p.gain_db !== undefined
      ? `Đã nhả bộ lọc Band ${p.band ?? ''} trên ${p.target ?? 'kênh'} về ${p.gain_db} dB.`
      : `Đã nhả bộ lọc Band ${p.band ?? ''} về mức ban đầu.`,
  'log.manualNotch': (p) => {
    const freq = p.freq_hz ? formatFrequency(Number(p.freq_hz)) : ''
    return `Đã hạ điểm hú thủ công tại ${freq} (${p.gain_db ?? -6} dB).`
  },
  'log.manualNotchRejected': (p) =>
    `Không thể áp dụng cắt hú thủ công: ${p.reason ?? 'Vượt giới hạn an toàn'}.`,
  'log.proposalRejectedBySafety': (p) =>
    `Chốt an toàn từ chối đề xuất cắt hú: ${p.reason ?? 'Đang khóa bảo vệ'}.`,
  'log.feedbackWarning': (p) => {
    const freq = p.freq_hz ? formatFrequency(Number(p.freq_hz)) : ''
    const target = p.target || (p.channel ? `Mic ${p.channel}` : 'hệ thống')
    return `Phát hiện nguy cơ hú tại ${freq} trên ${target}.`
  },
  'log.snapshotTaken': (p) => `Đã lưu bản chụp an toàn (${p.count ?? 0} điểm PEQ).`,
  'log.snapshotRollback': () => 'Đã khôi phục toàn bộ cài đặt PEQ về bản chụp ban đầu.',
  'log.exportSuccess': (p) => `Đã xuất tệp báo cáo ${p.format ?? 'JSON'} thành công.`,
  'log.wizardStarted': (p) => `Bắt đầu cân phòng tự động trên ${p.target ?? 'hệ thống'}.`,
  'log.wizardNotch': (p) => {
    const freq = p.freq_hz ? formatFrequency(Number(p.freq_hz)) : ''
    return `[Cân phòng] Đã xử lý điểm cộng hưởng tại ${freq} (${p.gain_db ?? -4.5} dB).`
  },
  'wizard.completed': (p) => `Hoàn tất cân phòng an toàn (${p.count ?? 0} điểm hú được xử lý).`,
  'wizard.aborted': () => 'Đã dừng cân phòng và trả âm lượng về mức an toàn.',
  'log.clipGuardian': (p) =>
    `Mic ${p.channel ?? ''} đang bị quá tải âm lượng! Hãy vặn nhỏ Gain trên mixer.`,
  'log.presetApplied': (p) => {
    const map: Record<string, string> = {
      monitor: 'Loa Kiểm Âm Sân Khấu (Monitor)',
      foh: 'Loa Hội Trường Chính (Main LR)',
      acoustic: 'Nhạc Acoustic / Ca đoàn (Cắt siêu hẹp giữ tiếng)',
      speech: 'Hội nghị / Tiệc cưới / MC (Bắt hú nhạy + Tự ngắt vang)'
    }
    const label = map[String(p.preset || '')] || String(p.preset || 'Mặc định')
    return `Đã áp dụng cấu hình bảo vệ: ${label}.`
  },
  'log.talkoverToggled': (p) => {
    const isOn = p.status === 'ON' || p.enabled === 1 || p.enabled === 'true'
    const ch = p.channel ?? p.mic_channel ?? 1
    return isOn
      ? `Đã bật tự động ngắt vang (Reverb) khi Mic ${ch} phát biểu.`
      : 'Đã tắt chế độ tự động ngắt vang khi MC nói.'
  },
  'log.talkoverState': (p) => {
    const isDucked =
      p.is_ducked === true
      || p.is_ducked === 'true'
      || p.ducked === 'ON'
      || p.ducked === 1
      || p.ducked === 'true'
    return isDucked
      ? `MC đang phát biểu (Mic ${p.channel ?? 1}) — Tự động dìm tiếng vang Reverb.`
      : 'MC ngừng nói — Đã mở lại tiếng vang Reverb cho ca sĩ.'
  },
  'log.gainCalibStarted': (p) =>
    `Đang đo âm lượng chuẩn 10 giây cho Mic ${p.channel ?? ''} — Hãy nói đều vào micro.`,
  'log.hpfToggled': (p) => {
    const isOn = p.status === 'ON' || p.enabled === 1 || p.enabled === 'true'
    return isOn
      ? `Đã bật lọc ù/bụp âm trầm (${p.freq_hz ?? 80} Hz) cho Mic ${p.channel ?? ''}.`
      : `Đã tắt lọc ù trầm cho Mic ${p.channel ?? ''}.`
  },
  'log.whitelistToggled': (p) =>
    p.whitelisted === 1 || p.whitelisted === 'true'
      ? `Đã chuyển Kênh ${p.channel ?? ''} sang chế độ Micro (Bật bảo vệ chống hú).`
      : `Đã chuyển Kênh ${p.channel ?? ''} sang chế độ Nhạc cụ / Playback (Khóa bảo vệ EQ).`,
  'log.lockToggled': (p) =>
    p.locked === 1 || p.locked === 'true'
      ? `Đã khóa an toàn Kênh ${p.channel ?? ''} (Ngừng tự động cắt EQ).`
      : `Đã mở khóa Kênh ${p.channel ?? ''}.`,
  'log.audioFallbackLanRta': (p) =>
    `Không mở được cổng USB Audio (${p.error ?? 'Không tìm thấy'}) — Tự động chuyển sang chế độ LAN RTA 100-Band.`,
  'log.audioCaptureStarted': (p) =>
    `Đã kích hoạt thu âm đa kênh USB từ thiết bị ${p.device ?? 'Mặc định'}.`,
  'log.audioCaptureStopped': () => 'Đã dừng luồng thu âm phân tích phổ.',
  'log.dryRunToggled': (p) =>
    p.enabled === 1 || p.enabled === 'true'
      ? 'Chế độ Chạy Thử ĐANG BẬT: Chỉ mô phỏng, không gửi lệnh xuống mixer.'
      : 'Chế độ Chạy Thử ĐÃ TẮT: Sẵn sàng gửi lệnh điều khiển thật xuống mixer.',
  'reasons.auto_release': (p) =>
    `Đã tự động nhả dần bộ lọc Band ${p.band ?? ''} trên ${p.target ?? 'kênh'} về ${p.gain_db ?? 0} dB.`,
  'errors.modeChange': (p) => `Lỗi chuyển chế độ: ${p.msg ?? ''}`,
  'errors.panic': (p) => `Lỗi thực thi dừng khẩn: ${p.msg ?? ''}`,
  'errors.undoPanic': (p) => `Lỗi hoàn tác dừng khẩn: ${p.msg ?? ''}`,
  'errors.snapshot': (p) => `Lỗi chụp bản lưu PEQ: ${p.msg ?? ''}`,
  'errors.rollback': (p) => `Lỗi khôi phục PEQ: ${p.msg ?? ''}`
}

export function translateEventMessage(
  entryOrText: LogEntry | string,
  t?: (key: string, params?: Record<string, string | number>) => string
): string {
  if (typeof entryOrText === 'object' && entryOrText !== null) {
    if (entryOrText.text_code) {
      if (t) {
        const translated = t(entryOrText.text_code, entryOrText.params)
        if (translated && translated !== entryOrText.text_code) {
          return translated
        }
      }
      if (CODED_EVENT_FORMATTERS[entryOrText.text_code]) {
        return CODED_EVENT_FORMATTERS[entryOrText.text_code]!(entryOrText.params || {})
      }
    }
    return translateLegacyText(entryOrText.text || '')
  }
  return translateLegacyText(entryOrText)
}

function translateLegacyText(text: string): string {
  if (!text) return 'Hệ thống đang hoạt động ổn định'

  if (text.includes('Phát hiện kỹ sư chỉnh tay') || text.includes('manual override')) {
    const match = text.match(/kênh\s+(\d+)/i)
    const ch = match ? match[1] : ''
    return `Đang có người chỉnh tay Mic ${ch}. Tạm dừng can thiệp tự động 10 giây để nhường quyền.`.replace(/\s+/g, ' ')
  }

  if (text.includes('Đã kết nối tới Mixer') || text.includes('Connected to mixer')) {
    return 'Đã kết nối thành công với bàn mixer. Sẵn sàng hoạt động.'
  }

  if (text.includes('ngắt kết nối') || text.includes('Disconnected')) {
    return 'Đã ngắt kết nối với bàn mixer.'
  }

  if (text.includes('Cắt notch') || text.includes('Notch applied') || text.includes('Dập hú')) {
    return text.replace(/Cắt notch/g, 'Đã hạ điểm hú').replace(/băng tần/g, 'bộ lọc')
  }

  if (text.includes('PANIC') || text.includes('khẩn cấp') || text.includes('rollback')) {
    return 'ĐÃ DỪNG KHẨN: Trả lại toàn bộ cài đặt âm thanh như lúc trước.'
  }

  if (text.includes('CLIP') || text.includes('quá tải') || text.includes('Clip guardian')) {
    const match = text.match(/kênh\s+(\d+)/i)
    const ch = match ? match[1] : ''
    return `Mic ${ch} đang bị quá tải âm lượng! Hãy vặn nhỏ Gain trên mixer.`.replace(/\s+/g, ' ')
  }

  return text
}

export function getFriendlyStatus(
  mixerStatus: MixerConnectionStatus | string,
  hasRecentFeedback: boolean,
  activeNotchCount: number,
  lastFeedbackInfo?: { channel: number; freq_hz: number; target?: string; bus?: number | null } | null
): {
  color: 'green' | 'amber' | 'red'
  badgeText: string
  headline: string
  subline: string
} {
  if (mixerStatus === 'DISCONNECTED') {
    return {
      color: 'red',
      badgeText: 'MẤT KẾT NỐI',
      headline: 'Chưa kết nối tới bàn mixer',
      subline: 'Âm thanh trên sân khấu vẫn chạy bình thường. Hãy kiểm tra dây mạng hoặc Wi-Fi.'
    }
  }

  if (mixerStatus === 'CONNECTING') {
    return {
      color: 'amber',
      badgeText: 'ĐANG KẾT NỐI',
      headline: 'Đang kết nối tới bàn mixer…',
      subline: 'Đang thiết lập kết nối mạng với bàn mixer. Âm thanh trên sân khấu vẫn hoạt động bình thường.'
    }
  }

  if (mixerStatus === 'RECONNECTING') {
    return {
      color: 'red',
      badgeText: 'ĐANG KẾT NỐI LẠI',
      headline: 'Đang thử kết nối lại với mixer…',
      subline: 'Show vẫn an toàn và không bị ngắt tiếng.'
    }
  }

  if (hasRecentFeedback && lastFeedbackInfo) {
    const freq = formatFrequency(lastFeedbackInfo.freq_hz)
    const targetLabel = formatFriendlyTarget(lastFeedbackInfo)
    return {
      color: 'amber',
      badgeText: 'VỪA CHẶN HÚ',
      headline: `Vừa dập tiếng hú ở ${targetLabel} (${freq})`,
      subline: 'Đã tự động giảm nhẹ tần số hú an toàn. Âm thanh tiếp tục được bảo vệ.'
    }
  }

  if (activeNotchCount > 0) {
    return {
      color: 'green',
      badgeText: 'ĐANG BẢO VỆ',
      headline: `Đang chủ động bảo vệ (đã dập ${activeNotchCount} điểm hú)`,
      subline: 'Hệ thống đang liên tục lắng nghe và ngăn chặn tiếng rít hú.'
    }
  }

  return {
    color: 'green',
    badgeText: 'AN TOÀN',
    headline: 'Đang bảo vệ — Âm thanh trong trẻo',
    subline: 'Chưa có dấu hiệu hú rít nào. Hãy an tâm làm show.'
  }
}
