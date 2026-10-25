# Nghiên cứu Sâu: Toàn bộ Vấn đề Vận hành Show Đơn Giản & Lỗ hổng Kiến trúc Hiện tại

## 1. Start time
- `2026-10-24T20:08:00+07:00`

## 2. Initial purpose
- **Câu hỏi nghiên cứu:** Tại sao ứng dụng hiện tại nhìn như "chỉ có 1 chức năng" khi chạy show, và nếu một người dùng (kỹ thuật viên bán chuyên, chủ quán acoustic, nhân viên sự kiện/tiệc cưới/hội nghị) dùng `tool xklive` cho một show đơn giản từ đầu đến cuối thì sẽ gặp những sự cố thực tế hay lỗ hổng kỹ thuật nào trong mã nguồn?
- **Bối cảnh & Ràng buộc:** Đối chiếu trực tiếp trên nhánh mã nguồn Rust/Tauri v2 (`src-tauri/src/`) và Nuxt 4 (`frontend/app/`) tại thời điểm `2026-10-24`, tuân thủ bất biến cách ly Audio Plane / Control Plane và các giới hạn của Safety Controller (`GEMINI.md`).

## 3. Strategy
- Đọc kiểm toán toàn bộ đường đi dữ liệu từ giao thức UDP OSC (`src-tauri/src/mixer/`), luồng thu âm `cpal` (`src-tauri/src/audio/`), các thuật toán DSP (`src-tauri/src/dsp/`), bộ điều khiển an toàn & Ring-Out (`src-tauri/src/core/`), tầng IPC (`src-tauri/src/commands.rs`, `src-tauri/src/state.rs`, `src-tauri/src/lib.rs`) đến toàn bộ các bước của Easy Mode (`frontend/app/components/easy/`).
- Đặt toàn bộ phát hiện lên dòng thời gian vận hành thực tế của một buổi diễn đơn giản: **Giai đoạn 1 (Cắm dây & Kết nối) → Giai đoạn 2 (Thử mic & Gain Staging) → Giai đoạn 3 (Cân phòng Ring-Out) → Giai đoạn 4 (Chạy show trực tiếp & Xử lý sự cố)**.

## 4. Checklist
- [x] Kiểm tra cách `EasyModeView.vue` gọi `startAudioCapture` và cách `lib.rs` chuyển mạch giữa USB Audio và LAN RTA.
- [x] Kiểm tra tác động thực tế của nút chọn Preset (`monitor`, `foh`, `acoustic`, `speech`) ở Bước 2 (`EasyStepMicCheck.vue` & `useCompanionSocket.ts`).
- [x] Kiểm tra cơ chế chụp Snapshot (`take_snapshot`), lưu giá trị gốc (`original_gain_db`) và khởi tạo `RingOutController` (`start_wizard`).
- [x] Kiểm tra mức độ tích hợp của `TwoFactorLocalizer`, `GainStagingManager` và `TalkoverController` trong `AppState`, `lib.rs` và `commands.rs`.
- [x] Đánh giá UX Psychology (`METHOD-ux-psych.md`) trên màn hình Bước 4 (`EasyStepLiveShow.vue`).

## 5. Result

### 5.1. Bảng 9 Phát hiện Kỹ thuật & Vận hành (Xếp theo Mức độ Nghiêm trọng)

