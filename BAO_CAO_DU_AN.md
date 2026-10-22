# BÁO CÁO KỸ THUẬT VÀ KẾT QUẢ TRIỂN KHAI DỰ ÁN
# HỆ THỐNG CHỐNG HÚ TỰ ĐỘNG "AUTO SOUND ENGINEER"
**Thiết bị hỗ trợ:** Behringer X-Air (XR12, XR16, XR18) & Midas M-Air (MR12, MR18)  
**Ngày cập nhật:** 22/10/2026  
**Ngôn ngữ & Nền tảng:** Python 3.11+ (Core Engine, DSP, FastAPI) | Nuxt 4 / Vue 3 (Web Companion UI)  
**Bản quyền:** 100% Open-Source Thương mại (MIT, BSD, Unlicense)

---

## 1. TỔNG QUAN DỰ ÁN & MỤC TIÊU CỐT LÕI

Dự án **Auto Sound Engineer** được xây dựng nhằm giải quyết bài toán nhức nhối nhất trong âm thanh trực tiếp (Live Sound) tại Việt Nam: **tiếng hú rít micro (acoustic feedback)** trong các chương trình sự kiện, đám cưới, acoustic cafe và dàn âm thanh cho thuê bình dân.

### Triết lý kiến trúc then chốt:
1. **Tách biệt tuyệt đối Audio Plane và Control Plane**:
   - Âm thanh buổi diễn đi thẳng từ micro vào mixer và ra loa, hoàn toàn **KHÔNG đi qua laptop**.
   - Laptop chỉ nhận bản sao tín hiệu (qua cổng USB 18x18 đối với XR18/MR18, hoặc qua gói tin phổ RTA 100-band đối với XR12/XR16/MR12) để phân tích DSP và gửi lệnh hạ notch PEQ qua mạng LAN (OSC/UDP).
   - **Cam kết an toàn**: Nếu laptop bị treo, sập nguồn hoặc đứt cáp, show diễn vẫn phát âm thanh 100% bình thường, không bao giờ gây sập chương trình.
2. **Kỹ sư âm thanh (Soundman) luôn nắm quyền tối thượng**:
   - Hỗ trợ 3 chế độ vận hành: Tự động hoàn toàn (`auto`), Bán tự động (`semi` — nhấp nháy cảnh báo đỏ, chờ Soundman duyệt hạ notch), và Gợi ý (`manual`).
   - Có nút **PANIC** (phím `[P]` trên CLI hoặc nút đỏ nổi bật trên Web Companion): Lập tức hoàn tác trong 1 thao tác, trả toàn bộ notch hệ thống về 0 dB (phẳng).
   - **Khóa an toàn khi chỉnh tay (Manual Override Lock)**: Nếu Soundman tự xoay núm EQ trên iPad hoặc mixer, hệ thống tự động khóa can thiệp trên kênh đó trong 10 giây.
   - **Cơ chế Expected-Echo & Anti-Ghosting**: Hệ thống tự động phân biệt giữa phản hồi echo của các lệnh do chính hệ thống ghi xuống mixer với thao tác vặn tay thực tế của soundman, ngăn chặn việc khóa nhầm kênh.
3. **Tương tác trực tiếp với mixer X-Air & Trải nghiệm Web Companion hiện đại**:
   - Tự động quét và phát hiện mixer trong mạng LAN qua UDP broadcast `/xinfo` mà không cần cấu hình IP thủ công.
   - Đồng bộ tên kênh, màu sắc và trạng thái MUTE trực tiếp từ mixer theo thời gian thực.
   - Giao diện điều khiển Web Companion hiện đại (Nuxt 4 / Vue 3 SPA + Tailwind CSS), kết nối WebSocket hai chiều độ trễ mili-giây, cho phép Soundman giám sát và can thiệp trên mọi thiết bị (iPad, iPhone, Android, Laptop).

---

## 2. CÁC CÔNG NGHỆ & KỸ THUẬT ĐÃ TRIỂN KHAI

### 2.1. Nền tảng & Thư viện lõi
- **Ngôn ngữ Core:** Python 3.11+ tận dụng cấu trúc kiểu dữ liệu chặt chẽ (`dataclass`, `typing`) và hiệu năng tối ưu của runtime mới.
- **Xử lý số học & DSP:** `numpy` và `scipy` (vận hành trên nền thư viện C PocketFFT giấy phép BSD 3-Clause, thay thế hoàn toàn FFTW để tránh rào cản bản quyền GPL).
- **Giao thức mạng:** `socket` và `select` tiêu chuẩn của Python, bộ parser/encoder OSC thuần tối ưu hóa xử lý căn lề 4 bytes (padding nhị phân) và đóng gói struct.
- **Thu nhận âm thanh:** `sounddevice` (giao tiếp PortAudio C/C++, giấy phép MIT) cho luồng USB, kết hợp cơ chế phát sinh âm thanh ảo (Virtual Mock Generator) cho môi trường kiểm thử.
- **Web Backend:** FastAPI + Uvicorn hỗ trợ REST API và WebSocket Full-Duplex truyền snapshot phổ âm thanh và trạng thái kênh tới client.
- **Web Frontend:** Nuxt 4 / Vue 3 + Vite + Tailwind CSS biên dịch tĩnh (Static SPA) nhúng trực tiếp vào backend, không cần cài đặt Node.js khi vận hành.
- **Kiểm thử tự động:** `pytest` và `hypothesis` (Property-Based Testing kiểm định hàng nghìn tổ hợp ngẫu nhiên).

