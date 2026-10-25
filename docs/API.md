# Tài liệu Giao diện Lập trình Ứng dụng Nội bộ (Tauri IPC Commands)

> **Lưu ý kiến trúc**: Ứng dụng chạy trên kiến trúc **Tauri v2 (Rust Backend) + Nuxt 4 (SPA Frontend)**. Giao diện giao tiếp trực tiếp với nhân xử lý âm thanh Rust thông qua cơ chế Tauri IPC (`invoke` từ `@tauri-apps/api/core`), không mở cổng HTTP/WebSocket ra mạng LAN.

---

## 1. Cấu trúc Trạng thái Đồng bộ (`FullStateSnapshot`)

Lệnh `get_state` trả về đối tượng JSON `FullStateSnapshot` chứa toàn bộ trạng thái thời gian thực để hiển thị trên giao diện:

```json
{
  "mixer_status": "CONNECTED | RECONNECTING | DISCONNECTED | MOCK",
  "mixer_model": "XR18",
  "current_mode": "auto | semi | manual",
  "current_preset": "monitor | foh | acoustic | speech",
  "audio_mode": "usb | lan_rta | none",
  "talkover_enabled": false,
  "talkover_is_ducked": false,
  "talkover_mic_channel": 1,
  "clip_alerts": [],
  "gain_sessions": {},
  "dry_run": false,
  "latency_ms": 44.8,
  "rtt_ms": 2.1,
  "dsp_latency_ms": 42.7,
  "active_notches": [
    {
      "channel": 1,
      "channel_name": "CH 01",
      "bus": null,
      "band": 3,
      "freq_hz": 2500.0,
      "gain_db": -3.0,
      "q": 8.0,
      "target": "ch",
      "age_s": 12.4,
      "is_locked": false,
      "step_count": 1
    }
  ],
  "pending_proposals": [
    {
      "id": "ch_2_1600",
      "channel": 2,
      "bus": null,
      "target": "ch",
      "freq_hz": 1600.0,
      "gain_db": -3.0,
      "q": 8.0,
      "confidence_score": 0.85,
      "created_at": 1729770000.0,
      "ttl_remaining_s": 10.0,
      "reason": "Feedback at 1600Hz"
    }
  ],
  "channels": [
    {
      "channel": 1,
      "name": "CH 01",
      "color": 1,
      "is_muted": false,
      "level": 0.12,
      "is_locked": false,
      "whitelisted": true,
      "hpf_enabled": false
    }
  ],
  "meters": [0.12, 0.0, 0.05],
  "rta_bins": [-65.0, -64.2],
  "event_logs": [
    {
      "id": 1,
      "time": "20:15:30",
      "text": "Connected to mixer at 192.168.1.100:10024",
      "type": "approved"
    }
  ]
}
```

---

## 2. Danh mục Lệnh Tauri IPC (`src-tauri/src/commands.rs`)

### 2.1. Kết nối Mixer & Thiết bị Âm thanh
- `get_state() -> FullStateSnapshot`: Lấy ảnh chụp trạng thái tổng thể của hệ thống.
- `discover_mixers_cmd(timeoutMs?: number, port?: number) -> DiscoveredMixer[]`: Quét broadcast UDP `/xinfo` trên các dải mạng LAN để tự động tìm bàn mixer X-Air / M-Air.
- `connect_mixer(ip: string, port: number) -> boolean`: Kết nối tới bàn mixer tại địa chỉ IP và cổng UDP (mặc định `10024`), khởi tạo luồng duy trì `/xremote` và đăng ký `/meters`.
- `disconnect_mixer() -> void`: Ngắt kết nối OSC với bàn mixer và dọn sạch phiên tạm thời.
- `list_audio_devices() -> AudioDeviceItem[]`: Liệt kê danh sách thiết bị thu âm đầu vào (`cpal`) trên máy tính.
- `start_audio_capture(deviceName?: string | null) -> boolean`: Bắt đầu luồng thu âm thời gian thực và phân tích phổ FFT đa kênh (tự động lọc rò âm Crosstalk Veto).
- `stop_audio_capture() -> void`: Dừng luồng thu âm hiện tại.
- `get_diagnostics() -> object`: Trả về thông số chẩn đoán kết nối OSC, RTT, thiết bị âm thanh và định tuyến.