| Mã | Mức độ | Phân hệ | Phát hiện đã xác minh từ mã nguồn | Hậu quả thực tế khi chạy show đơn giản |
| :--- | :--- | :--- | :--- | :--- |
| **F1** | **CRITICAL (An toàn âm lượng)** | `commands.rs` (`start_wizard`) + `ringout.rs` | `start_wizard` gán cứng `initial_fader = 0.75` (`0.0 dB` Unity) thay vì đọc vị trí Fader hiện tại của Mixer. Khi chạy bước đầu tiên, `RingOutController` gửi lệnh đẩy Fader `/lr/mix/fader` hoặc `/bus/xx/mix/fader` lên `0.77` (`+0.5 dB`). | Nếu người dùng đang để Fader tổng ở mức nhỏ (ví dụ `-15 dB`) theo đúng hướng dẫn trên màn hình rồi bấm "Bắt đầu cân phòng", loa hội trường sẽ **vọt âm lượng đột ngột thêm +15.5 dB**, gây giật mình hoặc hú nổ loa ngay lập tức. |
| **F2** | **CRITICAL (Mất bảo vệ ngầm)** | `EasyModeView.vue` + `audio/mod.rs` + `lib.rs` | Khi kết nối mixer ở Bước 1, `EasyModeView.vue` gọi `startAudioCapture()` không truyền tên thiết bị. `AudioEngine` mở `default_input_device()` của hệ điều hành (thường là *MacBook Pro Microphone* 1 kênh). Khi đó `usb_running == true` trong `lib.rs` sẽ **tắt luôn bộ dò LAN RTA**, trong khi cổng USB chỉ thu đúng 1 kênh từ mic laptop. | Người dùng tưởng hệ thống đang bảo vệ 16 kênh của bàn mixer, nhưng thực tế kênh 2–16 hoàn toàn không được phân tích và chế độ LAN RTA dự phòng cũng bị ngắt. |
| **F3** | **HIGH (Tính năng giả / No-op)** | `useCompanionSocket.ts` (`setPreset`) | Ở Bước 2 (`EasyStepMicCheck.vue`), người dùng chọn loại sự kiện (*Loa kiểm âm*, *Loa chính*, *Nhạc Acoustic*, *Hội nghị*). Tuy nhiên hàm `setPreset()` chỉ đổi biến giao diện `currentPreset` và ghi 1 dòng log, **không gọi bất kỳ lệnh Tauri nào xuống Rust**. | Dù chọn "Hội nghị" (cần bắt hú nhạy, tự ngắt vang MC) hay "Acoustic" (cần giữ nguyên họa âm nhạc cụ, Q thật hẹp), thuật toán DSP bên dưới vẫn chạy cùng một thông số cố định. |
| **F4** | **HIGH (Mất EQ gốc của Soundman)** | `xair.rs` + `commands.rs` (`take_snapshot`, `decide`) | Khi mới kết nối, `XAirClient::query_channel_configs` chỉ hỏi `/config/name` và `/mix/on`, không truy vấn các band PEQ hiện có và không hỏi vị trí Fader. Hàm `decide()` luôn được gọi với `get_current_gain = None` (mặc định `original_gain_db = 0.0`). | (1) Bấm `take_snapshot` trước giờ diễn sẽ chụp được `0 điểm PEQ` nếu chưa vặn tay.<br>(2) Khi bấm `PANIC` hoặc `release_notch`, hệ thống trả band PEQ về `0.0 dB` thay vì trả về mức EQ mà kỹ thuật viên đã căn chỉnh trước đó. |
| **F5** | **HIGH (Bỏ quên mô-đun đã viết)** | `dsp/talkover.rs` + `dsp/gain_staging.rs` + `state.rs` | Hai mô-đun sống còn cho show đơn giản là `TalkoverController` (tự động hạ Reverb/FX khi nhạc dừng và MC nói) và `GainStagingManager` (đo 10s đề xuất Preamp Gain + cảnh báo vỡ tiếng `ClipAlert` sau 300ms) đã được viết xong, có unit test và khởi tạo trong `AppState`, nhưng **không được gọi ở bất kỳ đâu trong `lib.rs` hay `commands.rs`**. | Người chạy show vẫn bị 2 lỗi phổ biến nhất: (1) Ca sĩ/MC nói giao lưu bị tiếng vang Reverb oang oang không nghe rõ chữ; (2) Mic vặn sai Gain gây vỡ tiếng (clip) hoặc thiếu âm lượng mà không được cảnh báo/cân chỉnh. |
| **F6** | **HIGH (Định vị kênh hú & Crosstalk)** | `dsp/localizer.rs` + `lib.rs` + `commands.rs` | `TwoFactorLocalizer` đã viết hoàn chỉnh nhưng không được nối vào luồng tự động: (1) Ở chế độ LAN RTA (`lib.rs`), mọi đề xuất đều gán cứng `target = "main", channel = 0` dù đã có `/meters/1` của 16 kênh; (2) Ở chế độ USB (`commands.rs`), khi 1 tiếng hú lớn lọt vào 3 mic gần nhau (crosstalk), cả 3 kênh đều bị cắt PEQ cùng lúc. | Làm mỏng tiếng của nhiều micro không liên quan khi xảy ra crosstalk trên sân khấu nhỏ, và không chỉ điểm được mic nào gây hú khi dùng XR12/XR16/MR12. |
| **F7** | **MEDIUM (Lặp đề xuất RTA)** | `dsp/rta_detector.rs` | Sau khi phát hiện đỉnh hú qua 3 frame liên tiếp và tạo đề xuất, `RTADetector` xóa bin đó khỏi `history` (`self.history.remove(&bin_idx)`) mà không có thời gian nghỉ (refractory cooldown) theo tần số vừa báo. | Trong chế độ Bán tự động (`semi`), nếu người dùng chưa kịp bấm duyệt trong 150ms, cùng một tần số hú sẽ liên tục đẩy thông báo lặp lại. |
| **F8** | **MEDIUM (Mù thông tin ở Bước 4)** | `EasyStepLiveShow.vue` | Màn hình Bước 4 chỉ hiển thị quả cầu trạng thái + nút Panic + 3 dòng log. Không truyền `channels`, `meters`, `activeNotches`, `clipAlerts`, `talkover` vào component. | Khi đang diễn, người trực không biết mic số mấy đang mở, mic nào đang bị đỏ (Clip), mic nào là kênh nhạc nền cần khóa bảo vệ (Whitelist), và không thể nhả riêng 1 mic bị nghẹt tiếng mà buộc phải bấm `DỪNG KHẨN` xóa sạch toàn bàn. |
| **F9** | **MEDIUM (Thiếu kiểm tra Low-Cut / HPF)** | `xair.rs` + `EasyStepMicCheck.vue` | Chưa đọc/ghi tham số High-Pass Filter (`/ch/xx/preamp/hpf` và `/ch/xx/preamp/hpon`) cho các kênh micro giọng nói/hát. | Micro cầm tay ở sự kiện nhỏ không bật cắt trầm 80–100Hz gây tiếng "bụp" môi, tiếng chân dậm sân khấu và ù rền dải trầm. |