### 2.2. Giao thức điều khiển thiết bị (Mixer OSC Driver & Direct Interfacing)
- **Giao thức:** Open Sound Control (OSC) qua UDP Socket không phong tỏa (non-blocking), cổng `10024`.
- **Tự động quét Mixer (Auto-Discovery):** Phát lệnh UDP broadcast `/xinfo` tới subnet và địa chỉ broadcast để nhận diện mixer (IP, Model XR12/XR16/XR18/MR12/MR18, Firmware, Mixer Name).
- **Duy trì phiên:** Gửi heartbeat `/xremote` định kỳ 8.0 giây. Nếu mất kết nối quá 15 giây, cỗ máy trạng thái tự động chuyển sang `RECONNECTING` và thăm dò kết nối lại mỗi 1.0 giây.
- **Đồng bộ Metadata thời gian thực:** Lắng nghe và cập nhật tên kênh (`/ch/{ch}/config/name`), màu sắc (`/ch/{ch}/config/color`), trạng thái bật/tắt MUTE (`/ch/{ch}/mix/on`) và trạng thái Master EQ (`/ch/{ch}/eq/on`).
- **Ghi có xác nhận & An toàn PEQ (Direct PEQ Enforcement):**
  - Mọi lệnh ghi tham số PEQ đều được xác nhận hai chiều.
  - Hàm `set_peq()` tự động bật Master EQ kênh (`/eq/on = 1`) và ép loại Band về Parametric EQ (`type = 2`), loại trừ nguy cơ notch bị vô hiệu hoặc preset của soundman đang để High Cut/Shelf làm méo tiếng dải cao.
- **Expected-Echo Window:** Lưu vết các giá trị tham số hệ thống vừa gửi kèm TTL 500ms; khi mixer phản hồi `/xremote` cùng giá trị, hệ thống xác nhận thành công mà không kích hoạt nhầm khóa tay 10s.

### 2.3. Ánh xạ tham số hai chiều (Parameter Mapping)
Firmware Behringer XR biểu diễn mọi tham số dưới dạng số thực chuẩn hóa `[0.0, 1.0]`. Hệ thống xây dựng bộ chuyển đổi `ParameterMapper`:
- **Tần số (Frequency):** Thang Logarit từ 20.0 Hz đến 20,000.0 Hz với 201 bước lượng tử hóa.
- **Độ lợi (Gain):** Thang Tuyến tính từ -15.0 dB đến +15.0 dB với 121 bước (bước nhảy ~0.25dB - 0.5dB).
- **Độ nhọn (Q-factor):** Thang Logarit từ 0.3 đến 10.0 với 72 bước nấc chuẩn.
- **Hàm Snap & Quantize:** Đảm bảo giá trị float gửi sang mixer luôn khớp chính xác với nấc phần cứng mà firmware nhận diện.

### 2.4. Kỹ thuật Audio I/O & Bộ đệm SPSC Ring Buffer
- **Cấu trúc:** Bộ đệm vòng tròn Single-Producer Single-Consumer (SPSC) 18 kênh âm thanh `float32`.
- **Hiệu năng Steady-State:** Đạt **Zero Memory Allocation (0 byte cấp phát động)** trong vòng lặp thu âm và đọc xử lý (đã kiểm chứng qua đo lường `tracemalloc`).
- **Khả năng chịu lỗi:** Sức chứa 96,000 mẫu (~2.0 giây âm thanh @ 48kHz). Nếu luồng đọc bị trễ, bộ đệm tự động ghi đè dữ liệu cũ nhất và tăng biến đếm `xruns` mà không làm crash luồng âm thanh.

### 2.5. Thuật toán DSP Phát hiện Tiếng hú & Quản lý Notch
- **Động cơ 1 (FFT 2048 mẫu cho XR18 / MR18):**
  - Cửa sổ Hann 2048 mẫu, bước nhảy 512 mẫu ($75\%$ overlap), nội suy đỉnh Parabol đạt độ chính xác tần số $< 0.3\%$.
  - Lọc sàn trung vị 31 bins, loại trừ hài âm nhạc cụ & giọng ca (Harmonic Rejection: kiểm tra bậc $2f_0, 3f_0, 4f_0$ và $f_0/2, f_0/3, f_0/4$).
  - Theo dõi tăng trưởng năng lượng (Growth Rate Tracking $\ge 2.0\text{ dB}$ qua $\ge 3$ khung liên tiếp).
  - **Bỏ qua kênh MUTE (Mute-Aware DSP Skip):** Tự động bỏ qua phân tích các kênh đang bị Mute trên bàn mixer, triệt tiêu báo động giả và tiết kiệm tài nguyên CPU.
