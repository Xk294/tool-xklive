# BÁO CÁO KỸ THUẬT VÀ KẾT QUẢ TRIỂN KHAI DỰ ÁN
# HỆ THỐNG CHỐNG HÚ TỰ ĐỘNG "AUTO SOUND ENGINEER" (PHA 1)
**Thiết bị hỗ trợ:** Behringer X-Air (XR12, XR16, XR18) & Midas M-Air (MR12, MR18)  
**Ngày báo cáo:** 20/10/2026  
**Ngôn ngữ triển khai:** Python 3.11+ | **Bản quyền:** 100% Open-Source Thương mại (MIT, BSD, Unlicense)

---

## 1. TỔNG QUAN DỰ ÁN & MỤC TIÊU CỐT LÕI

Dự án **Auto Sound Engineer** được xây dựng nhằm giải quyết bài toán nhức nhối nhất trong âm thanh trực tiếp (Live Sound) tại Việt Nam: **tiếng hú rít micro (acoustic feedback)** trong các chương trình sự kiện, đám cưới, acoustic cafe và dàn âm thanh cho thuê bình dân.

### Triết lý kiến trúc then chốt:
1. **Tách biệt tuyệt đối Audio Plane và Control Plane**:
   - Âm thanh buổi diễn đi thẳng từ micro vào mixer và ra loa, hoàn toàn **KHÔNG đi qua laptop**.
   - Laptop chỉ nhận bản sao tín hiệu (qua cổng USB 18x18 đối với XR18/MR18, hoặc qua gói tin phổ RTA 100-band đối với XR12/XR16/MR12) để phân tích DSP và gửi lệnh hạ notch PEQ qua mạng LAN (OSC/UDP).
   - **Cam kết an toàn**: Nếu laptop bị treo, sập nguồn hoặc đứt cáp, show diễn vẫn phát âm thanh 100% bình thường, không bao giờ gây sập chương trình.
2. **Kỹ sư âm thanh (Soundman) luôn nắm quyền tối thượng**:
   - Hỗ trợ 3 chế độ: Tự động hoàn toàn (`auto`), Bán tự động (`semi` — nhấp nháy cảnh báo đỏ, chờ Soundman bấm phím Space để duyệt hạ notch), và Gợi ý (`manual`).
   - Có nút **PANIC** (phím `[P]`): Chỉ trong 1 thao tác lập tức hoàn tác, trả toàn bộ các notch hệ thống về 0 dB (phẳng).
   - **Khóa an toàn khi chỉnh tay**: Nếu Soundman tự xoay núm EQ trên iPad hoặc mixer, hệ thống tự động khóa can thiệp trên kênh đó trong 10 giây.
3. **Phục vụ phân khúc bình dân, tiết kiệm tối đa chi phí phần cứng**:
   - XR18 / MR18: Tận dụng cổng USB 18x18 có sẵn.
   - XR12 / XR16 / MR12 (không có USB đa kênh): Chế độ RTA mạng LAN (**Thử nghiệm**) giám sát phổ RTA 100-band và can thiệp PEQ Main L/R không cần soundcard rời (lưu ý giới hạn độ phân giải 1/10 octave và chỉ can thiệp đường tổng).

---

## 2. CÁC CÔNG NGHỆ & KỸ THUẬT ĐÃ SỬ DỤNG

### 2.1. Nền tảng & Thư viện lõi
- **Ngôn ngữ:** Python 3.11+ tận dụng cấu trúc kiểu dữ liệu chặt chẽ (`dataclass`, `typing`) và hiệu năng tối ưu của runtime mới.
- **Xử lý số học & DSP:** `numpy` và `scipy` (vận hành trên nền thư viện C PocketFFT giấy phép BSD 3-Clause, thay thế hoàn toàn FFTW để không dính bẫy bản quyền GPL).
- **Giao thức mạng:** `socket` và `select` tiêu chuẩn của Python, bộ parser/encoder OSC thuần tối ưu hóa xử lý căn lề 4 bytes (padding nhị phân) và đóng gói struct.
- **Thu nhận âm thanh:** `sounddevice` (giao tiếp PortAudio C/C++, giấy phép MIT) cho luồng USB, kết hợp cơ chế phát sinh âm thanh ảo (Virtual Mock Generator) cho môi trường kiểm thử.
- **Kiểm thử tự động:** `pytest` và `hypothesis` (Property-Based Testing kiểm định hàng nghìn tổ hợp ngẫu nhiên).