### 5.2. Verification (Bằng chứng xác minh)
- Toàn bộ 9 phát hiện trên được xác minh trực tiếp bằng đọc tĩnh mã nguồn (`Static Reading Verification` theo `coding.B3`):
  - **F1:** Xem `src-tauri/src/commands.rs` dòng `766-767` (`let initial_fader = 0.75; ringout.start(...)`).
  - **F2:** Xem `frontend/app/components/EasyModeView.vue` dòng `170` (`props.startAudioCapture()`) kết hợp `src-tauri/src/audio/mod.rs` dòng `68-70` và `src-tauri/src/lib.rs` dòng `97-98`.
  - **F3:** Xem `frontend/app/composables/useCompanionSocket.ts` dòng `679-689` (`setPreset` chỉ gán `currentPreset.value = preset`).
  - **F4:** Xem `src-tauri/src/mixer/xair.rs` dòng `204-221` và `src-tauri/src/state.rs` dòng `152` (`decide(&safety, &prop, now, None)`).
  - **F5:** Grep `gain_staging` và `talkover` trong `src-tauri/src/` chỉ xuất hiện tại khai báo `state.rs` dòng `61-62, 83-84`, hoàn toàn vắng mặt trong `lib.rs` và `commands.rs`.
  - **F6:** Xem `src-tauri/src/lib.rs` dòng `112` (`rta_det.process_rta_frame(&rta, "main")`) và `src-tauri/src/commands.rs` dòng `706-726`.
  - **F7:** Xem `src-tauri/src/dsp/rta_detector.rs` dòng `144` (`self.history.remove(&bin_idx)`).
  - **F8:** Xem `frontend/app/components/easy/EasyStepLiveShow.vue` dòng `6-17` (Props interface).
- *Lưu ý chưa kiểm chứng phần cứng:* Hành vi lượng tử hóa và chiều biến thiên thực tế của tham số OSC trên mixer vật lý vẫn cần chạy bước đo thực tế theo `docs/HARDWARE_VALIDATION.md`.

### 5.3. Corroborating links
- Kiến trúc tổng thể & quy tắc an toàn: [`GEMINI.md`](../../GEMINI.md), [`docs/plan/PLAN_AUTO_SOUND_ENGINE.md`](../plan/PLAN_AUTO_SOUND_ENGINE.md)
- Hiện trạng kỹ thuật: [`BAO_CAO_DU_AN.md`](../../BAO_CAO_DU_AN.md)
- Đặc tả IPC: [`docs/API.md`](../API.md)

## 6. Decision
- **Action:** Chuyển hóa toàn bộ 9 phát hiện trên thành kế hoạch triển khai 4 giai đoạn tại [`docs/plan/done/simple-show-upgrade.md`](../plan/done/simple-show-upgrade.md) (Ưu tiên vá ngay 4 lỗi Critical/High về an toàn Fader/Audio/Preset/Snapshot ở Phase 1, nối dây `Talkover` + `GainStaging` + `Localizer` ở Phase 2, nâng cấp giao diện Bước 4 & Bước 1–3 ở Phase 3, và khóa bằng bộ unit test ở Phase 4).
- **Cross-references:** Cập nhật danh mục tại [`docs/index.md`](../index.md); đồng bộ [`docs/API.md`](../API.md) và [`BAO_CAO_DU_AN.md`](../../BAO_CAO_DU_AN.md) khi thực thi.
