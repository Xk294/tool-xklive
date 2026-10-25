# BÁO CÁO KỸ THUẬT & HIỆN TRẠNG DỰ ÁN: AUTO SOUND ENGINEER (TOOL XKLIVE)

- **Kiến trúc hiện tại**: Tauri v2 (Rust Backend) + Nuxt 4 / Vue 3 (SPA Frontend)
- **Đối tượng phần cứng mục tiêu**: Behringer X-Air (XR12, XR16, XR18) & Midas M-Air (MR12, MR18)
- **Giao thức điều khiển**: Behringer X-Air OSC over UDP (Port 10024) & Multichannel USB Audio / LAN RTA 100-band
- **Cập nhật lần cuối**: 24/10/2026

> **CẢNH BÁO TRẠNG THÁI HIỆN TẠI**: Toàn bộ hệ thống đã hoàn tất chuyển đổi từ bản mẫu Python sang **Rust/Tauri v2**. Các thuật toán DSP và giao thức OSC được kiểm thử tự động trong mã nguồn (`cargo test`), nhưng **CHƯA ĐƯỢC KIỂM CHỨNG TRÊN BÀN MIXER VẬT LÝ THẬT**. Không tự ý đưa vào vận hành thương mại hoặc chạy sự kiện trực tiếp khi chưa hoàn tất đo kiểm phần cứng theo `docs/HARDWARE_VALIDATION.md`.

---

## 1. Tổng quan Kiến trúc Hệ thống

- **Ngôn ngữ & Nền tảng**: Backend viết bằng Rust (`src-tauri/src/`), đóng gói ứng dụng Desktop qua Tauri v2; giao diện người dùng viết bằng Nuxt 4 / Vue 3 (`frontend/`), giao tiếp hoàn toàn qua Tauri IPC (`invoke`).
- **Tách biệt Luồng Âm thanh và Luồng Điều khiển (Audio Plane vs Control Plane Isolation)**:
  - Tuyệt đối không đưa luồng âm thanh biểu diễn đi xuyên qua máy tính rồi mới ra loa.
  - Âm thanh chạy trực tiếp trên DSP phần cứng của Mixer (`Micro -> Mixer -> Loa`).
  - Máy tính chỉ nhận bản sao tín hiệu qua USB (XR18/MR18 tối đa 18 kênh) hoặc dữ liệu phổ RTA 100-band qua mạng LAN (XR12/XR16/MR12) để phân tích và gửi lệnh điều khiển PEQ qua giao thức OSC/UDP cổng 10024.
  - Nếu phần mềm tắt đột ngột hoặc đứt cáp mạng, âm thanh ra loa không bị ngắt quãng.

---

## 2. Trạng thái Triển khai Chi tiết từng Phân hệ (`src-tauri/src/`)