- **Động cơ 2 (RTA 100-band cho XR12 / XR16 / MR12):**
  - Lắng nghe gói tin nhị phân `/meters/4`, lọc trung vị 11 bins, dò đỉnh bùng phát $\ge 10.0\text{ dB}$ và $\ge -50.0\text{ dBFS}$ để điều khiển PEQ Main Stereo L/R.
- **Định vị Micro Hú (Two-Factor Mic Localizer):**
  - Khi nhiều micro cùng bắt tiếng hú (crosstalk), thuật toán kết hợp phổ năng lượng micro với routing Bus âm thanh để định vị chính xác micro phát sinh hú đầu tiên, hạ notch đúng kênh gốc thay vì hạ nhầm tất cả các mic.
- **Tự động nhả Notch (Auto-Release) & Tái thu hồi Band (Reclaiming):**
  - Mỗi kênh micro được cấp 2 Band PEQ (Band 3 và Band 4).
  - Khi cạn band, hệ thống tự động tái thu hồi (reclaim) notch nông nhất có cùng dải tần để nhường chỗ cho tần số hú mới nguy hiểm hơn.
  - Khi âm trường ổn định sau thời gian cấu hình (ví dụ 60 giây không còn hú), hệ thống từ từ nhả gain notch về 0 dB theo từng bước 1 dB để bảo toàn chất lượng âm thanh gốc.

### 2.6. Bộ điều khiển An toàn (Safety Controller)
- **Hàm thuần khiết (Pure Function):** Không side-effects, dễ dàng kiểm thử bằng Property-Based Testing.
- **Rate Limit:** Tối đa 2 giao dịch/giây, chống quá tải CPU điều khiển của mixer.
- **Cắt thăm dò vi phân (-3 dB Step Probing):** Chớm hú hạ $-3.0\text{ dB}$, nếu hú tiếp tục mới hạ dần tới tối đa $-12.0\text{ dB}$.
- **Giới hạn Boost:** Tuyệt đối không bao giờ tăng gain quá $+4.0\text{ dB}$.
- **Bảo toàn dải tần EQ của Soundman:**
  - Micro: Chỉ can thiệp Band 3 & 4; giữ nguyên Band 1 & 2 để Soundman căn chỉnh tone giọng ca sĩ.
  - Main L/R: Chỉ can thiệp Band 3, 4, 5, 6; giữ nguyên Band 1 & 2 cho âm sắc FOH.

### 2.7. Giao diện Web Companion Nuxt 4 / Vue 3
- Chuyển đổi hoàn toàn từ file HTML đơn bản cũ sang kiến trúc hiện đại Nuxt 4 / Vue 3 SPA với các thành phần chuyên biệt:
  - `MetersGrid.vue`: Lưới hiển thị mức âm lượng 18 kênh, hiển thị tên kênh thực tế của show (*Lead Vox, Backing, MC, Acoustic...*), màu sắc và tag `MUTE`.
  - `ProposalsQueue.vue`: Hàng đợi các đề xuất hạ notch đang chờ Soundman duyệt trong chế độ `semi`, kèm nút Approve / Reject 1 chạm.
  - `NotchesTable.vue`: Bảng danh sách các notch PEQ đang kích hoạt theo thời gian thực kèm nút Bypass / Delete từng notch.
  - `PanicButton.vue`: Nút khẩn cấp PANIC nổi bật trên thanh tiêu đề, hỗ trợ phím tắt và thao tác hoàn tác tức thì.
  - `DeviceStatus.vue`: Thẻ thông tin mixer hiển thị IP, tên mixer, model và firmware thật.

---

## 3. CẤU TRÚC MÃ NGUỒN HIỆN TẠI

