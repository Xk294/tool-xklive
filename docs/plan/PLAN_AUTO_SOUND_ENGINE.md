# KẾ HOẠCH PHÁT TRIỂN HỆ THỐNG "AUTO SOUND ENGINEER" (BẢN NÂNG CẤP HOÀN THIỆN)
## Hệ thống Tự động Cân chỉnh Âm học, Căn Pha, Chống Hú và Điều khiển Đa Mixer Digital / Analog

---

## MỤC LỤC
1. [TỔNG QUAN DỰ ÁN & ĐỊNH HƯỚNG KIẾN TRÚC](#1-tổng-quan-dự-án--định-hướng-kiến-trúc)
2. [MA TRẬN NĂNG LỰC & GIAO THỨC ĐIỀU KHIỂN CÁC DÒNG MIXER](#2-ma-trận-năng-lực--giao-thức-điều-khiển-các-dòng-mixer)
3. [KIỂM TOÁN MÃ NGUỒN MỞ & BẢN ĐỒ GIẤY PHÉP (SBOM)](#3-kiểm-toán-mã-nguồn-mở--bản-đồ-giấy-phép-sbom)
4. [ĐỐI CHUẨN THƯƠNG MẠI & KHOẢNG TRỐNG KỸ THUẬT](#4-đối-chuẩn-thương-mại--khoảng-trống-kỹ-thuật)
5. [THIẾT KẾ KIẾN TRÚC HỆ THỐNG (TÁCH BIỆT AUDIO VÀ CONTROL)](#5-thiết-kế-kiến-trúc-hệ-thống-tách-biệt-audio-và-control)
6. [THIẾT KẾ CHI TIẾT THUẬT TOÁN XỬ LÝ TÍN HIỆU (DSP CORE)](#6-thiết-kế-chi-tiết-thuật-toán-xử-lý-tín-hiệu-dsp-core)
7. [GIẢI PHÁP CHO MIXER ANALOG & PHẦN CỨNG FAIL-SAFE DẬP NỔ DC](#7-giải-pháp-cho-mixer-analog--phần-cứng-fail-safe-dập-nổ-dc)
8. [CHIẾN LƯỢC AN TOÀN, BENCHMARK & CHỈ SỐ KPI](#8-chiến-lược-an-toàn-benchmark--chỉ-số-kpi)
9. [LỘ TRÌNH TRIỂN KHAI THEO MILESTONE (M0 – M8)](#9-lộ-trình-triển-khai-theo-milestone-m0--m8)
10. [KẾ HOẠCH HÀNH ĐỘNG 2 TUẦN ĐẦU TIÊN (SPRINT 1 & SPRINT 2)](#10-kế-hoạch-hành-động-2-tuần-đầu-tiên-sprint-1--sprint-2)
11. [BẢN QUYẾT ĐỊNH CÔNG NGHỆ & DEFINITION OF DONE (DoD)](#11-bản-quyết-định-công-nghệ--definition-of-done-dod)

---

## 1. TỔNG QUAN DỰ ÁN & ĐỊNH HƯỚNG KIẾN TRÚC

### 1.1 Mục tiêu Sản phẩm
**Auto Sound Engineer** là hệ thống phần mềm và phần cứng phụ trợ thông minh dành cho kỹ sư âm thanh biểu diễn trực tiếp (Live Sound / FOH / Monitor), hỗ trợ tự động hóa các tác vụ phức tạp:
- **Auto EQ:** Tự động đo đạc đáp tuyến phòng và cân chỉnh Equalizer cho hệ thống loa PA mà không làm méo âm sắc tự nhiên, tuyệt đối tránh bù vào các hố triệt tiêu pha (Acoustic Nulls).
- **Feedback Suppression:** Tự động phát hiện và triệt tiêu tiếng hú (acoustic feedback) theo thời gian thực với độ trễ dưới 150ms, phân biệt chính xác tiếng hú với nốt nhạc/nhạc cụ, định vị chính xác Kênh micro và đường Aux Bus Monitor gây hú thay vì cắt bừa toàn bộ hệ thống.
- **Phase & Sub Alignment:** Cân chỉnh độ trễ thời gian (Delay), đồng bộ pha và cực tính giữa loa Subwoofer và loa Full-range tại vùng cắt tần số (Crossover).
- **Multi-Mixer Control:** Điều khiển thông suốt các dòng mixer phổ biến trên thị trường thông qua mạng LAN hoặc MIDI.

### 1.2 Quyết định Kiến trúc Tối ưu: Kiến trúc Lai (Phương án D)
Sau khi đối chiếu kỹ thuật giữa 4 mô hình:
- *Phương án A (Điều khiển mixer qua mạng)*
- *Phương án B (Xử lý toàn bộ luồng audio qua máy tính)*
- *Phương án C (Hộp phần cứng DSP độc lập cắm trên đường tiếng)*
- *Phương án D (Kiến trúc lai)*

**Quyết định chiến lược:**
1. **Đối với Mixer Digital (XR12/16/18, MR12/18, X32/M32, Yamaha):** 
   - **Áp dụng triệt để Phương án A:** Âm thanh của show diễn đi trực tiếp từ mic nhạc cụ vào Mixer Digital ra loa PA. **Tuyệt đối không đưa luồng audio FOH/Monitor chính đi qua máy tính**.
   - Máy tính của kỹ sư đóng vai trò "Bộ não Đo lường & Giám sát Ngoài dải" (Out-of-band Brain): Thu nhận tín hiệu từ microphone đo lường (RTA mic), phân tích FFT, phát hiện hú hoặc đáp tuyến phòng, sau đó gửi lệnh tham số (OSC / SysEx) sang Mixer Digital thông qua một tầng kiểm duyệt an toàn (**Safety Controller**).
   - **Ưu điểm sống còn:** Nếu phần mềm máy tính bị treo, sập nguồn hoặc đứt cáp mạng, **âm thanh show diễn vẫn phát 100% bình thường, không gián đoạn**.
2. **Đối với Mixer Analog:**
   - **Bổ sung Phương án C (Hộp phần cứng DSP ngoài):** Đặt tại đường Insert hoặc Master/Monitor Out, sử dụng nền tảng nhúng (Raspberry Pi CM4 / Elk Audio OS) tích hợp **Relay cơ điện Bypass thụ động có mạch dập nổ DC** (Hardware Fail-safe Relay with Soft-Muting) tự động nối tắt mạch âm thanh khi mất điện hoặc lỗi phần cứng mà không gây nổ tiếng bụp ra loa.

---

## 2. MA TRẬN NĂNG LỰC & GIAO THỨC ĐIỀU KHIỂN CÁC DÒNG MIXER

### 2.1 Xác minh Thực tế Phần cứng
> **KẾT LUẬN THẨM ĐỊNH:** **Midas MR16 KHÔNG TỒN TẠI.** 
> Trong danh mục sản phẩm chính thức của Music Tribe / Midas M-Air, hãng chỉ sản xuất:
> - **Midas MR12:** 4 preamp Midas Pro, 2 Aux out, ghi âm USB 2-track stereo.
> - **Midas MR18:** 16 preamp Midas Pro, 6 Aux out, USB audio interface 18x18 multitrack.
> Sự xuất hiện của khái niệm "MR16" là do người dùng nhầm lẫn với dòng vỏ nhựa **Behringer X AIR XR16**. Hệ thống phần mềm ghi nhận chính xác danh mục thiết bị thực tế này.

### 2.2 Quy chuẩn Ánh xạ Tham số OSC (Normalized Parameter Mapping) & Giới hạn Client
1. **Ánh xạ Tham số Chuẩn hóa (Bidirectional Parameter Mapping):**
   Firmware Behringer X-Air và X32 không nhận trực tiếp giá trị số $\text{Hz}, \text{dB}, Q$ ở dạng thô mà chuẩn hóa về dải số thực `float32 [0.0, 1.0]`:
   - **Tần số ($20\text{Hz} - 20\text{kHz}$):** Biểu diễn theo hàm logarit:
     $$v_{\text{norm}} = \frac{\log_{10}(f / 20.0)}{\log_{10}(20000.0 / 20.0)} = \frac{\log_{10}(f / 20.0)}{3.0}$$
     $$f = 20.0 \times 10^{3.0 \cdot v_{\text{norm}}}$$
   - **Gain ($-15\text{dB} - +15\text{dB}$):** Biểu diễn theo hàm tuyến tính:
     $$v_{\text{norm}} = \frac{\text{Gain}_{\text{dB}} + 15.0}{30.0} \implies 0.0 = -15\text{dB},\; 0.5 = 0\text{dB},\; 1.0 = +15\text{dB}$$
   - **Hệ số Phẩm chất $Q$ ($10.0 - 0.3$):** Biểu diễn theo hàm nghịch đảo logarit.
   *(Module `XAirClient` bắt buộc phải tích hợp bộ ánh xạ 2 chiều này để tránh kẹp nhầm giá trị về 20kHz).*
2. **Giới hạn Kết nối Client Vật lý (4-Client Connection Limit):**
   - Mixer XR12/16/18 chỉ hỗ trợ tối đa **4 client UDP `/xremote` hoạt động đồng thời**.
   - Phần mềm tự động kiểm tra số lượng subscription khi gửi `/xinfo`. Cung cấp 2 chế độ:
     - **Active Monitoring Mode:** Duy trì heartbeat `/xremote` 8s/lần khi số client $< 4$.
     - **Passive Sniffer / One-shot Mode:** Khi mạng đã có 4 thiết bị kết nối (ví dụ 3 app X-Air-Q + 1 app X-Air-Edit), phần mềm chuyển sang chế độ không duy trì subscription liên tục mà chỉ gửi truy vấn và đẩy lệnh notch khi cần, tránh làm sập kết nối của mixer.

### 2.3 Bảng Ma trận Năng lực Điều khiển Chi tiết

| Tiêu chí Đánh giá | Behringer XR12 / XR16 | Behringer XR18 / Midas MR18 | Midas MR12 | Behringer X32 / Midas M32R | Yamaha LS9 | Yamaha 01V96 / 01V96V2 | Yamaha 01V96i |
|---|---|---|---|---|---|---|---|
| **Giao thức điều khiển** | OSC qua UDP (Port 10024) | OSC qua UDP (Port 10024) | OSC qua UDP (Port 10024) | OSC qua UDP (Port 10023) | MIDI SysEx & Proprietary TCP | MIDI SysEx (Model ID 0x3E) | MIDI SysEx (Model ID 0x3E) |
| **Giao diện vật lý** | Ethernet RJ45, Wi-Fi | Ethernet RJ45, Wi-Fi, MIDI DIN | Ethernet RJ45, Wi-Fi | Ethernet RJ45, USB, MIDI DIN | MIDI DIN, USB-MIDI, Ethernet (DME-N) | USB 1.1 MIDI, MIDI DIN, YGDAI | USB 2.0 Audio+MIDI, MIDI DIN |
| **Đọc Meter/RTA mở** | ✅ Có (`/meters` blob 50ms) | ✅ Có (`/meters` blob 50ms) | ✅ Có (`/meters` blob 50ms) | ✅ Có (`/meters/1..13` blob) | ❌ Không có API mở | ❌ Không có API mở | ⚠️ Qua luồng USB Audio 16ch |
| **Đọc/Ghi PEQ realtime** | ✅ Toàn diện (Normalized Float) | ✅ Toàn diện (Normalized Float) | ✅ Toàn diện (Normalized Float) | ✅ Toàn diện (Normalized Float) | ✅ Qua SysEx Param Change | ✅ Qua SysEx Param Change | ✅ Qua SysEx Param Change |
| **Đổi tham số khi đang diễn** | ✅ Tức thì (<5ms) | ✅ Tức thì (<5ms) | ✅ Tức thì (<5ms) | ✅ Tức thì (<5ms) | ✅ Viết vào Edit Buffer | ✅ Viết vào Edit Buffer | ✅ Viết vào Edit Buffer |
| **Bắt sự kiện chỉnh tay** | ✅ Có (`/xremote` push) | ✅ Có (`/xremote` push) | ✅ Có (`/xremote` push) | ✅ Có (`/xremote` push 2 chiều) | ⚠️ Có (Bật Param Change TX) | ⚠️ Có (Bật Param Change TX) | ⚠️ Có (Bật Param Change TX) |
| **Giới hạn tốc độ phản hồi** | Max 4 clients; timeout 10s | Max 4 clients; timeout 10s | Max 4 clients; timeout 10s | Cực kỳ ổn định (100Mbps) | Băng thông MIDI 31.25kbps | Băng thông MIDI hẹp, driver cũ | USB 2.0 ổn định hơn |
| **Tính khả thi cho Auto EQ** | ✅ RẤT CAO | ✅ RẤT CAO (MVP chuẩn) | ✅ RẤT CAO | ✅ RẤT CAO (Chuẩn tour) | ⚠️ TRUNG BÌNH (Cần mic đo ngoài) | ⚠️ THẤP (Độ trễ SysEx cao) | ⚠️ TRUNG BÌNH (Tận dụng USB multitrack) |
| **Xếp hạng ưu tiên phát triển** | Hạng 2 | **Hạng 1 (Ưu tiên số 1 cho MVP)** | Hạng 2 | **Hạng 1 (Ưu tiên số 1 cho Tour)** | Hạng 3 | Hạng 4 | Hạng 3 |

---

## 3. KIỂM TOÁN MÃ NGUỒN MỞ & BẢN ĐỒ GIẤY PHÉP (SBOM)

### 3.1 Chiến lược Đóng mã nguồn Thương mại Hợp pháp
Để đảm bảo sản phẩm thương mại có thể đóng mã nguồn phần lõi (Proprietary Closed-Source) mà không vi phạm pháp lý:
1. **Tuân thủ quy tắc Copyleft:** Tuyệt đối không nhúng (statically/dynamically link) bất kỳ mã nguồn nào mang giấy phép **GPLv2, GPLv3, AGPL**.
2. **Khai thác giấy phép tự do (Permissive):** Chỉ tích hợp trực tiếp các thư viện có giấy phép **MIT, BSD-3-Clause, Apache-2.0**.
3. **Phòng tránh bẫy chi phí FFTW:** FFTW đòi hỏi phí thương mại \$12,500 cho binary đóng mã nguồn. Dự án thay thế hoàn toàn bằng **pocketfft (BSD-3-Clause)** hoặc **kissfft (BSD-3-Clause)** với hiệu năng tương đương 90-95%.

### 3.2 Bảng Software Bill of Materials (SBOM)

| Thư viện / Module | URL tham chiếu | Giấy phép thực tế | Quyết định tích hợp | Lý do & Nghĩa vụ pháp lý |
|---|---|---|---|---|
| **PortAudio** | `github.com/PortAudio/portaudio` | **MIT** | **Dùng trực tiếp** | Thu âm tín hiệu microphone đo lường đa nền tảng. Giữ Copyright Notice trong phần thông tin phần mềm. |
| **pocketfft** | `github.com/mreineck/pocketfft` | **BSD-3-Clause** | **Dùng trực tiếp** | Biến đổi nhanh Fourier (FFT/IFFT) thay thế FFTW. Giữ nguyên thông báo bản quyền BSD. |
| **remote-mixer** | `github.com/kryops/remote-mixer` | **MIT** | **Trích xuất logic driver** | Driver giao tiếp Yamaha 01V96 (MIDI) và X32 (OSC). Giữ thông báo bản quyền MIT. |
| **magical-mixing-console** | `github.com/matiasbarrios/magical-mixing-console` | **Apache-2.0** | **Tham khảo kiến trúc** | Cơ chế đồng bộ hóa trạng thái mixer X-Air. Giữ file NOTICE và LICENSE của Apache 2.0. |
| **biquad-rs** | `github.com/korken89/biquad-rs` | **MIT / Apache-2.0** | **Dùng trực tiếp** | Công thức tính hệ số bộ lọc số IIR Biquad (PEQ/Notch). Kèm giấy phép MIT thông thường. |
| **Open Sound Meter** | `github.com/psmokotnin/osm` | **GPL-3.0** | ❌ **CẤM LINK CODE** | Chỉ sử dụng như một phần mềm độc lập bên ngoài để đo kiểm đối chứng chéo kết quả tính toán. |
| **AutoEQ / RoomEQ** | `github.com/pierreaubert/autoeq` | **GPL-3.0** | ❌ **CẤM DÙNG CODE** | Tự viết độc lập giải thuật tối ưu hóa dựa trên tài liệu toán học công cộng. Giai đoạn MVP dùng giải thuật Heuristic Inversion. |
| **CamillaDSP** | `github.com/HEnquist/camilladsp` | **Dual GPLv3 / MPL-2.0** | ⚠️ **CHỈ DÙNG QUA IPC** | Dành riêng cho hộp DSP analog. Chạy dưới dạng tiến trình ngầm (Daemon), giao tiếp qua WebSocket API. |
| **notameadow/xair-osc** | `github.com/notameadow/xair-osc` | **KHÔNG CÓ LICENSE** | ❌ **CẤM DÙNG CODE** | Không có license = All Rights Reserved. Tự viết bộ parser OSC riêng cho dự án. |

---

## 4. ĐỐI CHUẨN THƯƠNG MẠI & KHOẢNG TRỐNG KỸ THUẬT

### 4.1 Bảng Đối chuẩn Tính năng với Thiết bị Đầu ngành

| Thiết bị / Giải pháp | Nguyên lý vận hành | Điểm mạnh cốt lõi | Nhược điểm cố hữu | Khoảng trống Auto Sound Engineer chiếm lĩnh |
|---|---|---|---|---|
| **dbx AFS2 / DriveRack** | Hộp DSP cứng, chèn notch 1/80 octave tự động. | Cực kỳ ổn định, cắm là chạy. | Bắt buộc đi dây analog cồng kềnh; không can thiệp được từng bus mixer; dễ cắt nhầm nốt nhạc. | **Điều khiển trực tiếp mixer digital qua mạng LAN không cần mua thêm thiết bị phần cứng.** Cắt đúng bus monitor bị hú. |
| **Rational Smaart v9** | Phân tích 2 kênh Transfer Function thời gian thực. | Chuẩn công nghiệp toàn cầu, cực kỳ chính xác. | Giá rất đắt (\$1,000+); **hoàn toàn thụ động** (kỹ sư nhìn đồ thị rồi tự chỉnh tay bằng mixer). | **Tự động hóa chu trình khép kín:** Đo $\rightarrow$ Phân tích $\rightarrow$ Tự động tính toán và gửi lệnh EQ vào mixer chỉ với 1 click. |
| **Dirac Live / Trinnov** | Mixed-phase FIR+IIR filter cân chỉnh phòng. | Triệt tiêu phản xạ phòng tuyệt vời. | Độ trễ âm thanh lớn (20ms–80ms), không thể dùng cho ca sĩ hát live sân khấu; hệ sinh thái đóng. | **Tối ưu hóa độ trễ zero latency** sử dụng IIR PEQ và delay dành riêng cho môi trường live sound biểu diễn trực tiếp. |

### 4.2 Các Thành phần Không Đáng Xây Lại (Do Not Reinvent the Wheel)
- **Công thức toán học Biquad IIR:** Các phương trình tính hệ số lọc Robert Bristow-Johnson (Audio EQ Cookbook) là chuẩn mực công khai, áp dụng trực tiếp.
- **Biến đổi FFT cơ bản:** Sử dụng `pocketfft` tối ưu sẵn SIMD (AVX, NEON), không tự viết lại thuật toán Cooley-Tukey.
- **Thư viện socket UDP/MIDI mức thấp:** Sử dụng socket tiêu chuẩn của OS hoặc PortAudio/PortMidi.

---

## 5. THIẾT KẾ KIẾN TRÚC HỆ THỐNG (TÁCH BIỆT AUDIO VÀ CONTROL)

### 5.1 Sơ đồ Phân tách Luồng Tín hiệu (Architecture Dataflow)

```
======================================================================================================
[MẶT PHẲNG ÂM THANH - AUDIO PLANE] (Hoàn toàn độc lập, không đi qua máy tính xử lý chính)
======================================================================================================

 [Microphones Ca sĩ / Nhạc cụ]
           │
           ▼ (Analog XLR)
 ┌────────────────────────────────────────────────────────────────────────┐
 │                      DIGITAL MIXER (XR18 / X32 / M32)                 │
 │                                                                        │
 │  Input Channels ──► Channel PEQ ──► Aux / Monitor Buses ──► Bus PEQ   │
 │         │                                                       │      │
 │         └─────────► Main LR Bus ──► Main PEQ/GEQ ───────────────┼──────┘
 └─────────────────────────┬───────────────────────────────────────┼──────
                           │ (Analog Out)                          │ (Analog Out)
                           ▼                                       ▼
                  [PA Amplifiers / Loa FOH]             [Loa Monitor Sân khấu]
                           │                                       │
                           ░░░░░░░░░ Sóng âm thanh phòng ░░░░░░░░░░░
                                                   │
                                                   ▼
                                     [Calibrated Measurement Mic]
                                                   │ (Analog XLR)
                                                   ▼
                                    ┌─────────────────────────────┐
                                    │ Audio Interface (Soundcard) │
                                    └──────────────┬──────────────┘
                                                   │ (USB Audio Capture)
                                                   ▼
===================================================================================
[MẶT PHẲNG ĐIỀU KHIỂN & ĐO LƯỜNG - CONTROL PLANE] (Chạy trên Laptop Kỹ sư âm thanh)
===================================================================================
                                    ┌─────────────────────────────┐
                                    │    Audio Capture Engine     │
                                    │    (PortAudio / libsoundio) │
                                    └──────────────┬──────────────┘
                                                   │ PCM 48kHz Float32
                                                   ▼
                                    ┌─────────────────────────────┐
                                    │     DSP ANALYTICS CORE      │
                                    │ ─────────────────────────── │
                                    │ • Dual-channel FFT / MTW    │
                                    │ • Feedback Detection Engine │
                                    │ • Two-Factor Localization   │
                                    │ • Auto EQ (Heuristic/SLSQP) │
                                    │ • Phase & Delay (GCC-PHAT)  │
                                    └──────────────┬──────────────┘
                                                   │ Đề xuất can thiệp (Action Proposal)
                                                   │ (Freq, Gain, Q, Channel ID, Aux Bus ID)
                                                   ▼
                                    ┌─────────────────────────────┐
                                    │      SAFETY CONTROLLER      │
                                    │ ─────────────────────────── │
                                    │ • Max Cut/Boost Limit Guard │
                                    │ • Rate Limiter (<2 cmd/sec) │
                                    │ • Channel Whitelist Check   │
                                    │ • Panic Button / Snapshot   │
                                    │ • Operator Manual Confirm   │
                                    └──────────────┬──────────────┘
                                                   │ Lệnh đã phê duyệt (Approved OSC/SysEx)
                                                   ▼
                                    ┌─────────────────────────────┐
                                    │     MIXER DRIVER LAYER      │
                                    │ ─────────────────────────── │
                                    │ • Parameter Mapper (Norm)   │
                                    │ • 4-Client Connection Mgr   │
                                    │ • X-Air / X32 Driver (OSC)  │
                                    │ • Yamaha Driver (SysEx)     │
                                    └──────────────┬──────────────┘
                                                   │ UDP Port 10024 / 10023 / MIDI
                                                   ▼
 [Đường cáp mạng LAN Ethernet] ────────────────────┘ (Gửi lệnh cập nhật tham số vào Mixer)
```

### 5.2 14 Module Phần mềm Chuẩn hóa
1. **Mixer Driver Interface (HAL):** Interface trừu tượng đa hình định nghĩa các tác vụ cơ bản của mixer.
2. **X-Air / X32 Driver:** Giao tiếp UDP OSC, bộ ánh xạ tham số logarit chuẩn hóa `[0.0, 1.0]`, quản lý heartbeat `/xremote`, giải mã `/meters` blob.
3. **Yamaha Driver:** Giao tiếp USB-MIDI / SysEx, phân giải cấu trúc tham số theo Yamaha MIDI Data Format (chẻ 2 byte 7-bit).
4. **Measurement Engine:** Thu nhận âm thanh 2 kênh, thực hiện tính toán Transfer Function $H(f)$, Coherence $\gamma^2(f)$, Impulse Response.
5. **Feedback Detection Engine:** Phân tích FFT thời gian thực, bám bắt đỉnh phổ và nhận dạng hú 4 giai đoạn.
6. **Two-Factor Source Localizer:** Đối chiếu đỉnh hú không gian với bảng Meter đầu vào `/meters/1` và ma trận Send Routing để định vị đích danh Kênh mic và Aux bus gây hú.
7. **EQ Optimization Engine:** Triển khai thuật toán Heuristic Inversion (cho MVP) và SLSQP nâng cao, tích hợp bộ tránh triệt tiêu phòng.
8. **Phase/Delay Alignment Engine:** Đo thời gian trễ bằng GCC-PHAT, khớp độ dốc pha (Phase slope) tại dải tần số cắt.
9. **Safety Controller:** Tầng kiểm soát tối cao, ngăn chặn boost gain quá mức, khống chế Channel Whitelist, giới hạn tần suất gửi lệnh, hỗ trợ Panic/Rollback.
10. **Device Profile Manager:** Lưu trữ profile cấu hình cho từng dòng mixer (dải tần, bước nhảy gain, số lượng band).
11. **Measurement Session Manager:** Quản lý lưu trữ phiên đo đa điểm, snapshot cấu hình trước và sau khi chỉnh.
12. **Audio I/O Backend:** Wrapper PortAudio quản lý buffer kích thước 1024 mẫu @ 48kHz không bị nghẽn (zero dropout).
13. **Logging & Diagnostics:** Ghi log toàn bộ sự kiện tần số hú, cảnh báo mạng, phản hồi của mixer.
14. **User Interface (UI):** Giao diện tương tác trực quan thời gian thực (hiển thị RTA, Phase trace, cảnh báo hú 1-click).

---

## 6. THIẾT KẾ CHI TIẾT THUẬT TOÁN XỬ LÝ TÍN HIỆU (DSP CORE)

### 6.1 Thuật toán Phát hiện Hú Đa Tầng & Định vị Nguồn Gây Hú (Two-Factor Feedback Engine)

#### Quy trình Phân loại 4 Giai đoạn:
Thuật toán phân tích khung âm thanh 2048 mẫu (42.6ms) với 75% overlap qua 4 tầng kiểm tra liên hoàn:

```
[Khung Audio 2048 mẫu (42.6ms)] ──► [Cửa sổ Hann + 75% Overlap FFT]
                                                │
                                                ▼
                             [Giai đoạn 1: Lọc Đỉnh Phổ Hẹp (Peak Prominence)]
                             • Tìm các bin tần số có biên độ vượt ngưỡng nền cục bộ:
                               P(k) = X(k) - median[X(k-M ... k+M)] >= 12 dB
                                                │ (Vượt ngưỡng)
                                                ▼
                             [Giai đoạn 2: Tốc độ Bùng nổ Năng lượng (Growth Rate)]
                             • Kiểm tra độ dốc tăng trưởng năng lượng theo thời gian:
                               GR(k) = [X_n(k) - X_{n-1}(k)] / dt >= 4 dB / frame (hàm mũ)
                                                │ (Tăng trưởng hàm mũ)
                                                ▼
                             [Giai đoạn 3: Độ Ổn định Pha & Tần số (Phase Coherence)]
                             • Tính phương sai vi phân pha qua 3 frame liên tiếp:
                               Var(Δφ_k) <= ε (Feedback có pha cực kỳ ổn định, khóa pha)
                                                │ (Phương sai pha cực thấp)
                                                ▼
                             [Giai đoạn 4: Loại trừ Nốt Nhạc & Nhạc cụ (Harmonic Check)]
                             • Kiểm tra cấu trúc họa âm (Harmonics 2f, 3f): Nếu có => Nhạc cụ / Nốt thẳng.
                             • Kiểm tra vi rung tần số (Vibrato 5-7Hz): Nếu có => Giọng hát.
                             • Kiểm tra Crest Factor: Nếu phân tán rộng => Cymbal / Snare.
                             • Kiểm tra Channel Whitelist: Nếu kênh được đánh dấu Exclude => Bỏ qua.
                                                │ (Xác nhận Feedback tại f_0)
                                                ▼
                             [Giai đoạn 5: Định vị Kênh & Bus (Two-Factor Localization)]
                             • Đọc Meter 16 kênh từ /meters/1: Kênh nào có mức tín hiệu tiệm cận 0dBFS?
                               ===> Xác định Channel ID (ví dụ: Ch 03).
                             • Tra cứu ma trận Send Routing: /ch/03/mix/X/level.
                               ===> Xác định Aux Bus ID (ví dụ: Aux 1).
                                                │
                                                ▼
                             ===> SINH ĐỀ XUẤT NOTCH CHÍNH XÁC:
                                  Target: Aux 1 Bus PEQ (hoặc Channel 3 PEQ)
                                  Params: f_0, Q=60, Gain=-12dB
```

#### Quản lý Danh sách Loại trừ (Channel Whitelist / Exclude List):
Cho phép kỹ sư âm thanh đánh dấu loại trừ các kênh không quét chống hú:
- Kênh Guitar Solo / Lead: Tránh triệt tiêu tiếng feedback nghệ thuật có chủ đích của nghệ sĩ.
- Kênh FX Return (Reverb, Delay): Tránh cắt dải đuôi vang tự nhiên của không gian.

#### Cơ chế Quản lý Bộ lọc Notch Động (Dual-Pool Notch Filters):
- **Fixed Filters (Cố định):** Khóa các dải tần cộng hưởng phòng đo được trong lúc soundcheck; giữ nguyên suốt show.
- **Live Filters (Động nổi):** Tối đa 4 bộ lọc dành cho các sự cố phát sinh trong show. Tích hợp bộ đếm tự nhả (Auto-release Timer): Sau 20 giây ổn định, bộ lọc tự động nâng dần gain về 0dB với tốc độ 1dB/giây để khôi phục âm sắc.

---

### 6.2 Thuật toán Auto EQ: Heuristic Inversion (MVP) & Tránh Hố Triệt Tiêu Phòng

#### Thuật toán Đảo ngược Heuristic (Peak/Dip Inversion Heuristic cho MVP):
Để tránh rủi ro bản quyền và độ phức tạp toán học của bộ giải SLSQP trong giai đoạn khởi đầu, MVP sử dụng thuật toán Heuristic Inversion 100% tự viết:
1. **Lấy trung bình không gian đa điểm (Spatial Averaging):**
   $$\overline{|H(f)|} = \sqrt{\frac{1}{N} \sum_{i=1}^{N} |H_i(f)|^2}$$
2. **Tính sai lệch phổ (Spectral Error):**
   $$E(f) = \overline{|H(f)|} - \text{TargetCurve}(f)$$
3. **Tìm các đỉnh lồi (Prominent Peaks):**
   Tìm các điểm cực đại địa phương có $E(f_p) > +3\text{dB}$.
4. **Gán tham số PEQ:**
   - Tần số trung tâm: $f_m = f_p$.
   - Gain: $g_m = -E(f_p)$ (Ưu tiên gọt đỉnh lồi, giới hạn cắt tối đa $-12\text{dB}$).
   - Hệ số $Q$: Tính theo độ rộng dải $\Delta f$ tại mức giảm $3\text{dB}$: $Q = \frac{f_m}{\Delta f_{3\text{dB}}}$.
5. **Quy tắc Bỏ qua Hố Triệt tiêu Pha (Acoustic Interference Nulls):**
   Một điểm trũng tần số được phân loại là **Acoustic Null bất khả kháng** khi thỏa mãn:
   - Độ sâu trũng $\Delta_{\text{dip}} \ge 10\text{ dB}$.
   - Độ rộng cực hẹp $Q \ge 5.0$.
   - Biến thiên không gian mạnh: Dịch mic 30cm làm độ sâu thay đổi $\ge 6\text{ dB}$.
   $$\text{Nếu } \text{IsAcousticNull}(f_k) == \text{True} \implies \text{CẤM TUYỆT ĐỐI KHÔNG CAN THIỆP BOOST TẠI } f_k$$

---

### 6.3 Thuật toán Căn Pha và Cân Trễ Sub/Full (Phase & Delay Alignment)
1. **Đo độ trễ bằng GCC-PHAT kết hợp Coherence Weighting:**
   $$R_{\text{GCC-PHAT}}(\tau) = \mathcal{F}^{-1} \left[ \frac{X_{\text{ref}}(f) \cdot X_{\text{mic}}^*(f)}{\left| X_{\text{ref}}(f) \cdot X_{\text{mic}}^*(f) \right|} \cdot \gamma^2(f) \right]$$
   - Chỉ tính toán trên các bin tần số có độ tin cậy Coherence $\gamma^2(f) \ge 0.6$. Đỉnh cực đại $\tau_{\text{peak}}$ xác định độ lệch thời gian chính xác tới phần mười mili-giây.
2. **Quy trình Khớp Pha tại Vùng Giao thoa (Crossover Region):**
   - **Polarity Invert:** Nếu góc pha tại điểm cắt lệch từ $150^\circ$ đến $210^\circ$, thực hiện đảo cực trước khi bù delay.
   - **Phase Slope Alignment:** Khớp độ dốc pha giữa Sub và Full trong dải tần cắt $\pm 0.5\text{ octave}$.
   - **Summation Check:** Bật đồng thời cả hai loa; biên độ phải tăng thêm $+4\text{dB}$ đến $+6\text{dB}$ chứng minh đồng pha hoàn hảo.

---

## 7. GIẢI PHÁP CHO MIXER ANALOG & PHẦN CỨNG FAIL-SAFE DẬP NỔ DC

### 7.1 Thừa nhận Giới hạn Vật lý
> **NGUYÊN LÝ VẬT LÝ BẮT BUỘC:** Đối với mixer analog không có giao thức kết nối mạng, nếu chỉ đặt 1 microphone đo duy nhất giữa phòng, hệ thống **HOÀN TOÀN KHÔNG THỂ BIẾT KÊNH MICROPHONE NÀO TRONG BÀN ANALOG ĐANG BỊ HÚ**. 
> Thiết bị phần cứng DSP chỉ có thể can thiệp xử lý trên luồng tín hiệu mà nó được đấu nối vật lý vào:
> - **Cắm vào Insert của Aux Bus Monitor:** Triệt tiêu hú trên riêng đường monitor của ca sĩ đó.
> - **Cắm vào Master Out:** Triệt tiêu hú trên toàn bộ dàn âm thanh FOH.

### 7.2 Thiết kế Mạch Relay Fail-Safe Có Tầng Dập Nổ DC (Anti-Pop Soft-Muting)
- **Core DSP:** Raspberry Pi Compute Module 4 (CM4) chạy **Elk Audio OS** (đạt độ trễ xử lý $\le 1\text{ms}$).
- **Codec ADC/DAC:** Cirrus Logic CS4272 hoặc AKM AK5572/AK4490 (24-bit/96kHz, Balanced XLR $+24\text{dBu}$ Headroom).
- **MẠCH CHUYỂN MẠCH AN TOÀN TRIỆT TIÊU TIẾNG NỔ BỤP (ANTI-POP HARDWARE FAIL-SAFE):**
  - Mắc song song giữa ngõ vào và ngõ ra XLR một cụm **Relay Cơ điện Thường Đóng (NC DPDT Relay)**.
  - Bổ sung **Điện trở xả DC (Bleeder Resistors $100\text{k}\Omega$)** tại cả 2 đầu tiếp điểm xuống mass tín hiệu để xả sạch điện áp tĩnh tích tụ trên tụ ghép tầng.
  - Tích hợp tầng **Mute bán dẫn Photo-MOSFET tốc độ cao (<0.1ms)**:
    - Khi phát hiện sụt nguồn hoặc nhận tín hiệu Watchdog lỗi từ CPU, mạch Photo-MOSFET lập tức dập tắt tín hiệu âm thanh xuống 0V trong vòng $0.1\text{ms}$ *trước khi* tiếp điểm cơ khí của relay nhả.
    - Relay cơ khí nhả tiếp điểm trong vòng $2\text{ms}$ sau đó để nối tắt ngõ vào thẳng sang ngõ ra.
    - Loại bỏ $100\%$ tiếng nổ xung điện DC ("BỤP"), bảo vệ an toàn tuyệt đối cho củ loa treble và amply công suất.

---

## 8. CHIẾN LƯỢC AN TOÀN, BENCHMARK & CHỈ SỐ KPI

### 8.1 Safety Controller: Quy tắc Vận hành An toàn
- **Rate Limiting:** Không cho phép gửi quá 2 lệnh điều khiển EQ trong vòng 1 giây để tránh biến đổi đột ngột âm thanh.
- **Max Gain Guard:** Chặn tuyệt đối mọi lệnh boost gain vượt quá $+4\text{dB}$.
- **Max Notches Guard:** Khống chế tối đa không quá 4–6 notch filter trên cùng một đường tiếng.
- **Operator Override:** Nếu soundman can thiệp kéo fader/EQ bằng tay trên mixer, hệ thống tự động khóa can thiệp trên kênh đó trong 10 giây.
- **Emergency Panic / Snapshot Rollback:** Phím tắt 1-click đưa toàn bộ thông số mixer về trạng thái ban đầu của phiên soundcheck.

### 8.2 Các Chỉ số Đánh giá Hiệu năng (Target KPIs)

| Chỉ số Đo lường | Mục tiêu Thiết kế | Phương pháp Đo kiểm |
|---|---|---|
| **Thời gian phát hiện hú ($T_{\text{detect}}$)** | $< 100\text{ ms}$ | Benchmark trên tập mẫu audio kiểm thử tại 48kHz |
| **Độ trễ điều khiển mạng ($T_{\text{control}}$)** | $< 5\text{ ms}$ | Gửi gói tin UDP OSC qua mạng LAN có dây |
| **Tổng thời gian triệt tiêu hú** | $< 150\text{ ms}$ | Thử nghiệm thực tế với mic và loa monitor thật |
| **Độ chính xác nhận diện hú (Recall)** | $\ge 98.0\%$ | Đánh giá trên 100 mẫu tiếng hú thực tế |
| **Tỷ lệ báo động giả (False Positive Rate)** | $< 0.5\%$ | Đánh giá trên 250 mẫu giọng hát ngân, guitar, cymbal |
| **Độ chính xác căn trễ (Time Alignment)** | $\le \pm 0.1\text{ ms}$ ($\approx \pm 3.4\text{cm}$) | Đối chiếu với khoảng cách đo bằng thước laser |

---

## 9. LỘ TRÌNH TRIỂN KHAI THEO MILESTONE (M0 – M8)

```
┌──────┐     ┌──────┐     ┌──────┐     ┌──────┐     ┌──────┐     ┌──────┐     ┌──────┐
│  M0  ├────►│  M1  ├────►│  M2  ├────►│  M3  ├────►│  M4  ├────►│  M5  ├────►│  M6  │
└──────┘     └──────┘     └──────┘     └──────┘     └──────┘     └──────┘     └──────┘
Protocol     Kết nối      Ghi PEQ      Thu Mic      Phân tích    Thử nghiệm   Auto EQ
& License    & Đọc Meter  & Mapper     & FFT        Feedback     Live XR18    & Phase
```

### Chi tiết Các Milestone Nghiệm thu:

- **M0 (Tuần 1): Protocol & License Compliance**
  - *Deliverable:* Kiến trúc khung dự án C++/Rust sạch bản quyền; bộ giải mã gói tin OSC cho XR18; tích hợp `pocketfft` (BSD) và `PortAudio` (MIT).
  - *Nghiệm thu:* Gửi gói tin `/xinfo` nhận diện chính xác model; SBOM không chứa mã nguồn GPL lây nhiễm.
- **M1 (Tuần 1): Kết nối Mixer, Quản lý Client & Đọc Meter Realtime**
  - *Deliverable:* Thread UDP duy trì heartbeat `/xremote` mỗi 8s; cơ chế kiểm tra giới hạn 4-client; hàm parse nhị phân `/meters/1` blob.
  - *Nghiệm thu:* Nhận diện meter 16 kênh ở tần suất $\ge 15\text{Hz}$ ($\le 66\text{ms}$); tự kết nối lại trong 3s khi tuột dây mạng.
- **M2 (Tuần 2): Module Ánh xạ Tham số Logarit & Ghi PEQ Xác minh**
  - *Deliverable:* Lớp `ParameterMapper` chuyển đổi 2 chiều giữa $\text{Hz}, \text{dB}, Q$ và `float [0.0, 1.0]`; module gửi lệnh PEQ có readback verify.
  - *Nghiệm thu:* Nhập $2500\text{Hz}$, gain $-12\text{dB} \rightarrow$ tính đúng giá trị chuẩn hóa $\rightarrow$ ghi vào mixer và đọc lại xác minh khớp 100% trong $< 10\text{ms}$.
- **M3 (Tuần 2): Thu Tín hiệu Microphone Đo lường**
  - *Deliverable:* Tích hợp PortAudio backend, thu tín hiệu 48kHz Float32 từ soundcard ngoài, hiển thị RTA thời gian thực.
  - *Nghiệm thu:* Thu âm liên tục không bị gián đoạn (zero dropout/xrun); RTA hiển thị mượt mà $\ge 30\text{ FPS}$.
- **M4 (Tuần 3): Thuật toán Phát hiện Hú Ngoại tuyến & Two-Factor Localizer**
  - *Deliverable:* Core thuật toán phát hiện hú 4 tầng kết hợp ma trận đối chiếu meter `/meters/1` và routing bus.
  - *Nghiệm thu:* Đạt độ chính xác $\ge 98\%$ trên tập mẫu hú; tỷ lệ báo nhầm $< 0.5\%$ trên tập mẫu nhạc cụ; chỉ đúng kênh mic phát sinh hú.
- **M5 (Tuần 4): Thử nghiệm Realtime Khép kín trên XR18 (MVP Ready)**
  - *Deliverable:* Vòng lặp tự động: Phát hiện hú $\rightarrow$ Safety Controller duyệt $\rightarrow$ gửi lệnh OSC hạ notch trên đúng Aux Bus của mixer thật.
  - *Nghiệm thu:* Triệt tiêu tiếng hú thực tế trên loa monitor sân khấu trong vòng $< 150\text{ms}$.
- **M6 (Tuần 5–6): Tích hợp Auto EQ Heuristic & Căn Pha Sub/Full**
  - *Deliverable:* Đo đạc đáp tuyến đa điểm, tối ưu hóa Heuristic Inversion với bộ tránh hố triệt tiêu; cân trễ Sub bằng GCC-PHAT.
  - *Nghiệm thu:* Đo và đề xuất delay sai số $\le \pm 0.1\text{ms}$; đáp tuyến loa phẳng hơn mà không bị boost hố triệt tiêu phòng.
- **M7 (Tuần 7): Mở rộng Hỗ trợ Đa Mixer (X32/M32 & Yamaha)**
  - *Deliverable:* Tích hợp driver OSC cho X32/M32 và driver SysEx cho Yamaha LS9/01V96i.
  - *Nghiệm thu:* Điều khiển thông suốt đồng thời 1 bàn Behringer X32 và 1 bàn Yamaha qua cùng giao diện phần mềm.
- **M8 (Tuần 8+): Prototype Phần cứng DSP cho Mixer Analog có Dập Nổ DC**
  - *Deliverable:* Bo mạch Raspberry Pi CM4 + Codec Audio HAT + Mạch Relay Fail-Safe kèm Photo-MOSFET soft-muting.
  - *Nghiệm thu:* Rút nguồn hộp DSP đột ngột, âm thanh analog tự động nối tắt thông mạch trong $< 3\text{ms}$, không có tiếng nổ bụp ra loa.

---

## 10. KẾ HOẠCH HÀNH ĐỘNG 2 TUẦN ĐẦU TIÊN (SPRINT 1 & SPRINT 2)

### Hướng dẫn Cấu hình Hạ tầng Mạng Kết nối Trực tiếp (Direct Cat5e Setup):
Khi cắm cáp mạng LAN trực tiếp từ máy tính sang mixer XR18 (không qua Router DHCP):
- **Cấu hình Static IP trên XR18:** Gạt công tắc mạng sang `Ethernet`. Dùng app X-Air-Edit tạm thời đặt IP tĩnh cho mixer: `192.168.1.100`, Subnet: `255.255.255.0`.
- **Cấu hình Static IP trên Laptop:** Cài đặt IP card mạng có dây của laptop: `192.168.1.50`, Subnet: `255.255.255.0`.
*(Quy trình này đảm bảo gói tin UDP truyền tức thì trong $< 1\text{ms}$, loại bỏ hoàn toàn hiện tượng rơi vào dải Auto-IP 169.254.x.x gây mất kết nối).*

---

### Sprint 1: Khởi tạo Khung Dự án & Kết nối Mixer Thật (Ngày 1 – Ngày 7)
- **Ngày 1:** Thiết lập repo Git, cấu trúc module chuẩn hóa; tích hợp `pocketfft` (BSD) và `PortAudio` (MIT).
- **Ngày 2:** Xây dựng module `XAirClient` quản lý socket UDP; viết parser phân giải gói tin OSC `/xinfo`; xây dựng lớp `ParameterMapper` chuẩn hóa logarit cho tần số và gain.
- **Ngày 3:** Thiết lập mạng LAN IP tĩnh (`192.168.1.x`); kết nối trực tiếp máy tính với bàn **Behringer XR18** thật qua cáp LAN; cài đặt thread gửi `/xremote` định kỳ 8s với cơ chế giám sát giới hạn 4-client.
- **Ngày 4:** Viết hàm giải mã nhị phân cho gói tin `/meters/1` blob; hiển thị mức tín hiệu 16 kênh đầu vào lên terminal theo thời gian thực.
- **Ngày 5:** Triển khai các lệnh ghi tham số PEQ: `/ch/01/eq/1/f`, `/g`, `/q`, `/on` thông qua `ParameterMapper`; đối chiếu tham số hiển thị với app X-Air-Edit chính hãng.
- **Ngày 6:** Xây dựng lớp `SafetyController` cài đặt giới hạn an toàn (Max boost $+4\text{dB}$, Rate limiter $\le 2\text{ lệnh/giây}$, Channel Whitelist check).
- **Ngày 7:** Chạy kiểm thử tự động kiểm tra vòng lặp kết nối $\rightarrow$ đọc meter $\rightarrow$ ghi 1 dải PEQ $\rightarrow$ đọc lại xác minh thành công 100%.

### Sprint 2: Xây dựng Module Thu Âm & Thuật toán Dò Hú Offline (Ngày 8 – Ngày 14)
- **Ngày 8:** Tích hợp PortAudio mở luồng thu âm 1 kênh từ soundcard đo lường; cố định buffer 1024 mẫu @ 48kHz không dropout.
- **Ngày 9:** Kết nối luồng âm thanh với `pocketfft`; cài đặt cửa sổ Hann và kỹ thuật chồng lấp 75%; hiển thị phổ RTA thời gian thực.
- **Ngày 10:** Triển khai Tầng 1 (Đỉnh phổ Prominence $\ge 12\text{dB}$) và Tầng 2 (Tốc độ bùng nổ Growth Rate $\ge 4\text{dB/frame}$).
- **Ngày 11:** Triển khai Tầng 3 (Đo phương sai vi phân pha Phase Coherence Variance) và Tầng 4 (Kiểm tra họa âm loại trừ nốt nhạc).
- **Ngày 12:** Tích hợp thuật toán **Two-Factor Localizer**: Khi phát hiện hú, tự động quét meter 16 kênh và routing table để định vị chính xác channel mic và Aux bus gây hú; kiểm thử trên bộ mẫu âm thanh offline.
- **Ngày 13:** Ghép nối hệ thống: Phát hiện hú $\rightarrow$ Safety Controller sinh Action Proposal $\rightarrow$ Kỹ sư bấm Spacebar $\rightarrow$ Bắn lệnh OSC hạ notch $-12\text{dB}$ trên đúng Aux bus của XR18 thật.
- **Ngày 14:** Sơ kết Sprint 1 & 2; nghiệm thu demo nội bộ khả năng phát hiện hú và tự động can thiệp đúng bus trên Behringer XR18 thật.

---

## 11. BẢN QUYẾT ĐỊNH CÔNG NGHỆ & DEFINITION OF DONE (DoD)

### 11.1 Bảng Quyết định Mã nguồn Cuối cùng (The Final Code Verdict)

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                               QUYẾT ĐỊNH CUỐI CÙNG VỀ MÃ NGUỒN                         │
├───────────────────────────────────┬────────────────────────────────────────────────────┤
│ [1] TÁI SỬ DỤNG TRỰC TIẾP         │ • PortAudio (MIT) - Thu âm soundcard/mic đa nền tảng│
│     (Direct Re-use)               │ • pocketfft (BSD-3) - Biến đổi nhanh Fourier (FFT) │
│                                   │ • kryops/remote-mixer (MIT) - Khung kết nối mixer  │
├───────────────────────────────────┼────────────────────────────────────────────────────┤
│ [2] TỰ VIẾT MỚI 100% (CLEAN-ROOM) │ • Feedback Detection Core (Peak + Growth + Phase)  │
│     (Proprietary In-House)        │ • Two-Factor Source Channel Localizer              │
│                                   │ • ParameterMapper (Behringer Logarithmic Math)     │
│                                   │ • Safety Controller & Rule Engine                  │
│                                   │ • Heuristic Inversion Auto EQ Engine               │
│                                   │ • GCC-PHAT Delay & Phase Alignment Engine          │
│                                   │ • Trình điều khiển OSC riêng cho XR18 / X32        │
├───────────────────────────────────┼────────────────────────────────────────────────────┤
│ [3] CHỈ DÙNG THAM KHẢO NGOẠI VI   │ • Open Sound Meter (GPLv3) - Công cụ đối chứng đo  │
│     (Reference / Benchmark Only)  │ • cirilln/AFS (No License) - Tài liệu lý thuyết NHS│
│                                   │ • REW (Freeware) - Tham khảo đường Target Curve    │
├───────────────────────────────────┼────────────────────────────────────────────────────┤
│ [4] TRÁNH TUYỆT ĐỐI (DO NOT USE)  │ • FFTW (GPLv2 / Dính bẫy phí $12,500)              │
│                                   │ • notameadow/xair-osc (Không có License = Vi phạm) │
│                                   │ • Web Audio API / Javascript cho Audio DSP         │
└───────────────────────────────────┴────────────────────────────────────────────────────┘
```

### 11.2 Tiêu chuẩn Hoàn thành của Bản MVP (Definition of Done - DoD)
Bản phát hành MVP được nghiệm thu đạt chuẩn khi đáp ứng đầy đủ 8 tiêu chí:
1. Kết nối ổn định liên tục $4\text{ giờ}$ với **Behringer XR18** thật qua cáp mạng LAN Ethernet cấu hình Static IP, không bị drop gói tin và tôn trọng giới hạn 4-client.
2. Đọc và phân giải luồng Meter 16 kênh với độ trễ phản hồi $\le 66\text{ms}$.
3. Bộ `ParameterMapper` chuyển đổi chính xác tần số và gain giữa số thực chuẩn hóa `[0.0, 1.0]` và giá trị thực tế $\text{Hz}, \text{dB}$.
4. Thu âm microphone đo lường qua soundcard ngoài với độ trễ FFT $\le 50\text{ms}$, hoàn toàn không có hiện tượng gián đoạn mẫu (zero xrun/dropout).
5. Phát hiện tiếng hú thực tế trên sân khấu thử nghiệm trong thời gian $\le 150\text{ms}$, định vị chính xác Kênh micro và Aux Monitor Bus phát sinh hú thông qua thuật toán Two-Factor Localizer.
6. Triệt tiêu dứt điểm tiếng hú sau khi chèn notch filter mà không làm sụt giảm âm lượng tổng thể của hệ thống; không can thiệp vào các kênh nằm trong Channel Whitelist.
7. Tỷ lệ nhận diện nhầm tiếng hát ca sĩ hoặc nhạc cụ ngân dài thành tiếng hú đạt mức $< 0.5\%$ trên tập mẫu kiểm thử.
8. Nút dừng khẩn cấp (**Panic / Bypass All**) và tính năng **Rollback Snapshot** khôi phục nguyên trạng mixer hoạt động trơn tru trong vòng dưới 1 giây.
9. Toàn bộ mã nguồn và dependencies được kiểm toán sạch sẽ $100\%$ bản quyền, không chứa bất kỳ thành phần GPL lây nhiễm nào trong binary thương mại đóng mã nguồn.