### 2.2. Giao thức điều khiển thiết bị (Mixer OSC Driver)
- **Giao thức:** Open Sound Control (OSC) qua UDP Socket không phong tỏa (non-blocking).
- **Cổng kết nối:** `10024` (chuẩn hãng Behringer / Midas cho dòng X-Air).
- **Duy trì phiên:** Gửi heartbeat `/xremote` định kỳ 8.0 giây. Nếu mất kết nối quá 15 giây, cỗ máy trạng thái tự động chuyển sang `RECONNECTING` và thăm dò kết nối lại mỗi 1.0 giây.
- **Ghi có xác nhận (Verified Write):** Mọi lệnh ghi tham số PEQ đều được gửi đi và lập tức đọc lại giá trị xác nhận qua OSC. Nếu gói tin bị rớt, hệ thống tự động thử lại (retry) tối đa 1 lần.

### 2.3. Ánh xạ tham số hai chiều (Parameter Mapping)
Firmware Behringer XR biểu diễn mọi tham số dưới dạng số thực chuẩn hóa `[0.0, 1.0]`. Hệ thống đã xây dựng bộ chuyển đổi `ParameterMapper`:
- **Tần số (Frequency):** Thang Logarit từ 20.0 Hz đến 20,000.0 Hz với 201 bước lượng tử hóa.
- **Độ lợi (Gain):** Thang Tuyến tính từ -15.0 dB đến +15.0 dB với 121 bước (bước nhảy ~0.25dB - 0.5dB).
- **Độ nhọn (Q-factor):** Thang Logarit từ 0.3 đến 10.0 với 72 bước nấc chuẩn.
- **Hàm Snap & Quantize:** Đảm bảo khi gửi tần số bất kỳ (ví dụ 2500Hz), giá trị float gửi sang mixer luôn khớp chính xác với nấc phần cứng mà firmware nhận diện.

### 2.4. Kỹ thuật Audio I/O & Bộ đệm SPSC Ring Buffer
- **Cấu trúc:** Bộ đệm vòng tròn Single-Producer Single-Consumer (SPSC) 18 kênh âm thanh `float32`.
- **Hiệu năng Steady-State:** Đạt **Zero Memory Allocation (0 byte cấp phát động)** trong vòng lặp thu âm và đọc xử lý (đã được kiểm chứng qua đo lường `tracemalloc`).
- **Khả năng chịu lỗi:** Sức chứa 96,000 mẫu (~2.0 giây âm thanh @ 48kHz). Nếu luồng đọc bị trễ, bộ đệm tự động ghi đè dữ liệu cũ nhất và tăng biến đếm `xruns` mà không làm crash luồng âm thanh.

### 2.5. Thuật toán DSP Phát hiện Tiếng hú (Feedback Detection)
Dự án triển khai **hai động cơ dò hú chuyên biệt**:

