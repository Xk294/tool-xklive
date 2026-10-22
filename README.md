# Auto Sound Engineer (Behringer X-Air & Midas M-Air)

Hệ thống hỗ trợ kỹ sư âm thanh trực tiếp (Live Sound) tự động phát hiện hú (acoustic feedback) và can thiệp notch PEQ trực tiếp trên dòng mixer digital Behringer X-Air (XR12, XR16, XR18) & Midas M-Air (MR12, MR18) qua giao thức mạng OSC/UDP (cổng 10024) kết hợp giao diện Web Companion hiện đại (Nuxt 4 / Vue 3).

---

## 1. Nguyên Tắc Cốt Lõi

1. **Tách biệt tuyệt đối Audio Plane và Control Plane**:
   - Âm thanh của buổi biểu diễn đi trực tiếp từ micro -> mixer -> loa FOH/Monitor, hoàn toàn **KHÔNG đi qua laptop**.
   - Laptop chỉ thu bản sao tín hiệu (qua cổng USB 18x18 đối với XR18/MR18, hoặc qua gói tin phổ RTA 100-band đối với XR12/XR16/MR12) để phân tích DSP và gửi lệnh điều khiển PEQ qua mạng LAN (OSC/UDP).
   - **Cam kết an toàn**: Nếu laptop treo, phần mềm tắt hoặc đứt cáp USB, buổi diễn vẫn tiếp tục phát 100% bình thường, không bao giờ làm gián đoạn chương trình.

2. **Kỹ sư âm thanh (Soundman) luôn giữ quyền quyết định**:
   - Hỗ trợ 3 chế độ vận hành: Tự động (`auto`), Bán tự động (`semi` — cảnh báo đỏ, chờ Soundman bấm Space hoặc bấm Approve trên Web để hạ notch), và Gợi ý (`manual`).
   - Có nút **PANIC** (phím tắt `[P]` trên CLI hoặc nút đỏ khẩn cấp trên Web Companion): Lập tức hoàn tác, trả toàn bộ các notch hệ thống về 0 dB chỉ trong 1 thao tác.

3. **Can thiệp Mixer An toàn & Tương tác Trực tiếp (Direct Interfacing)**:
   - **Tự động quét mạng (Auto-Discovery)**: Quét UDP broadcast `/xinfo` port 10024 để tìm mixer Behringer/Midas trên LAN không cần gán cứng IP.
   - **Đồng bộ Metadata thời gian thực**: Lấy tên kênh show (*Lead Vox, MC, Guitar...*), mã màu, trạng thái MUTE và Master EQ trực tiếp từ mixer.
   - **Mute-Aware DSP Skip**: Tự động bỏ qua phân tích các micro đang bị MUTE trên bàn mixer để triệt tiêu hoàn toàn báo động giả.
   - **Đảm bảo hiệu lực PEQ (Direct PEQ Enforcement)**: Hàm `set_peq()` tự động bật Master EQ kênh (`/eq/on = 1`) và ép loại Band về Parametric EQ (`type = 2`), chống tình trạng notch bị vô hiệu hoặc méo dải cao từ preset cũ.
   - **Cơ chế Expected-Echo**: Phân biệt chính xác giữa phản hồi của lệnh hệ thống ghi với thao tác vặn tay thực tế của soundman trên iPad/bàn mixer.
   - **Rate limit**: Tối đa 2 giao dịch/giây, tránh nghẽn buffer UDP và sập giao diện điều khiển X-Air-Edit.
   - **Cắt thăm dò vi phân**: Chớm hú hạ `-3.0 dB`, nếu hú tiếp tục mới hạ dần tới tối đa `-12.0 dB`. Tuyệt đối không bao giờ tăng gain quá `+4.0 dB`.
   - **Bảo toàn dải tần soundman**: Trên micro chỉ can thiệp Band 3 & 4 (giữ Band 1 & 2 cho Soundman căn tone giọng ca sĩ); trên Main L/R chỉ can thiệp Band 3, 4, 5, 6.
   - **Khóa an toàn khi chỉnh tay (Manual Override Lock)**: Nếu soundman tự vặn núm EQ trên iPad hoặc mixer, hệ thống tự động khóa can thiệp trên kênh đó 10 giây.
   - **Two-Factor Localizer**: Giải quyết hiện tượng crosstalk khi nhiều mic cùng bắt tiếng hú dựa trên ma trận phổ và routing Bus.
   - **Auto-Release & Reclaiming**: Tự động thu hồi notch nông nhất khi cạn band PEQ và từ từ nhả gain notch về 0 dB khi âm trường ổn định.

4. **100% Giấy phép nguồn mở tương thích thương mại**:
   - Sử dụng các thư viện có giấy phép MIT, BSD, Apache-2.0, Unlicense.
   - Tuyệt đối không chứa mã nguồn GPL/AGPL hay FFTW để đảm bảo an toàn pháp lý cho việc triển khai thương mại.

---

## 2. Cài Đặt Môi Trường