| Phân hệ | Tệp mã nguồn | Trạng thái | Chi tiết hiện trạng kỹ thuật |
| :--- | :--- | :--- | :--- |
| **Luồng thu âm & Ring Buffer** | `src-tauri/src/audio/mod.rs` | Đã có trong mã nguồn (có unit test) | Thu âm qua `cpal`, tự động nhận diện soundcard USB đa kênh của mixer (`find_preferred_mixer_device`, tránh mở nhầm mic tích hợp 1 kênh của laptop), tách kênh (de-interleave) tối đa 18 kênh vào SPSC Ring Buffer không cấp phát bộ nhớ động trong callback âm thanh. |
| **Phát hiện hú FFT (USB)** | `src-tauri/src/dsp/detector.rs` | Đã có trong mã nguồn (có unit test) | FFT 2048 mẫu (`rustfft`), cửa sổ Hann, nội suy đỉnh Parabolic, kiểm tra độ nhọn phổ (PSD Prominence), tốc độ tăng trưởng năng lượng, kiểm tra hài âm (Harmonic Veto), độ bền đỉnh và chặn cắt nhầm do lọt âm sang mic bên cạnh (Dominant Channel Crosstalk Veto). |
| **Phát hiện hú RTA 100-band (LAN)** | `src-tauri/src/dsp/rta_detector.rs` | Đã có trong mã nguồn (có unit test) | Phân tích mảng 100-band RTA (20Hz - 20kHz) từ gói tin `/meters/4` cho XR12/XR16/MR12 với cơ chế chống lặp đề xuất (`cooldown_s = 2.0s`), tích hợp vào vòng lặp nền khi chạy chế độ LAN RTA. |
| **Định vị kênh hú 2 yếu tố** | `src-tauri/src/dsp/localizer.rs` | Đã có trong mã nguồn (có unit test) | Kết hợp năng lượng tín hiệu theo kênh và trạng thái routing/mute (`TwoFactorLocalizer`) để gợi ý mic nghi ngờ gây hú khi chạy chế độ LAN RTA. |
| **Gợi ý Gain Staging & Clip** | `src-tauri/src/dsp/gain_staging.rs` | Đã có trong mã nguồn (có unit test) | Đo mức RMS/Peak thời gian thực từ luồng USB hoặc `/meters/1`, cảnh báo vỡ tiếng (`ClipAlert`) và hỗ trợ đo chuẩn Gain 10 giây (`start_gain_calibration`). |
| **Tự động giảm FX khi MC nói** | `src-tauri/src/dsp/talkover.rs` | Đã có trong mã nguồn (có unit test) | Tự động dìm fader FX Return (`/fxrtn/01..04/mix/fader`) khi MC phát biểu và khôi phục mượt khi MC dừng nói (`TalkoverController`), có khóa nhường quyền 10s khi kỹ thuật viên kéo fader FX bằng tay. |
| **Ánh xạ tham số OSC** | `src-tauri/src/mixer/mapper.rs` | Đã có trong mã nguồn (có unit test) | Chuyển đổi qua lại giữa đơn vị vật lý (Hz, dB, Q) và số thực chuẩn hóa `[0.0 .. 1.0]` (`ParameterMapper`). |
| **Giao tiếp OSC X-Air / M-Air** | `src-tauri/src/mixer/xair.rs` | Đã có trong mã nguồn (có unit test) | Gửi/nhận gói UDP OSC (`rosc`), duy trì `/xremote` định kỳ, đồng bộ cấu hình ban đầu (PEQ, Fader, Mute, tên kênh, High-Pass Filter `hpon`/`hpf`), giải mã blob `/meters/1` và `/meters/4`, hỗ trợ PEQ cho Kênh (`/ch/01..16`), Bus (`/bus/01..06`) và Main LR (`/lr`), kèm cửa sổ Expected-Echo 500ms. |
| **Bộ điều khiển an toàn (Safety)** | `src-tauri/src/core/safety.rs` | Đã có trong mã nguồn (có unit test) | Giới hạn tốc độ tối đa 2 lệnh/giây, cắt thăm dò từng bước `-3.0 dB` (chờ `probe_wait_ms = 80ms`), giới hạn cắt sâu tối đa `-12.0 dB`, bảo toàn `original_gain_db` từ cache phần cứng, khóa kênh 10 giây khi kỹ thuật viên chỉnh tay, tự động nhả notch (`check_auto_release`), tái sử dụng band khi đầy (`reclaim_on_exhaustion`) và `panic_rollback`. |
| **Dò hú trước giờ diễn (Ring-Out)** | `src-tauri/src/core/ringout.rs` | Đã có trong mã nguồn (có unit test) | Máy trạng thái đọc fader thực tế hiện tại từ mixer, tăng fader từng bước an toàn (tối đa `+3.0 dB` mặc định, trần cứng `+4.0 dB`) và khôi phục fader khi dừng (`RingOutWizard`). |
| **Quản lý trạng thái & Lệnh IPC** | `src-tauri/src/state.rs`, `src-tauri/src/commands.rs` | Đã có trong mã nguồn | Cung cấp các Tauri command bất đồng bộ (`async`) cho giao diện Nuxt (Easy Mode 4 bước & Pro Dashboard), hỗ trợ áp dụng Preset sự kiện (`apply_preset`), lọc ù 80Hz (`apply_channel_hpf`), Talkover MC (`set_talkover_config`), đo Gain 10s (`start_gain_calibration`), chụp/khôi phục Snapshot PEQ và điều phối đề xuất cắt hú. |

---

## 3. Các Hạng mục Chưa Hoàn thiện / Giới hạn Hiện tại