### 2.2. Điều khiển Chống hú, Preset & Hỗ trợ Show Đơn giản (Safety, Notch Filters & Simple Show Assistant)
- `set_mode(mode: 'auto' | 'semi' | 'manual') -> void`: Chuyển đổi chế độ vận hành.
- `apply_preset(preset: 'monitor' | 'foh' | 'acoustic' | 'speech') -> object`: Áp dụng cấu hình DSP và Safety thật cho từng kịch bản sự kiện (`Q`, ngưỡng độ nhọn phổ, giới hạn cắt sâu `max_cut_db`, và bật/tắt `Talkover` tương ứng).
- `set_talkover_config(enabled: boolean, micChannel?: number | null, fxReturn?: number | null, duckingDepthDb?: number | null) -> object`: Bật/tắt chế độ tự động dìm fader FX Return (Reverb/Delay) khi MC phát biểu (`TalkoverController`), kèm tôn trọng khóa chỉnh tay 10s trên `/fxrtn/xx/mix/fader`.
- `start_gain_calibration(channel: number) -> { success: boolean, channel: number, session: GainCalibrationSession }`: Khởi chạy phiên đo mức tín hiệu chuẩn 10 giây cho một kênh micro để đưa ra gợi ý chỉnh Gain đầu vào.
- `cancel_gain_calibration(channel: number) -> { success: boolean, channel: number }`: Hủy phiên đo Gain đang chạy trên kênh chỉ định.
- `apply_channel_hpf(channel: number, enabled: boolean, freqHz?: number | null) -> boolean`: Bật/tắt bộ lọc cắt trầm High-Pass Filter (`/ch/xx/preamp/hpon` và `/ch/xx/preamp/hpf`, mặc định `80 Hz`) để khử tiếng ù nền và tiếng bụp môi cho micro.
- `toggle_dry_run(enabled?: boolean) -> boolean`: Bật/tắt chế độ chạy thử (chỉ mô phỏng trên giao diện, không gửi gói OSC thay đổi PEQ xuống mixer).
- `toggle_lock(channel: number) -> boolean`: Khóa hoặc mở khóa bảo vệ kênh không cho thuật toán tự động cắt PEQ.
- `toggle_whitelist(channel: number) -> boolean`: Thêm hoặc gỡ kênh khỏi danh sách cho phép can thiệp tự động.
- `approve_proposal(channel: number, freqHz: number, id?: string) -> boolean`: Duyệt đề xuất cắt hú trong chế độ Bán tự động (`semi`).
- `reject_proposal(channel: number, freqHz: number, id?: string) -> void`: Từ chối và xóa đề xuất cắt hú khỏi hàng đợi.
- `snooze_proposal(channel: number, freqHz: number, id?: string) -> void`: Bỏ qua đề xuất và tạm khóa kênh đó trong 60 giây.
- `apply_manual_notch(target: string, channel: number, bus: number | null, freqHz: number, gainDb: number, q: number) -> boolean`: Cắt nhanh một điểm PEQ thủ công từ bảng điều khiển hoặc biểu đồ RTA.
- `release_notch(channel: number, band: number, target: string, bus?: number | null) -> void`: Nhả một bộ lọc notch đang hoạt động về giá trị Gain, tần số và Q gốc của kỹ thuật viên.
- `panic_reset() -> void`: Kích hoạt khẩn cấp **PANIC** — hoàn tác toàn bộ các dải PEQ đã cắt về trạng thái gốc (có điều tiết tốc độ OSC) và chuyển hệ thống sang chế độ `manual`.
- `undo_panic_reset() -> number`: Khôi phục lại danh sách các điểm cắt vừa bị xóa bởi thao tác `panic_reset`.

### 2.3. Snapshot, Ring-Out Wizard & Báo cáo
- `take_snapshot() -> { success: boolean, bands_count: number }`: Lưu bản chụp cấu hình các dải PEQ hiện tại trước giờ diễn.
- `rollback_snapshot() -> { success: boolean, restored_count: number, message: string }`: Khôi phục toàn bộ các dải PEQ về bản chụp Snapshot đã lưu qua `set_peq()`.
- `start_wizard(channel?: number, maxBoostDb?: number, dwellTimeS?: number) -> { success: boolean }`: Khởi chạy quy trình dò điểm hú trước giờ diễn (`RingOutController`).
- `stop_wizard() -> RingOutReport`: Dừng quy trình dò hú và lập tức trả fader về mức ban đầu (hoặc đặt lịch hoàn trả ngay khi kết nối lại).
- `get_wizard_status() -> WizardStatusSnapshot`: Lấy trạng thái tiến trình Ring-Out Wizard kèm danh sách tần số cộng hưởng đã xử lý (`detected_frequencies`).
- `get_dynamics_suggestions() -> { suggestions: DynamicsSuggestionItem[] }`: Lấy gợi ý Gain Staging, Compressor và Noise Gate dựa trên mức tín hiệu các kênh.
- `trigger_demo_feedback(channel: number, freqHz: number, gainDb?: number) -> void`: Bơm tín hiệu hú mô phỏng để kiểm tra quy trình phát hiện và cắt notch.
- `export_report(format?: 'json' | 'csv') -> string`: Xuất báo cáo danh sách các điểm cắt notch ra định dạng JSON hoặc CSV.
- `clear_logs() -> void`: Xóa nhật ký sự kiện hệ thống.