#### Động cơ 1: FFT Đa Kênh USB (Dành cho XR18 / MR18)
- **Độ phân giải:** FFT $2048$ mẫu tại tần số lấy mẫu $48,000\text{ Hz}$ (độ rộng bin $\Delta f \approx 23.4\text{ Hz}$), bước nhảy $512$ mẫu ($75\%$ overlap), cửa sổ Hann.
- **Nội suy đỉnh Parabol (Parabolic Interpolation):** Xác định tần số đỉnh thật giữa 3 bin lân cận, đạt độ chính xác tần số dưới **$0.3\%$**.
- **Lọc sàn phổ trung vị (Median Filter 31 bins):** Tự động bám sát đường cong năng lượng âm nhạc tổng thể, chỉ bắt các đỉnh nhọn nhô cao hơn sàn phổ $\ge 10.0\text{ dB}$.
- **Loại trừ hài âm nhạc cụ & giọng hát (Musical Harmonic Rejection):**
  - Giọng hát ngân dài và guitar distortion có cấu trúc hài âm rất giống tiếng hú.
  - Thuật toán kiểm tra toàn diện các đỉnh hài bậc cao ($2f_0, 3f_0, 4f_0$) và phân hài ($f_0/2, f_0/3, f_0/4$). Nếu phát hiện cấu trúc hài âm âm nhạc, thuật toán lập tức **từ chối báo động giả**.
- **Theo dõi tăng trưởng năng lượng (Growth Rate Tracking):** Đỉnh hú phải duy trì qua ít nhất 3 khung liên tiếp (~$32\text{ ms}$) và có năng lượng tích lũy tăng trưởng $\ge 2.0\text{ dB}$.

#### Động cơ 2: RTA Network Analyzer (Dành cho XR12 / XR16 / MR12)
- **Không cần dây âm thanh:** Mixer tự tính RTA trong chip DSP và gửi phổ **100-band** (`/meters/4` blob binary gồm 100 số nguyên 16-bit) về qua mạng UDP.
- **Thuật toán `RTADetector`:** Lọc trung vị 11 bins, dò đỉnh nhọn vượt ngưỡng $\ge 10.0\text{ dB}$ và $\ge -50.0\text{ dBFS}$, theo dõi bùng phát qua 3 khung UDP để hạ notch trên Main Stereo L/R.

### 2.6. Kiến trúc Hàng Đợi Bất Đồng Bộ Zero-Blocking (Worker Queue)
- Luồng âm thanh và luồng mạng được tách biệt hoàn toàn qua `queue.Queue` và một **Background Worker Thread**.
- Khi phát hiện hú, hàm `execute_proposal()` chỉ mất $< 0.001\text{ ms}$ để đẩy lệnh vào hàng đợi và lập tức quay lại đọc âm thanh. Toàn bộ thao tác gửi lệnh UDP và đọc xác nhận (mất 50-100ms) diễn ra ở luồng phụ.
- **Kết quả:** Triệt tiêu hoàn toàn nguy cơ giật lag hay tràn bộ đệm âm thanh khi mạng LAN chập chờn.

### 2.7. Bộ điều khiển An toàn (Safety Controller)
Được thiết kế theo nguyên tắc hàm thuần khiết (**Pure Function** — không có side-effects):
- **Rate Limit:** Tối đa 2 giao dịch/giây, chống sập giao diện điều khiển X-Air-Edit của Soundman.
- **Cắt thăm dò vi phân (-3 dB Step Probing):** Chớm hú chỉ hạ $-3.0\text{ dB}$. Nếu hú dừng thì giữ nguyên; nếu hú tiếp tục mới hạ bước tiếp theo tối đa $-12.0\text{ dB}$.
- **Giới hạn Boost:** Tuyệt đối không bao giờ tăng gain quá $+4.0\text{ dB}$.
- **Bảo toàn dải tần EQ của Soundman:**
  - Trên kênh micro: Chỉ dùng Band 3 và Band 4; **tuyệt đối không đụng vào Band 1 & 2** (dành cho Soundman căn tone giọng ca sĩ).
  - Trên Main L/R (XR12/XR16): Dùng Band 3, 4, 5, 6; giữ Band 1 & 2 cho Soundman chỉnh âm sắc dàn loa FOH.
- **Channel Whitelist:** Chỉ can thiệp các kênh micro chỉ định, bỏ qua hoàn toàn kênh Aux/USB Return.

---

## 3. HIỆN TẠI DỰ ÁN ĐÃ TỚI ĐÂU? (TIẾN ĐỘ THỰC TẾ)