1. **Chưa hỗ trợ dòng bàn X32 / M32**:
   - Mã nguồn hiện tại (`CapabilityMap::channel_count_for_model` & `CapabilityMap::supports_usb_multitrack` trong `src-tauri/src/core/models.rs`) chỉ định nghĩa cấu hình cho dòng X-Air / M-Air (`XR18`, `MR18`, `XR16`, `XR12`, `MR12`). Chưa có profile thiết bị và ánh xạ OSC riêng cho X32/M32.
2. **Chưa có cơ chế Bản quyền / Dùng thử (License / Trial)**:
   - Chưa triển khai bất kỳ mô-đun kiểm tra khóa bản quyền (license key) hay giới hạn thời gian dùng thử (trial) nào trong cả `src-tauri` lẫn `frontend`.
3. **Chưa có Web Companion từ xa qua trình duyệt điện thoại/iPad**:
   - Phiên bản Tauri hiện tại sử dụng Tauri IPC nội bộ (`invoke` trong `frontend/app/composables/useCompanionSocket.ts`), không mở máy chủ HTTP/WebSocket nội bộ trên mạng LAN cho thiết bị di động bên ngoài truy cập.

---

## 4. Lịch sử dọn dẹp dữ liệu giả lập

- Tệp báo cáo kiểm thử độ bền trước đây đã được đổi tên thành `soak_report_mock.json` để phản ánh đúng bản chất là kết quả chạy với trình giả lập phần cứng (`FakeXR18`), tuyệt đối không dùng làm bằng chứng kiểm chứng phần cứng thật.
- Các công cụ thu thập và đo kiểm phần cứng bằng Python trước đây đã bị gỡ bỏ khi chuyển sang kiến trúc Rust/Tauri.

---

## 5. Kết quả Kiểm thử Tự động (Unit Tests)

Chạy lệnh kiểm thử chính thức của dự án tại thư mục gốc:

```bash
cargo test --manifest-path src-tauri/Cargo.toml
```

- **Số lượng bài kiểm thử hiện tại**: **32 unit tests** trong crate `src-tauri` (toàn bộ đều đạt `ok`, `0 failed`, `0 ignored`), bao gồm:
  - `audio`: 1 bài test (tự động chọn thiết bị USB đa kênh của mixer và loại trừ mic tích hợp 1 kênh của laptop).
  - `commands`: 1 bài test (`test_usb_crosstalk_veto_three_channels_2500hz` kiểm chứng lọc lọt âm 3 kênh đồng thời).
  - `core::safety`: 11 bài test (cắt bước đầu, cắt dò sâu, tôn trọng `probe_wait_ms`, giới hạn tốc độ 2 lệnh/giây, giới hạn boost tối đa `+4 dB`, khóa chỉnh tay 10s, hỗ trợ Main LR band 3-6, cách ly band hệ thống, tái sử dụng band khi đầy, tự động nhả notch theo tốc độ cấu hình và tôn trọng khóa tay, hoàn tác khẩn cấp Panic).
  - `core::ringout`: 5 bài test (tăng bước fader, phát hiện cộng hưởng và lùi fader, dừng khẩn cấp vs hoàn tất 0 notch, kiểm tra trần boost mặc định và số kênh theo từng dòng mixer).
  - `dsp::detector`: 2 bài test (bỏ qua nhiễu nền, phát hiện sóng sin hú kéo dài).
  - `dsp::rta_detector`: 3 bài test (chuyển đổi bin/tần số logarit, phát hiện đỉnh hú trên mảng 100-band RTA, chống lặp đề xuất trong cửa sổ cooldown 2.0s).
  - `dsp::localizer`: 2 bài test (xếp hạng kênh hú, bỏ qua kênh đang mute).
  - `dsp::gain_staging`: 2 bài test (tính toán mức gain đề xuất, cảnh báo clip kéo dài).
  - `dsp::talkover`: 1 bài test (kích hoạt hạ fader khi có tiếng nói và khôi phục khi hết câu).
  - `mixer::mapper`: 2 bài test (ánh xạ tuyến tính Gain dB, ánh xạ logarit tần số Hz).
  - `mixer::xair`: 2 bài test (giải mã gói tin nhị phân `/meters/1` và `/meters/4`).