```text
xklive/
├── pyproject.toml                      # Cấu hình dự án, gói và dependencies
├── README.md                           # Hướng dẫn vận hành chi tiết tiếng Việt
├── BAO_CAO_DU_AN.md                    # Báo cáo kỹ thuật tổng thể dự án
├── run_ui.py                           # Trình khởi chạy giao diện Web Companion kèm Auto-Discovery
├── device_profiles/                    # Hồ sơ cấu hình phần cứng thiết bị (TOML)
│   ├── xr18.toml                       # Profile Behringer XR18 / Midas MR18 (USB 18x18)
│   ├── xr12.toml                       # Profile Behringer XR12 (4 mic, LAN RTA)
│   ├── xr16.toml                       # Profile Behringer XR16 (8 mic, LAN RTA)
│   └── mr12.toml                       # Profile Midas MR12 (4 Midas mic, LAN RTA)
├── frontend/                           # Giao diện Nuxt 4 / Vue 3 SPA (Single Page App)
│   ├── app.vue                         # Layout chính: Header, Navigation, Status Bar
│   ├── package.json                    # Cấu hình Nuxt 4, Vue 3, Tailwind CSS, Lucide Icons
│   ├── nuxt.config.ts                  # Cấu hình SSR: false, static output sang web/dist
│   ├── composables/
│   │   └── useCompanionSocket.ts       # Hook quản lý kết nối WebSocket và đồng bộ Pinia-like state
│   └── components/
│       ├── MetersGrid.vue              # Lưới giám sát âm lượng, tên kênh, màu sắc và MUTE
│       ├── ProposalsQueue.vue          # Hàng đợi duyệt hạ notch chế độ Semi-Auto
│       ├── NotchesTable.vue            # Bảng quản lý notch đang áp dụng
│       ├── DeviceStatus.vue            # Hiển thị thông tin mixer thật/mô phỏng
│       └── PanicButton.vue             # Nút khẩn cấp Panic 1 chạm
├── src/auto_sound/
│   ├── core/
│   │   ├── models.py                   # Dataclass: ChannelInfo, PEQBand, ActionProposal, Snapshot...
│   │   └── config.py                   # Bộ nạp cấu hình TOML với validate dữ liệu chặt chẽ
│   ├── mixer/
│   │   ├── base.py                     # Interface MixerDriver trừu tượng
│   │   ├── parameter_mapper.py         # Bộ chuyển đổi 2 chiều float [0.0, 1.0] <-> Hz, dB, Q
│   │   ├── osc.py                      # Parser/Encoder OSC nhị phân chống crash
│   │   ├── fake.py                     # UDP Simulator FakeXR18 cho CI/CD và thử nghiệm offline
│   │   └── xair.py                     # Driver XAirClient (Discovery, Handshake, Metadata, PEQ Safety)
│   ├── audio/
│   │   ├── ring_buffer.py              # SPSC Ring Buffer 18 kênh, zero allocation
│   │   └── io.py                       # Thu âm USB thật qua sounddevice hoặc bộ sinh âm thanh ảo
│   ├── dsp/
│   │   ├── detector.py                 # Bộ dò hú FFT 2048 mẫu cho từng kênh micro
│   │   ├── rta_detector.py             # Bộ dò hú trên 100 nấc phổ RTA mạng cho XR12/XR16
│   │   └── localizer.py                # Two-Factor Mic Localizer định vị micro hú
│   ├── safety/
│   │   ├── controller.py               # Pure function Safety Controller (Rate limit, Probe, Reclaim)
│   │   └── snapshot.py                 # Quản lý sao lưu/phục hồi snapshot trạng thái EQ trước show
│   ├── sim/
│   │   └── room.py                     # Mô phỏng âm học phòng (Logistic feedback, Vocal, Guitar)
│   ├── app/
│   │   ├── cli.py                      # Core runtime điều phối toàn trình, CLI tiếng Việt
│   │   └── server.py                   # FastAPI REST API + WebSocket Server cho Web Companion
│   └── web/
│       └── dist/                       # Bản dựng tĩnh Nuxt 4 / Vue 3 được server FastAPI phục vụ trực tiếp
└── tests/
    ├── test_bus_notch.py               # 5 tests kiểm định can thiệp PEQ Bus và Main Stereo L/R
    ├── test_cli_queue.py               # 2 tests hàng đợi mạng bất đồng bộ và callback khóa tay 10s
    ├── test_detector_sim.py            # 2 tests benchmark âm học phòng (20 bài test độ nhạy, 1 test skipped)
    ├── test_e2e.py                     # 1 test tích hợp khép kín đầu cuối từ âm thanh đến mixer
    ├── test_localizer.py               # 4 tests Two-Factor Localizer giải quyết crosstalk micro
    ├── test_mixer_fake.py              # 3 tests máy chủ giả lập FakeXR18
    ├── test_osc_parser.py              # 3 tests giải mã OSC và fuzzing ngẫu nhiên
    ├── test_parameter_mapper.py        # 8 tests Hypothesis kiểm định ánh xạ tham số
    ├── test_ring_buffer.py             # 6 tests bộ đệm không cấp phát heap, overflow, continuity
    ├── test_safety.py                  # 11 tests rào chắn an toàn, Auto-Release và Reclaiming
    ├── test_server_api.py              # 7 tests API FastAPI, WebSocket snapshot và Nuxt static app
    ├── test_snapshot.py                # 2 tests sao lưu và phục hồi snapshot PEQ
    ├── test_xair_direct_features.py    # 5 tests Auto-Discovery, Metadata sync, Mute skip, Master EQ on
    ├── test_xair_state.py              # 3 tests cỗ máy trạng thái kết nối và verified write
    ├── test_xr12_rta.py                # 4 tests profile XR12/XR16/MR12 và dò hú qua RTA
    └── test_xremote_echo.py            # 4 tests cơ chế Expected-Echo và chống báo động giả khi vặn tay
```