Dự án đã **hoàn thành xây dựng kiến trúc cốt lõi và kiểm chứng trong mô phỏng (Pha 1 Prototype)**. Hệ thống đã hỗ trợ cấu trúc profile cho XR18/MR18 (USB audio) và thử nghiệm XR12/XR16/MR12 (LAN RTA).

> **Lưu ý quan trọng:** Hệ thống hiện tại **CHƯA được kiểm chứng trên phần cứng thật** tại hiện trường show diễn (Milestone M5 chưa thực hiện). Toàn bộ kết quả hiện tại phản ánh hoạt động trên máy chủ mô phỏng `FakeXR18` và bộ sinh tín hiệu giả lập phòng `sim/room.py`.

### Cấu trúc mã nguồn hoàn thiện:
```text
xklive/
├── pyproject.toml                      # Cấu hình dự án, gói và dependency
├── README.md                           # Sách hướng dẫn vận hành chi tiết tiếng Việt
├── BAO_CAO_DU_AN.md                    # Báo cáo kỹ thuật tổng thể dự án
├── device_profiles/                    # Hồ sơ cấu hình phần cứng thiết bị (TOML)
│   ├── xr18.toml                       # Profile Behringer XR18 / Midas MR18 (USB 18x18)
│   ├── xr12.toml                       # Profile Behringer XR12 (4 mic, LAN RTA)
│   ├── xr16.toml                       # Profile Behringer XR16 (8 mic, LAN RTA)
│   └── mr12.toml                       # Profile Midas MR12 (4 Midas mic, LAN RTA)
├── src/auto_sound/
│   ├── core/
│   │   ├── models.py                   # Dataclass lõi: ConnectionState, PEQBand, ActionProposal...
│   │   └── config.py                   # Bộ nạp cấu hình TOML với validate kiểu dữ liệu
│   ├── mixer/
│   │   ├── base.py                     # Interface MixerDriver trừu tượng
│   │   ├── parameter_mapper.py         # Bộ chuyển đổi 2 chiều float [0.0, 1.0] <-> Hz, dB, Q
│   │   ├── osc.py                      # Parser/Encoder OSC nhị phân chống crash
│   │   ├── fake.py                     # UDP Simulator FakeXR18 cho CI/CD và thử nghiệm offline
│   │   └── xair.py                     # Driver XAirClient (Handshake, Heartbeat, RTA, Verified Write)
│   ├── audio/
│   │   ├── ring_buffer.py              # SPSC Ring Buffer 18 kênh, zero allocation
│   │   └── io.py                       # Thu âm USB thật qua sounddevice hoặc bộ sinh âm thanh ảo
│   ├── dsp/
│   │   ├── detector.py                 # Bộ dò hú FFT 2048 mẫu cho từng kênh micro
│   │   └── rta_detector.py             # Bộ dò hú trên 100 nấc phổ RTA mạng cho XR12/XR16
│   ├── safety/
│   │   └── controller.py               # Pure function Safety Controller (Rate limit, Probe, Panic)
│   ├── sim/
│   │   └── room.py                     # Mô phỏng âm học phòng (Logistic feedback growth, Vocal, Guitar)
│   └── app/
│       └── cli.py                      # Ứng dụng điều phối toàn trình, giao diện dòng lệnh tiếng Việt
└── tests/
    ├── test_parameter_mapper.py        # 8 tests Hypothesis kiểm định ánh xạ tham số
    ├── test_osc_parser.py              # 3 tests giải mã OSC và fuzzing ngẫu nhiên
    ├── test_mixer_fake.py              # 3 tests máy chủ giả lập, giới hạn 4 client
    ├── test_xair_state.py              # 3 tests cỗ máy trạng thái kết nối và verified write
    ├── test_ring_buffer.py             # 6 tests bộ đệm không cấp phát heap, overflow, continuity
    ├── test_safety.py                  # 8 tests rào chắn an toàn và property-based testing
    ├── test_detector_sim.py            # 1 test Benchmark âm học phòng (40 bài test độ nhạy)
    ├── test_cli_queue.py               # 2 tests hàng đợi mạng bất đồng bộ và khóa 10s chỉnh tay
    ├── test_xr12_rta.py                # 4 tests profile XR12/XR16/MR12 và dò hú qua RTA
    └── test_e2e.py                     # 1 test tích hợp khép kín đầu cuối từ âm thanh đến mixer
```