Yêu cầu hệ thống:
- Hệ điều hành: macOS hoặc Linux (khuyến nghị có hỗ trợ CoreAudio/ALSA)
- Python: Phiên bản `>= 3.11`
- Kết nối phần cứng: Cáp mạng LAN RJ45 Cat5e/Cat6 và cáp USB 2.0 Type-B nối với XR18 (hoặc cáp mạng LAN cho XR12/XR16).
- Giao diện Web: Bản dựng tĩnh Nuxt 4 / Vue 3 đã được biên dịch sẵn trong `src/auto_sound/web/dist/`, **không bắt buộc phải cài đặt Node.js/npm** khi chạy.

### Các bước cài đặt:

```bash
# 1. Tạo môi trường ảo Python 3.11+
python3.11 -m venv .venv
source .venv/bin/activate

# 2. Cài đặt gói ở chế độ phát triển cùng toàn bộ dependency
pip install -e ".[dev]"

# 3. Kiểm tra tính hợp lệ của giấy phép bản quyền
pip-licenses
```

*(Nếu muốn tùy biến mã nguồn giao diện Nuxt 4: vào thư mục `frontend/`, chạy `npm install` và `npm run generate` để xuất bản sang `src/auto_sound/web/dist/`).*

---

## 3. Chạy Kiểm Thử Tự Động (Testing Suite)

Toàn bộ hệ thống được kiểm thử tự động với **70 kịch bản** (69 passed, 1 skipped chờ tập dữ liệu show diễn thực tế), bao gồm Unit tests, Property-based testing (Hypothesis), kiểm tra Expected-Echo, Web Companion API và Benchmark âm học:

```bash
# Chạy toàn bộ test suite
.venv/bin/pytest -v

# Chạy riêng bài kiểm thử Benchmark phát hiện hú và từ chối báo động giả
.venv/bin/pytest -v -s tests/test_detector_sim.py
```

### Kết quả Benchmark mô phỏng thực nghiệm (Synthetic Data):
- **Độ nhạy phát hiện hú (Recall)**: `100.0%` (20/20 trường hợp) | Khoảng tin cậy Wilson 95%: `[83.9% - 100.0%]`.
- **Tỷ lệ báo động giả (False Positives)**: `0/20` (0 ca báo động giả trên tín hiệu mô phỏng) | Khoảng tin cậy Wilson 95%: `[0.0% - 16.1%]`.
- **Thời gian phát hiện trung thực**: `64.0 ms` (bao gồm cửa sổ Hann 2048 mẫu 42.6 ms và 3 frame tích lũy xác nhận, p50: 64.0 ms, p95: 64.0 ms, max: 64.0 ms).

---

## 4. Khởi Chạy Giao Diện & Vận Hành

### 🚀 Khởi động 1 chạm với Giao diện Web Companion (Khuyên dùng):
Chạy lệnh khởi chạy trực quan:
```bash
python3 run_ui.py
```
- Trình khởi chạy sẽ tự động phát sóng UDP broadcast `/xinfo` để tìm mixer X-Air trên mạng LAN.
- Nếu tìm thấy mixer (ví dụ `192.168.1.100`), hệ thống tự động kết nối và mở giao diện Web tại `http://localhost:8000`.
- Nếu không tìm thấy phần cứng, hệ thống tự động chuyển sang chế độ mô phỏng `--mock` để Soundman làm quen giao diện.

### Khởi chạy qua dòng lệnh chuyên sâu (CLI):

#### 1. Chế độ mô phỏng (Không cần mixer thật):
```bash
# Mở CLI mô phỏng
.venv/bin/auto-sound --mock --mode semi

# Mở Web Companion mô phỏng kèm giao diện trình duyệt
.venv/bin/auto-sound --mock --web --port 8000
```

#### 2. Kết nối từ xa qua iPad / Điện thoại trong mạng LAN:
```bash
.venv/bin/auto-sound --web --listen-lan --port 8000
# Nhập mã PIN 4 chữ số hiển thị trên terminal để xác thực thiết bị kết nối
```

### Các phím thao tác trong CLI / Web Companion:
- `[SPACE]` (Dấu cách) hoặc nút `Approve`: Phê duyệt lệnh hạ notch đang chờ (trong chế độ `semi`).
- `[P]` hoặc nút `PANIC`: **GIANT PANIC BUTTON** — Lập tức hoàn tác, trả toàn bộ notch tự động về 0 dB.
- `[Q]`: Thoát chương trình sạch sẽ, tự động ngắt kết nối an toàn.

---

## 5. Hướng Dẫn Vận Hành Với Bàn Behringer XR18 / Midas MR18 Thật

### Bước 1: Cấu hình mạng LAN IP tĩnh trực tiếp (Khuyến nghị cho Show Live)
Nối trực tiếp cáp mạng RJ45 từ cổng Ethernet của laptop vào cổng Ethernet của XR18 (hoặc qua switch mạng có dây chất lượng tốt). Tránh dùng Wi-Fi tích hợp của XR18 trong không gian đông người do băng tần 2.4GHz rất dễ bị nhiễu.