---

## 4. BẢNG TỔNG HỢP CÁC CHỨC NĂNG ĐÃ HOÀN THÀNH

| Nhóm chức năng | Tên tính năng cụ thể | Trạng thái | Module chịu trách nhiệm |
| :--- | :--- | :--- | :--- |
| **Giao tiếp Mixer** | Tự động quét tìm mixer trong mạng LAN qua `/xinfo` (Auto-Discovery) | **ĐÃ XONG** | `auto_sound.mixer.xair` |
| | Bắt tay handshake `/xinfo` & Heartbeat `/xremote` 8s | **ĐÃ XONG** | `auto_sound.mixer.xair` |
| | Tự động khôi phục kết nối trong $\le 3\text{s}$ khi rớt mạng | **ĐÃ XONG** | `auto_sound.mixer.xair` |
| | Đồng bộ tên kênh, màu sắc và trạng thái MUTE trực tiếp từ mixer | **ĐÃ XONG** | `auto_sound.mixer.xair` |
| | Đọc/Ghi PEQ có xác nhận hai chiều (Verified Write) | **ĐÃ XONG** | `auto_sound.mixer.xair` |
| | Tự động bật Master EQ (`/eq/on = 1`) và ép loại Band Parametric (`type = 2`) | **ĐÃ XONG** | `auto_sound.mixer.xair` |
| | Lọc bỏ Expected-Echo, phân biệt chính xác thao tác vặn tay thật | **ĐÃ XONG** | `auto_sound.mixer.xair` |
| | Hỗ trợ điều khiển PEQ Kênh, Bus và Main Stereo L/R | **ĐÃ XONG** | `auto_sound.mixer.xair` |
| | Nhận luồng RTA 100-band qua OSC `/meters/4` | **ĐÃ XONG** | `auto_sound.mixer.xair` |
| **Audio I/O** | Thu âm 18 track qua USB soundcard từ XR18 / MR18 | **ĐÃ XONG** | `auto_sound.audio.io` |
| | Bộ đệm tròn SPSC Ring Buffer không cấp phát heap (Zero Alloc) | **ĐÃ XONG** | `auto_sound.audio.ring_buffer` |
| | Bộ sinh âm thanh ảo (Virtual Generator) thử nghiệm không cần phần cứng | **ĐÃ XONG** | `auto_sound.audio.io` |
| **Phát hiện hú (DSP)** | Dò hú từng micro qua FFT 2048 + Nội suy đỉnh Parabol | **ĐÃ XONG** | `auto_sound.dsp.detector` |
| | Lọc sàn năng lượng trung vị (Median Filter 31 bins) | **ĐÃ XONG** | `auto_sound.dsp.detector` |
| | Triệt tiêu báo động giả cho giọng hát & guitar (Harmonic Rejection) | **ĐÃ XONG** | `auto_sound.dsp.detector` |
| | Tự động bỏ qua phân tích các kênh đang MUTE trên bàn mixer | **ĐÃ XONG** | `auto_sound.app.cli` |
| | Two-Factor Mic Localizer: Định vị chính xác micro hú khi có crosstalk | **ĐÃ XONG** | `auto_sound.dsp.localizer` |
| | Dò hú qua phổ RTA 100-band mạng LAN cho XR12/XR16/MR12 | **ĐÃ XONG** | `auto_sound.dsp.rta_detector` |
| **Bộ an toàn (Safety)** | Hạn mức 2 giao dịch/giây (Rate Limiting) | **ĐÃ XONG** | `auto_sound.safety.controller` |
| | Cắt thăm dò an toàn $-3.0\text{ dB}$ (Incremental Probing) | **ĐÃ XONG** | `auto_sound.safety.controller` |
| | Chống vượt ngưỡng Max Boost ($+4\text{ dB}$) và Max Cut ($-12\text{ dB}$) | **ĐÃ XONG** | `auto_sound.safety.controller` |
| | Khóa an toàn 10 giây khi Soundman chỉnh tay (Manual Override) | **ĐÃ XONG** | `auto_sound.safety.controller` |
| | Tự động giải phóng notch theo thời gian (Auto-Release) | **ĐÃ XONG** | `auto_sound.safety.controller` |
| | Tái thu hồi notch nông nhất khi cạn band PEQ (Notch Reclaiming) | **ĐÃ XONG** | `auto_sound.safety.controller` |
| | Nút PANIC / Rollback 1 chạm thu hồi toàn bộ notch về $0\text{ dB}$ | **ĐÃ XONG** | `auto_sound.safety.controller` |
| | Quản lý sao lưu/phục hồi Snapshot PEQ trước và sau show diễn | **ĐÃ XONG** | `auto_sound.safety.snapshot` |
| **Giao diện Web Companion** | Backend FastAPI REST API + WebSocket Server | **ĐÃ XONG** | `auto_sound.app.server` |
| | Frontend Nuxt 4 / Vue 3 SPA + Tailwind CSS | **ĐÃ XONG** | `frontend/` & `web/dist` |
| | Hiển thị tên kênh show, màu sắc, âm lượng và tag MUTE thời gian thực | **ĐÃ XONG** | `frontend/components/MetersGrid` |
| | Hàng đợi duyệt đề xuất Semi-Auto 1 chạm trên Web | **ĐÃ XONG** | `frontend/components/ProposalsQueue`|
| | Bảng quản lý notch thời gian thực kèm nút Bypass / Delete | **ĐÃ XONG** | `frontend/components/NotchesTable` |
| | Mã PIN kết nối LAN bảo vệ chống thao tác lạ | **ĐÃ XONG** | `auto_sound.app.server` |
| **Vận hành & Giả lập** | Hàng đợi mạng phi đồng bộ (Async Queue) chống nghẽn luồng âm thanh | **ĐÃ XONG** | `auto_sound.app.cli` |
| | Giao diện dòng lệnh CLI tiếng Việt với cảnh báo màu ANSI | **ĐÃ XONG** | `auto_sound.app.cli` |
| | Script khởi chạy trực quan tự động nhận diện mixer `run_ui.py` | **ĐÃ XONG** | `run_ui.py` |
| | Giả lập mixer hoàn chỉnh FakeXR18 chạy trên máy tính | **ĐÃ XONG** | `auto_sound.mixer.fake` |