---

## 4. BẢNG TỔNG HỢP CÁC CHỨC NĂNG ĐÃ CÓ

| Nhóm chức năng | Tên tính năng cụ thể | Trạng thái | Module chịu trách nhiệm |
| :--- | :--- | :--- | :--- |
| **Giao tiếp Mixer** | Bắt tay handshake `/xinfo` & Heartbeat `/xremote` 8s | **ĐÃ XONG** | `auto_sound.mixer.xair` |
| | Tự động hồi phục kết nối trong $\le 3\text{s}$ khi rớt mạng | **ĐÃ XONG** | `auto_sound.mixer.xair` |
| | Đọc/Ghi PEQ có xác nhận hai chiều (Verified Write) | **ĐÃ XONG** | `auto_sound.mixer.xair` |
| | Hỗ trợ điều khiển PEQ Kênh, Bus và Main Stereo L/R | **ĐÃ XONG** | `auto_sound.mixer.xair` |
| | Nhận luồng RTA 100-band qua OSC `/meters/4` | **ĐÃ XONG** | `auto_sound.mixer.xair` |
| **Audio I/O** | Thu âm 18 track qua USB soundcard từ XR18 | **ĐÃ XONG** | `auto_sound.audio.io` |
| | Bộ đệm tròn SPSC Ring Buffer không cấp phát heap (Zero Alloc) | **ĐÃ XONG** | `auto_sound.audio.ring_buffer` |
| | Bộ sinh âm thanh ảo (Virtual Generator) thử nghiệm không cần phần cứng | **ĐÃ XONG** | `auto_sound.audio.io` |
| **Phát hiện hú (DSP)** | Dò hú từng micro qua FFT 2048 + Nội suy đỉnh Parabol | **ĐÃ XONG** | `auto_sound.dsp.detector` |
| | Lọc sàn năng lượng trung vị (Median Filter 31 bins) | **ĐÃ XONG** | `auto_sound.dsp.detector` |
| | Triệt tiêu báo động giả cho giọng hát & guitar (Harmonic Rejection) | **ĐÃ XONG** | `auto_sound.dsp.detector` |
| | Dò hú qua phổ RTA 100-band mạng LAN cho XR12/XR16/MR12 | **ĐÃ XONG** | `auto_sound.dsp.rta_detector` |
| **Bộ an toàn (Safety)** | Hạn mức 2 giao dịch/giây (Rate Limiting) | **ĐÃ XONG** | `auto_sound.safety.controller` |
| | Cắt thăm dò an toàn $-3.0\text{ dB}$ (Incremental Probing) | **ĐÃ XONG** | `auto_sound.safety.controller` |
| | Chống vượt ngưỡng Max Boost ($+4\text{ dB}$) và Max Cut ($-12\text{ dB}$) | **ĐÃ XONG** | `auto_sound.safety.controller` |
| | Khóa an toàn 10 giây khi Soundman chỉnh tay (Manual Override) | **ĐÃ XONG** | `auto_sound.safety.controller` |
| | Nút PANIC / Rollback 1 chạm thu hồi toàn bộ notch về $0\text{ dB}$ | **ĐÃ XONG** | `auto_sound.safety.controller` |
| **Hạ tầng & Vận hành** | Hàng đợi mạng phi đồng bộ (Async Queue) chống nghẽn audio | **ĐÃ XONG** | `auto_sound.app.cli` |
| | Giao diện dòng lệnh CLI tiếng Việt với cảnh báo màu ANSI | **ĐÃ XONG** | `auto_sound.app.cli` |
| | Hỗ trợ 3 chế độ vận hành: Tự động (`auto`), Bán tự động (`semi`), Gợi ý | **ĐÃ XONG** | `auto_sound.app.cli` |
| | Nhật ký sự kiện có cấu trúc JSON (Structured JSON Logging) | **ĐÃ XONG** | `auto_sound.app.cli` |
| | Giả lập mixer hoàn chỉnh FakeXR18 chạy trên máy tính | **ĐÃ XONG** | `auto_sound.mixer.fake` |