Thiết lập IP tĩnh cho card mạng LAN của Laptop:
- **IP Laptop**: `192.168.1.50`
- **Subnet Mask**: `255.255.255.0`
- **Gateway**: để trống (hoặc `192.168.1.1`)

Thiết lập IP tĩnh trên bàn XR18 (thông qua ứng dụng X-AIR Edit -> Setup -> Network -> LAN -> Static):
- **IP XR18**: `192.168.1.100`
- **Subnet Mask**: `255.255.255.0`
- **Gateway**: `192.168.1.1`
- **Cổng OSC UDP**: `10024` (mặc định của X-Air)

### Bước 2: Kết nối USB Audio 18x18
1. Cắm cáp USB 2.0 từ cổng USB B của XR18 vào laptop.
2. Trên phần mềm X-Air Edit: Vào mục `In/Out` -> `USB Sends`: Đảm bảo 16 kênh đầu vào micro được định tuyến gửi tín hiệu `Direct Out` (tiền gain/pre-DSP) lên 16 kênh USB Send tương ứng.

### Bước 3: Khởi chạy phần mềm Auto Sound
Quét tìm mixer X-Air tự động trong mạng LAN:
```bash
.venv/bin/auto-sound --discover
```

Khởi chạy với tự động dò tìm IP mixer và bật Web Companion:
```bash
.venv/bin/auto-sound --ip auto --mode semi --web --port 8000
```

Hoặc chỉ định rõ file profile:
```bash
.venv/bin/auto-sound --profile device_profiles/xr18.toml --ip 192.168.1.100 --mode semi --web
```

---

## 6. Hướng Dẫn Vận Hành Với Behringer XR12 / XR16 / Midas MR12 (Chế Độ RTA Mạng LAN)

> **LƯU Ý:** XR12, XR16 và MR12 không có card USB audio 18x18 đa kênh. Hệ thống tự động sử dụng luồng phổ RTA 100-band mạng LAN (`/meters/4`) để giám sát đường tổng và can thiệp PEQ trên **Main Stereo L/R**:
> - **Cơ chế**: Mixer gửi luồng phổ RTA 100-band về Laptop qua UDP. Thuật toán `RTADetector` quét tìm đỉnh hú trên đường tổng và hạ notch PEQ trên Main Stereo L/R (sử dụng Band 3, 4, 5, 6 — giữ Band 1 & 2 cho Soundman tinh chỉnh âm sắc FOH).
> - **Kết nối**: Cắm cáp mạng LAN từ Laptop vào XR12/XR16 (hoặc qua router Wi-Fi riêng).

### Lệnh khởi chạy:
```bash
# Tự động nhận diện model và kết nối
.venv/bin/auto-sound --ip auto --mode semi --web

# Hoặc chỉ định rõ profile thiết bị:
.venv/bin/auto-sound --profile device_profiles/xr12.toml --mode semi --web
.venv/bin/auto-sound --profile device_profiles/xr16.toml --mode semi --web
.venv/bin/auto-sound --profile device_profiles/mr12.toml --mode semi --web
```

---

## 7. Cấu Trúc Dự Án

```text
xklive/
├── pyproject.toml                      # Cấu hình dự án và dependencies
├── README.md                           # Sách hướng dẫn vận hành chi tiết
├── BAO_CAO_DU_AN.md                    # Báo cáo kỹ thuật tổng thể dự án
├── run_ui.py                           # 1-Click Launcher khởi chạy Web Companion
├── device_profiles/                    # Hồ sơ phần cứng (xr18, xr12, xr16, mr12)
├── frontend/                           # Giao diện Nuxt 4 / Vue 3 SPA + Tailwind CSS
├── src/auto_sound/
│   ├── core/models.py                  # Dataclass lõi hệ thống
│   ├── mixer/xair.py                   # X-Air Driver: Discovery, OSC, Metadata, PEQ Safety
│   ├── audio/ring_buffer.py            # SPSC Ring Buffer 18 kênh zero-allocation
│   ├── audio/io.py                     # Thu âm USB PortAudio & Virtual Generator
│   ├── dsp/detector.py                 # Bộ dò hú FFT 2048 mẫu & Harmonic Rejection
│   ├── dsp/rta_detector.py             # Bộ dò hú phổ RTA 100-band cho XR12/XR16
│   ├── dsp/localizer.py                # Two-Factor Mic Localizer định vị micro hú
│   ├── safety/controller.py            # Safety Controller: Rate limit, Probe, Reclaim
│   ├── safety/snapshot.py              # Sao lưu và phục hồi Snapshot PEQ
│   ├── app/cli.py                      # Runtime điều phối toàn trình
│   ├── app/server.py                   # FastAPI REST API + WebSocket Server
│   └── web/dist/                       # Bản dựng tĩnh Nuxt 4 / Vue 3 SPA
└── tests/                              # 70 kịch bản kiểm thử tự động
```

---

## 8. Giấy Phép & Bản Quyền

Dự án phát hành theo giấy phép **MIT**. 100% các thành phần phụ thuộc đều tương thích thương mại tự do (MIT, BSD, Apache-2.0, Unlicense).