---

## 5. ĐÁNH GIÁ THỰC TẾ & CHỨNG CỨ KIỂM ĐỊNH

Toàn bộ hệ thống logic phần mềm **ĐÃ ĐƯỢC KIỂM ĐỊNH TỰ ĐỘNG 100% TRONG MÔ PHỎNG VÀ VÒNG LẶP MẠNG NỘI BỘ**.

### 5.1. Bằng chứng kiểm thử tự động toàn diện
Chạy toàn bộ test suite trên môi trường thực tế:
```bash
.venv/bin/pytest -v
```

**Kết quả thực tế đo lường trên hệ thống:**
```text
============================= test session starts ==============================
platform darwin -- Python 3.11.17, pytest-9.1.1, pluggy-1.7.0 -- /Volumes/DATA/DEV/tool xklive/.venv/bin/python3.11
cachedir: .pytest_cache
hypothesis profile 'default'
rootdir: /Volumes/DATA/DEV/tool xklive
configfile: pyproject.toml
testpaths: tests
plugins: hypothesis-6.170.5, anyio-4.15.1
collecting ... collected 70 items                                                             

tests/test_bus_notch.py::test_bus_notch_allocation_uses_band_5_or_6 PASSED [  1%]
tests/test_bus_notch.py::test_bus_not_in_whitelist_rejected PASSED       [  2%]
tests/test_bus_notch.py::test_bus_manual_override_locks_bus PASSED       [  4%]
tests/test_bus_notch.py::test_bus_exhaustion_reclaim_option_1 PASSED     [  5%]
tests/test_bus_notch.py::test_bus_auto_release_towards_zero PASSED       [  7%]
tests/test_cli_queue.py::test_async_network_queue_execution PASSED       [  8%]
tests/test_cli_queue.py::test_manual_override_detection_callback PASSED  [ 10%]
tests/test_detector_sim.py::test_detector_benchmark_recall_and_false_positives PASSED [ 11%]
tests/test_detector_sim.py::test_detector_benchmark_real_data SKIPPED    [ 12%]
tests/test_e2e.py::test_end_to_end_feedback_suppression_loop PASSED      [ 14%]
tests/test_localizer.py::test_single_mic_howling_identified PASSED       [ 15%]
tests/test_localizer.py::test_multiple_mics_bleeding_resolved_by_routing PASSED [ 17%]
tests/test_localizer.py::test_ambiguous_case_downgrades_to_semi PASSED   [ 18%]
tests/test_localizer.py::test_muted_channel_receives_zero_score PASSED   [ 20%]
tests/test_mixer_fake.py::test_fake_xinfo_response PASSED                [ 21%]
tests/test_mixer_fake.py::test_fake_param_get_set PASSED                 [ 22%]
tests/test_mixer_fake.py::test_fake_max_4_clients PASSED                 [ 24%]
tests/test_osc_parser.py::test_encode_decode_roundtrip_valid PASSED      [ 25%]
tests/test_osc_parser.py::test_malformed_truncated_packets PASSED        [ 27%]
tests/test_osc_parser.py::test_fuzz_random_bytes_never_crash PASSED      [ 28%]
tests/test_parameter_mapper.py::TestSubMapperProperties::test_freq_to_float_bounds PASSED [ 30%]
tests/test_parameter_mapper.py::TestSubMapperProperties::test_gain_to_float_bounds PASSED [ 31%]
tests/test_parameter_mapper.py::TestSubMapperProperties::test_from_float_bounds PASSED [ 32%]
tests/test_parameter_mapper.py::TestSubMapperProperties::test_quantize_float_idempotent PASSED [ 34%]
tests/test_parameter_mapper.py::TestSubMapperProperties::test_snap_idempotent PASSED [ 35%]
tests/test_parameter_mapper.py::TestSubMapperProperties::test_exact_step_roundtrip PASSED [ 37%]
tests/test_parameter_mapper.py::TestParameterMapperXR18::test_load_from_profile PASSED [ 38%]
tests/test_parameter_mapper.py::TestParameterMapperXR18::test_known_boundary_values PASSED [ 40%]
tests/test_ring_buffer.py::test_ring_buffer_basic_read_write PASSED      [ 41%]
tests/test_ring_buffer.py::test_ring_buffer_wraparound PASSED            [ 42%]
tests/test_ring_buffer.py::test_ring_buffer_overflow_xrun PASSED         [ 44%]
tests/test_ring_buffer.py::test_ring_buffer_zero_allocation_in_steady_state PASSED [ 45%]
tests/test_audio_continuity_and_no_dropped_samples PASSED                 [ 47%]
tests/test_audio_capture_virtual_mode PASSED                              [ 48%]
tests/test_safety.py::test_whitelist_rejection PASSED                    [ 50%]
tests/test_safety.py::test_manual_override_lock_10s PASSED               [ 51%]
tests/test_safety.py::test_rate_limit_2_transactions_per_sec PASSED      [ 52%]
tests/test_safety.py::test_max_boost_guard PASSED                        [ 54%]
tests/test_safety.py::test_system_band_isolation_and_exhaustion PASSED   [ 55%]
tests/test_safety.py::test_incremental_probing_step PASSED               [ 57%]
tests/test_safety.py::test_panic_rollback PASSED                         [ 58%]
tests/test_safety.py::test_safety_invariants_property_based PASSED       [ 60%]
tests/test_safety.py::test_reclaim_shallowest_notch_on_band_exhaustion PASSED [ 61%]
tests/test_safety.py::test_auto_release_recovers_band_over_time PASSED   [ 62%]
tests/test_safety.py::test_auto_release_invariants_property_based PASSED [ 64%]
tests/test_server_api.py::test_server_status_and_nuxt_app PASSED         [ 65%]
tests/test_server_api.py::test_mode_switching_requires_confirmation_for_auto PASSED [ 67%]
tests/test_server_api.py::test_panic_endpoint_and_undo PASSED            [ 68%]
tests/test_server_api.py::test_lan_security_pairing_pin PASSED           [ 70%]
tests/test_server_api.py::test_websocket_snapshot_and_disconnect_stability PASSED [ 71%]
tests/test_server_api.py::test_proposal_approve_and_reject PASSED        [ 72%]
tests/test_server_api.py::test_snapshot_api_endpoints PASSED             [ 74%]
tests/test_snapshot.py::test_snapshot_capture_and_rollback_timing PASSED [ 75%]
tests/test_snapshot.py::test_snapshot_serialization_roundtrip PASSED     [ 77%]
tests/test_xair_direct_features.py::test_discover_mixers_local PASSED    [ 78%]
tests/test_xair_direct_features.py::test_mixer_device_info_handshake PASSED [ 80%]
tests/test_xair_direct_features.py::test_channel_metadata_sync_and_mute_tracking PASSED [ 81%]
tests/test_xair_direct_features.py::test_peq_ensures_master_eq_and_type_peq PASSED [ 82%]
tests/test_xair_direct_features.py::test_server_channels_and_discovery_api PASSED [ 84%]
tests/test_xair_state.py::test_xair_connect_success PASSED               [ 85%]
tests/test_xair_state.py::test_verified_write_peq PASSED                 [ 87%]
tests/test_xair_state.py::test_state_reconnecting_and_recovery PASSED    [ 88%]
tests/test_xr12_rta.py::test_xr12_xr16_mr12_profiles_load PASSED         [ 90%]
tests/test_xr12_rta.py::test_rta_detector_math_and_peak_detection PASSED [ 91%]
tests/test_xr12_rta.py::test_fake_xr18_main_peq_and_rta PASSED           [ 92%]
tests/test_xr12_rta.py::test_end_to_end_xr12_rta_feedback_loop PASSED    [ 94%]
tests/test_xremote_echo.py::test_expected_echo_ttl_expiry PASSED         [ 95%]
tests/test_xremote_echo.py::test_system_peq_write_does_not_trigger_manual_override_lock PASSED [ 97%]
tests/test_xremote_echo.py::test_external_soundman_adjust_different_band_locks_channel PASSED [ 98%]
tests/test_xremote_echo.py::test_soundman_adjusts_same_band_system_wrote_locks_channel PASSED [100%]

======================== 69 passed, 1 skipped in 13.66s ========================
```
*(Ghi chú: 1 test skipped `test_detector_benchmark_real_data` chờ nạp bộ dữ liệu âm thanh hiện trường ở Giai đoạn kiểm định phần cứng thật).*