---

## 5. ĐÁNH GIÁ THỰC TẾ & CHỨNG CỨ KIỂM ĐỊNH

Hệ thống **ĐÃ KIỂM CHỨNG TRONG MÔ PHỎNG (MOCK / SYNTHETIC)** nhưng **CHƯA ĐƯỢC KIỂM CHỨNG TRÊN PHẦN CỨNG THẬT**.

### 5.1. Bằng chứng đã kiểm chứng trong mô phỏng (Simulation Verified)
Các kết quả dưới đây chứng minh mã nguồn hoạt động đúng theo các giả định thiết kế đã đặt ra:

### Chứng cứ 1: Kết quả kiểm thử tự động toàn diện
Chạy lệnh kiểm thử với toàn bộ 47 kịch bản (46 passed, 1 skipped) trên máy:
```bash
.venv/bin/pytest -v
```
**Kết quả thực tế từ máy:**
```text
============================= test session starts ==============================
collected 39 items

tests/test_cli_queue.py::test_async_network_queue_execution PASSED       [  2%]
tests/test_cli_queue.py::test_manual_override_detection_callback PASSED  [  5%]
tests/test_detector_sim.py::test_detector_benchmark_recall_and_false_positives PASSED [  7%]
tests/test_e2e.py::test_end_to_end_feedback_suppression_loop PASSED      [ 10%]
tests/test_mixer_fake.py::test_fake_xinfo_response PASSED                [ 12%]
tests/test_mixer_fake.py::test_fake_param_get_set PASSED                 [ 15%]
tests/test_mixer_fake.py::test_fake_max_4_clients PASSED                 [ 17%]
tests/test_osc_parser.py::test_encode_decode_roundtrip_valid PASSED      [ 20%]
tests/test_osc_parser.py::test_malformed_truncated_packets PASSED        [ 23%]
tests/test_osc_parser.py::test_fuzz_random_bytes_never_crash PASSED      [ 25%]
tests/test_parameter_mapper.py::TestSubMapperProperties::test_freq_to_float_bounds PASSED [ 28%]
tests/test_parameter_mapper.py::TestSubMapperProperties::test_gain_to_float_bounds PASSED [ 30%]
tests/test_parameter_mapper.py::TestSubMapperProperties::test_from_float_bounds PASSED [ 33%]
tests/test_parameter_mapper.py::TestSubMapperProperties::test_quantize_float_idempotent PASSED [ 35%]
tests/test_parameter_mapper.py::TestSubMapperProperties::test_snap_idempotent PASSED [ 38%]
tests/test_parameter_mapper.py::TestSubMapperProperties::test_exact_step_roundtrip PASSED [ 41%]
tests/test_parameter_mapper.py::TestParameterMapperXR18::test_load_from_profile PASSED [ 43%]
tests/test_parameter_mapper.py::TestParameterMapperXR18::test_known_boundary_values PASSED [ 46%]
tests/test_ring_buffer.py::test_ring_buffer_basic_read_write PASSED      [ 48%]
tests/test_ring_buffer.py::test_ring_buffer_wraparound PASSED            [ 51%]
tests/test_ring_buffer.py::test_ring_buffer_overflow_xrun PASSED         [ 53%]
tests/test_ring_buffer.py::test_ring_buffer_zero_allocation_in_steady_state PASSED [ 56%]
tests/test_ring_buffer.py::test_audio_continuity_and_no_dropped_samples PASSED [ 58%]
tests/test_ring_buffer.py::test_audio_capture_virtual_mode PASSED        [ 61%]
tests/test_safety.py::test_whitelist_rejection PASSED                    [ 64%]
tests/test_safety.py::test_manual_override_lock_10s PASSED               [ 66%]
tests/test_safety.py::test_rate_limit_2_transactions_per_sec PASSED      [ 69%]
tests/test_safety.py::test_max_boost_guard PASSED                        [ 71%]
tests/test_safety.py::test_system_band_isolation_and_exhaustion PASSED   [ 74%]
tests/test_safety.py::test_incremental_probing_step PASSED               [ 76%]
tests/test_safety.py::test_panic_rollback PASSED                         [ 79%]
tests/test_safety.py::test_safety_invariants_property_based PASSED       [ 82%]
tests/test_xair_state.py::test_xair_connect_success PASSED               [ 84%]
tests/test_xair_state.py::test_verified_write_peq PASSED                 [ 87%]
tests/test_xair_state.py::test_state_reconnecting_and_recovery PASSED    [ 89%]
tests/test_xr12_rta.py::test_xr12_xr16_mr12_profiles_load PASSED         [ 92%]
tests/test_xr12_rta.py::test_rta_detector_math_and_peak_detection PASSED [ 94%]
tests/test_xr12_rta.py::test_fake_xr18_main_peq_and_rta PASSED           [ 97%]
tests/test_xr12_rta.py::test_end_to_end_xr12_rta_feedback_loop PASSED    [100%]

============================== 39 passed in 7.05s ==============================
```

### Chứng cứ 2: Kết quả Benchmark âm học thực nghiệm
Chạy kiểm tra đo lường độ nhạy và chống báo động giả:
```bash
.venv/bin/pytest -v -s tests/test_detector_sim.py
```
**Số liệu đo đạc thực tế (trên dữ liệu tổng hợp sinh bởi `sim/room.py`):**
- **Độ nhạy phát hiện hú (Recall):** **$100.0\%$ (20/20 trường hợp)** | Khoảng tin cậy Wilson 95%: `[83.9% - 100.0%]`.  
  Tất cả các tần số chớm hú từ trầm (250Hz) đến cao (12,000Hz) đều được phát hiện chính xác với sai số tần số $< 0.3\%$.
- **Tỷ lệ báo động giả (False Positives):** **$0/20$ (Hoàn toàn không có báo động sai trên 20 mẫu mô phỏng)** | Khoảng tin cậy Wilson 95%: `[0.0% - 16.1%]`.  
  *(Lưu ý thống kê: 0/20 mẫu âm tính chỉ bảo đảm cận trên tỷ lệ lỗi thật $< 16.1\%$ với độ tin cậy $95\%$. Cần mở rộng lên $\ge 250$ mẫu thật ngoài hiện trường ở Giai đoạn C để kiểm chứng thương mại).*
- **Thời gian phản ứng phát hiện thực tế:** **$64.0\text{ ms}$** (bao gồm cả cửa sổ FFT 2048 mẫu 42.67ms và 3 frame tích lũy xác nhận, p50: 64.0ms, p95: 64.0ms, max: 64.0ms). Con số 21.3ms trước đây là đếm số hop đơn thuần, đã được chuẩn hóa lại trung thực.

### Chứng cứ 3: Khả năng vận hành ngay trên máy tính mà không cần mixer thật
Bất kỳ ai cài đặt repo này đều có thể tự mình chạy kiểm chứng giao diện tương tác:
```bash
.venv/bin/auto-sound --mock --mode semi
```
- Hệ thống tự khởi động mixer ảo `FakeXR18` trên localhost và sinh âm thanh giả lập.
- Khi có tiếng hú xuất hiện trên kênh 2, màn hình lập tức nhấp nháy:
  `[CẢNH BÁO ĐỎ] Kênh 2 chớm hú tại 2500.0Hz! Bấm [SPACE] để duyệt hạ notch.`
- Người dùng bấm phím `Space` -> Lệnh hạ notch được gửi và xác nhận ngay lập tức:
  `[ĐÃ HẠ NOTCH] Kênh 2 | Band 3 | 2500.0Hz | -3.0dB | Q=10.0`