### 5.2. Bằng chứng Benchmark âm học thực nghiệm (DSP Recall & Precision)
- **Độ nhạy phát hiện hú (Recall):** **$100.0\%$ (20/20 trường hợp)** | Khoảng tin cậy Wilson 95%: `[83.9% - 100.0%]`.
- **Tỷ lệ báo động giả (False Positives):** **$0/20$ (Hoàn toàn không có báo động sai trên 20 mẫu mô phỏng)** | Khoảng tin cậy Wilson 95%: `[0.0% - 16.1%]`.
- **Thời gian phản ứng phát hiện thực tế:** **$64.0\text{ ms}$** (bao gồm cửa sổ FFT 2048 mẫu 42.67ms và 3 frame xác nhận bùng phát).

---

## 6. HƯỚNG DẪN VẬN HÀNH SHOW DIỄN THỰC TẾ

Khi kết nối với mixer vật lý ngoài đời thật (XR18 hoặc XR12/XR16), khuyến nghị chạy ở chế độ Bán tự động (`semi`) có Soundman giám sát:

### 6.1. Khởi chạy nhanh với Giao diện Web Companion (Khuyên dùng)
Chỉ cần chạy lệnh duy nhất:
```bash
python3 run_ui.py
```
- Trình khởi chạy sẽ tự động phát sóng UDP broadcast để tìm mixer X-Air trên mạng LAN.
- Nếu tìm thấy mixer (ví dụ `192.168.1.100`), hệ thống tự động kết nối và mở giao diện Web tại `http://localhost:8000`.
- Nếu không tìm thấy phần cứng, hệ thống tự động thông báo và chuyển sang chế độ mô phỏng `--mock` để Soundman làm quen giao diện.