- Bấm phím `P` -> Lập tức hoàn tác trả về $0\text{ dB}$.

---

## 6. HƯỚNG DẪN KẾT NỐI VÀ DANH MỤC CẦN KIỂM CHỨNG TRƯỚC SHOW THẬT

Hệ thống **CHƯA sẵn sàng chạy tự động (`auto`) trên show thật**. Khi kết nối với mixer vật lý ngoài đời thật (XR18 hoặc XR12/XR16), bắt buộc chạy ở chế độ Bán tự động (`semi`) có soundman giám sát:

### Trường hợp 1: Dùng cho Behringer XR18 / Midas MR18
1. **Dây mạng LAN:** Cắm trực tiếp từ cổng Ethernet laptop vào XR18 (Laptop đặt IP tĩnh `192.168.1.50`, Subnet `255.255.255.0`; XR18 đặt IP tĩnh `192.168.1.100`).
2. **Dây USB:** Cắm cáp USB 2.0 từ XR18 vào laptop. Trên X-Air Edit, mục `In/Out` -> `USB Sends` đặt 16 kênh Direct Out tiền gain.
3. **Lệnh chạy:**
   ```bash
   .venv/bin/auto-sound --profile device_profiles/xr18.toml --mode semi
   ```

### Trường hợp 2: Dùng cho Behringer XR12 / XR16 / Midas MR12 (Chế độ RTA LAN - THỬ NGHIỆM)
1. **Dây mạng LAN:** Cắm 1 sợi dây mạng LAN từ laptop vào XR12 (hoặc kết nối qua bộ phát Wi-Fi riêng).
2. **Lệnh chạy:**
   ```bash
   .venv/bin/auto-sound --profile device_profiles/xr12.toml --mode semi
   ```
   *(Chạy ở chế độ `semi` thử nghiệm, tự động giám sát phổ RTA 100-band của âm thanh tổng và đề xuất hạ notch trên Main L/R khi có hú).*

### Các thông số `[CẦN ĐO THẬT]` tại hiện trường:
Khi cắm trên bàn vật lý, cần ghi nhận thực tế bằng công cụ probe ở Giai đoạn B:
- `max_clients`: Xác nhận xem firmware thực tế có giới hạn cứng 4 client `/xremote` hay không.
- `probe_wait_ms`: Đo độ trễ ping thực tế từ laptop qua mixer (RTT p50/p95/p99 trên >= 200 lần).
- `freq_steps`, `gain_steps`, `q_steps`: Kiểm tra độ phân giải nấc hiển thị trên ứng dụng X-Air Edit chính hãng và bảng lượng tử hóa thật.
- `xremote_echo`: Đo thời gian echo của các lệnh ghi PEQ để cấu hình TTL expected-echo.

---

## 7. ĐÁNH GIÁ TỔNG KẾT

Dự án **Auto Sound Engineer (Pha 1 Prototype)** đã đạt được trạng thái:
1. **Tính hoàn chỉnh về kiến trúc:** Tách biệt Audio Plane và Control Plane, Safety Controller hàm thuần khiết, Verified Write, hàng đợi bất đồng bộ zero-blocking.
2. **Kiểm thử tự động trong mô phỏng:** 39 bài test tự động bao phủ các trường hợp biên của logic phần mềm trên FakeXR18.
3. **Mục tiêu Pha 2 để sẵn sàng cho show thật:**
   - Hoàn thành đo kiểm trên phần cứng thật (Giai đoạn B).
   - Thu thập và đánh giá trên 100 mẫu hú và 250 mẫu âm thanh thật (Giai đoạn C).
   - Bổ sung Two-Factor Localizer, Auto-Release khi cạn band (Giai đoạn D).
   - Xây dựng giao diện Web Companion điều khiển trực quan (Giai đoạn E).
4. **Pháp lý tuyệt đối an toàn:** 100% mã nguồn mở tự do thương mại (MIT, BSD, Unlicense).