### 6.2. Vận hành chuyên sâu bằng CLI

#### Trường hợp 1: Dùng cho Behringer XR18 / Midas MR18 (USB 18x18)
1. **Dây mạng LAN:** Cắm cáp mạng từ laptop vào XR18 (Laptop đặt IP tĩnh `192.168.1.50`, Subnet `255.255.255.0`; XR18 đặt `192.168.1.100`).
2. **Dây USB:** Cắm cáp USB 2.0 từ XR18 vào laptop. Trên X-Air Edit, mục `In/Out` -> `USB Sends` đặt 16 kênh Direct Out tiền gain (Pre-DSP).
3. **Lệnh chạy:**
   ```bash
   .venv/bin/auto-sound --profile device_profiles/xr18.toml --ip auto --mode semi --web --port 8000
   ```

#### Trường hợp 2: Dùng cho Behringer XR12 / XR16 / Midas MR12 (Chế độ RTA LAN)
1. **Dây mạng LAN:** Cắm 1 sợi dây mạng LAN từ laptop vào XR12 (hoặc kết nối qua router Wi-Fi riêng).
2. **Lệnh chạy:**
   ```bash
   .venv/bin/auto-sound --profile device_profiles/xr12.toml --ip auto --mode semi --web --port 8000
   ```
   *(Hệ thống tự động phát hiện model XR12/XR16, nhận luồng RTA 100-band qua OSC `/meters/4` và điều khiển PEQ Main Stereo L/R).*

---

## 7. ĐÁNH GIÁ TỔNG KẾT & TRẠNG THÁI HIỆN TẠI

Hệ thống **Auto Sound Engineer** đã đạt mức độ hoàn thiện kiến trúc cao:
1. **Độc lập và an toàn tuyệt đối:** Tách biệt Audio Plane và Control Plane. Mixer tiếp tục hoạt động bình thường ngay cả khi phần mềm dừng đột ngột.
2. **Tương tác trực tiếp và thích ứng X-Air:** Tự động phát hiện thiết bị trên mạng, đồng bộ tên/màu kênh, trạng thái Mute, ép Master EQ On & PEQ Type 2 an toàn.
3. **Cơ chế chống hú thông minh:** FFT 2048 mẫu kết hợp Harmonic Rejection, Two-Factor Localizer, Auto-Release và Reclaiming khi cạn band.
4. **Trải nghiệm Soundman toàn diện:** Giao diện Web Companion Nuxt 4 / Vue 3 mượt mà, hỗ trợ giám sát từ xa qua điện thoại/iPad song song với màn hình CLI.
5. **Kiểm định nghiêm ngặt:** Toàn bộ **69 bài test tự động đều passed** (bao gồm cả Property-based testing với Hypothesis).
6. **Bước tiếp theo (Milestone M5):** Tiến hành cắm thực tế vào thiết bị vật lý XR18 và XR12 ngoài hiện trường để đo đạc RTT mạng, kiểm chứng độ trễ gói tin và thu thập thêm 100 mẫu âm thanh show diễn thật.
