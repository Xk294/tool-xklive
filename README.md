# Auto Sound Engineer (Pha 1 — Behringer XR18 / Midas MR18)

Hệ thống hỗ trợ kỹ sư âm thanh trực tiếp (Live Sound) tự động phát hiện hú (acoustic feedback) theo từng kênh micro qua cổng USB 18x18 và tự động đề xuất hoặc hạ notch PEQ trên mixer digital Behringer XR18 / Midas MR18 qua giao thức mạng OSC/UDP (cổng 10024).

---

## 1. Nguyên Tắc Cốt Lõi

1. **Tách biệt Audio Plane và Control Plane**: Âm thanh của buổi biểu diễn đi trực tiếp từ micro -> mixer -> loa FOH/Monitor, hoàn toàn KHÔNG đi qua laptop. Laptop chỉ thu tín hiệu qua đường USB 18x18 để phân tích DSP và gửi lệnh điều khiển tham số qua mạng LAN (OSC/UDP). Nếu laptop treo, phần mềm tắt hoặc đứt cáp USB, buổi diễn vẫn tiếp tục phát bình thường.
2. **Kỹ sư âm thanh luôn giữ quyền quyết định**: Hỗ trợ 3 chế độ vận hành: Tự động (`auto`), Bán tự động (`semi` — cảnh báo đỏ, chờ bấm Space để hạ), và Gợi ý (`manual`). Có phím tắt `[P]` (Panic) để lập tức thu hồi toàn bộ các notch về 0 dB chỉ trong 1 thao tác.
3. **Mọi lệnh mixer đều qua Bộ điều khiển An toàn (Safety Controller)**:
   - Rate limit tối đa 2 giao dịch/giây, tránh nghẽn buffer UDP và sập giao diện điều khiển của soundman (X-Air-Edit).
   - Cắt thăm dò an toàn: chớm hú chỉ hạ `-3.0 dB`, nếu hú dừng thì dừng hạ, nếu hú tiếp mới hạ thêm tối đa `-12.0 dB`. Tuyệt đối không bao giờ tăng gain quá `+4.0 dB`.
   - Giới hạn băng tần can thiệp: Chỉ sử dụng Band 3 và Band 4 của kênh đầu vào; tuyệt đối không can thiệp Band 1 và Band 2 (dành riêng cho soundman căn chỉnh tone giọng ca sĩ).
   - Whitelist bảo vệ kênh: Chỉ can thiệp 16 kênh micro đầu vào (`ch 1-16`), tuyệt đối không đụng vào kênh Aux/USB Return (`ch 17-18`).
   - Khóa an toàn khi chỉnh tay: Nếu soundman can thiệp thủ công vào PEQ trên mixer, hệ thống tự động khóa kênh đó 10 giây.
4. **100% Giấy phép nguồn mở tương thích thương mại**: Chỉ sử dụng các thư viện có giấy phép MIT, BSD, Apache-2.0, Unlicense. Không chứa bất kỳ dòng mã nguồn nào từ GPL/AGPL, FFTW hay các dự án không có license.

---

## 2. Cài Đặt Môi Trường

Yêu cầu hệ thống:
- Hệ điều hành: macOS hoặc Linux (khuyến nghị có hỗ trợ CoreAudio/ALSA)
- Python: Phiên bản `>= 3.11`
- Kết nối phần cứng: Cáp mạng LAN RJ45 Cat5e/Cat6 và cáp USB 2.0 Type-B nối với XR18.

### Các bước cài đặt:

```bash
# 1. Tạo môi trường ảo Python 3.11+
python3.11 -m venv .venv
source .venv/bin/activate

# 2. Cài đặt gói ở chế độ phát triển cùng toàn bộ dependency kiểm thử
pip install -e ".[dev]"

# 3. Kiểm tra tính hợp lệ của giấy phép bản quyền
pip-licenses
```

---

## 3. Chạy Kiểm Thử & Đo Lường (Testing & Benchmark)

Toàn bộ hệ thống được kiểm thử tự động với 47 kịch bản (46 passed, 1 skipped chờ tập dữ liệu thật Giai đoạn C), bao gồm Unit tests, Property-based testing (Hypothesis), kiểm tra Expected-Echo và Benchmark âm học:

```bash
# Chạy toàn bộ test suite
.venv/bin/pytest -v

# Chạy riêng bài kiểm thử Benchmark phát hiện hú và từ chối báo động giả
.venv/bin/pytest -v -s tests/test_detector_sim.py
```

### Kết quả Benchmark mô phỏng thực nghiệm (Synthetic Data):
> **Lưu ý:** Kết quả dưới đây được đo trên tín hiệu tổng hợp sinh bởi `sim/room.py`, chưa phải dữ liệu thu âm ngoài hiện trường thực tế.

- **Tổng số mẫu kiểm thử**: 40 bài test (20 bài hú thực tế ở các tần số 250Hz – 12kHz, 20 bài âm nhạc thực tế gồm vocal ngân có vibrato, vocal thẳng, guitar lead distortion, cymbal trống).
- **Độ nhạy phát hiện hú (Recall)**: `100.0%` (20/20 trường hợp) | Khoảng tin cậy Wilson 95%: `[83.9% - 100.0%]`.
- **Tỷ lệ báo động giả (False Positives)**: `0/20` (0 ca báo động giả trên tín hiệu mô phỏng) | Khoảng tin cậy Wilson 95%: `[0.0% - 16.1%]`.
- **Thời gian phát hiện trung thực**: `64.0 ms` (bao gồm cửa sổ Hann 2048 mẫu 42.6 ms và 3 frame tích lũy xác nhận, p50: 64.0 ms, p95: 64.0 ms, max: 64.0 ms).
- **Tập dữ liệu thực tế (Real Data)**: Tách riêng trong harness, chờ thu thập tối thiểu 100 mẫu hú và 250 mẫu âm nhạc thật ở Giai đoạn C.

---

## 4. Khởi Chạy Giao Diện & Mô Phỏng

### 🚀 Cách Mở Giao Diện Web Nhanh Nhất (1-Click Launcher):
Bạn có thể khởi động ngay giao diện đồ họa Nuxt 4 / Vue 3 với trình duyệt mặc định tự động mở:
```bash
# Cách 1: Chạy trực tiếp qua terminal (tự động bật mock mode nếu không cắm mixer)
./run_ui.py

# Cách 2: Trên macOS, nhấp đúp trực tiếp vào file run_ui.command trong thư mục dự án
```

### Chạy qua dòng lệnh chuyên sâu:
Chế độ mô phỏng cho phép thử nghiệm toàn bộ luồng hoạt động (sinh âm thanh ảo, mixer ảo `FakeXR18`, giao diện phím bấm) trực tiếp trên laptop mà **không cần mixer vật lý hay card âm thanh**:

```bash
.venv/bin/auto-sound --mock
```

Hoặc chạy ở chế độ bán tự động (cảnh báo đỏ khi có hú, chờ soundman xác nhận):

```bash
.venv/bin/auto-sound --mock --mode semi
```

Hoặc khởi chạy kèm **Web Companion UI (Nuxt 4 / Vue 3)** trên trình duyệt:

```bash
.venv/bin/auto-sound --mock --web
# Mở trình duyệt tại: http://127.0.0.1:8000
```

Nếu muốn kết nối từ iPad / điện thoại cùng mạng LAN:
```bash
.venv/bin/auto-sound --web --listen-lan
# Nhập mã PIN 4 chữ số hiển thị trên terminal để xác thực thiết bị
```

### Các phím thao tác trong CLI / Web Companion:
- `[SPACE]` (Dấu cách): Phê duyệt lệnh hạ notch đang chờ (trong chế độ `semi`).
- `[P]` hoặc `[ESC]`: **GIANT PANIC BUTTON** — Lập tức hoàn tác, trả toàn bộ notch tự động về 0 dB.
- `[Q]`: Thoát chương trình sạch sẽ, tự động ngắt kết nối an toàn.

---

## 5. Hướng Dẫn Vận Hành Với Bàn Behringer XR18 / Midas MR18 Thật

### Bước 1: Cấu hình mạng LAN IP tĩnh trực tiếp (Khuyến nghị số 1 cho Show Live)

Nên nối trực tiếp cáp mạng RJ45 từ cổng Ethernet của laptop vào cổng Ethernet của XR18 (hoặc qua switch mạng có dây chất lượng tốt). Tránh dùng Wi-Fi tích hợp của XR18 trong không gian đông người do băng tần 2.4GHz rất dễ bị nhiễu.

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

Chạy ở chế độ tự động can thiệp an toàn:
```bash
.venv/bin/auto-sound --profile device_profiles/xr18.toml --mode auto
```

Chạy ở chế độ bán tự động (khuyến nghị cho các show đầu tiên để soundman làm quen):
```bash
.venv/bin/auto-sound --profile device_profiles/xr18.toml --mode semi
```

---

## 6. Hướng Dẫn Vận Hành Với Behringer XR12 / XR16 / Midas MR12 (Chế Độ RTA Mạng LAN — THỬ NGHIỆM)

> **CẢNH BÁO THỬ NGHIỆM:** XR12, XR16 và MR12 **không có card USB audio 18x18 đa kênh**, nên hệ thống sử dụng chế độ RTA qua Mạng LAN mang tính chất **THỬ NGHIỆM**, không cam kết triệt tiêu hú tuyệt đối:
> - **Giới hạn độ phân giải**: Phổ RTA 100-band trên dải 20Hz – 20kHz có độ phân giải khoảng 1/10 octave mỗi band (kém chi tiết hơn nhiều so với FFT 2048 bin ~23.4Hz).
> - **Giới hạn can thiệp**: Luồng RTA phản ánh âm thanh tổng (Main L/R), không thể định vị micro cá nhân nào gây hú, do đó chỉ có thể hạ notch bảo vệ trên **Main Stereo L/R**.
> - **Độ trễ**: Gói tin `/meters/4` cập nhật chu kỳ ~50ms, cần ít nhất 3 frame liên tiếp (>= 150ms) để xác nhận chớm hú. Khuyến nghị chạy ở chế độ bán tự động (`semi`).

- **Kết nối phần cứng**: Cáp mạng LAN RJ45 từ Laptop vào XR12/XR16 (hoặc qua Wi-Fi nội bộ có router riêng).
- **Cơ chế**: Mixer gửi luồng phổ **RTA 100-band** (`/meters/4`) về Laptop qua UDP. Thuật toán `RTADetector` quét tìm đỉnh hú trên đường tổng và đề xuất/hạ notch PEQ trên **Main Stereo L/R** (dùng Band 3, 4, 5, 6 — giữ Band 1 & 2 cho Soundman tinh chỉnh âm sắc FOH).

### Lệnh khởi chạy:
```bash
# Dành cho Behringer XR12
.venv/bin/auto-sound --profile device_profiles/xr12.toml --mode auto

# Dành cho Behringer XR16
.venv/bin/auto-sound --profile device_profiles/xr16.toml --mode auto

# Dành cho Midas MR12
.venv/bin/auto-sound --profile device_profiles/mr12.toml --mode auto
```

---

## 7. Giới Hạn Đã Biết & Danh Sách Điểm `[CẦN ĐO THẬT]`

Các thông số dưới đây được xây dựng dựa trên tài liệu giao thức OSC X-Air chính hãng và kỹ thuật dịch ngược cộng đồng. Khi triển khai trên thiết bị XR18 vật lý tại hiện trường, cần đo đạc và hiệu chỉnh thực tế:

| Thành phần | Thông số trong profile | Ý nghĩa kỹ thuật | Trạng thái kiểm chứng |
| :--- | :--- | :--- | :--- |
| **Max Clients OSC** | `max_clients = 4` | XR18/XR12/XR16 giới hạn tối đa 4 client duy trì đăng ký `/xremote` đồng thời. Nếu có nhiều hơn 4 thiết bị (iPad, laptop, điện thoại), client thứ 5 sẽ bị từ chối hoặc đẩy văng. | `[CẦN ĐO THẬT]` trên firmware mới nhất |
| **Độ trễ phản hồi OSC** | `probe_wait_ms = 80` | Thời gian chờ từ lúc laptop gửi lệnh UDP đổi PEQ đến khi mixer áp dụng vào DSP và phản hồi trạng thái. Dao động trong khoảng 50–100ms. | `[CẦN ĐO THẬT]` với ping mạng thực tế |
| **Bước lượng tử hóa Freq** | `freq_steps = 201` | Mixer XR18/XR12 biểu diễn tần số qua số thực `[0.0, 1.0]` với khoảng 201 nấc logarit (khoảng 67 nấc mỗi decade trên 3 decade 20Hz-20kHz). | `[CẦN ĐO THẬT]` độ phân giải bước nhảy |
| **Bước lượng tử hóa Gain** | `gain_steps = 121` | Thang gain từ -15dB đến +15dB trên XR18 chia làm khoảng 121 nấc (bước nhảy ~0.25dB - 0.5dB). | `[CẦN ĐO THẬT]` phản hồi từ X-AIR Edit |
| **Bước lượng tử hóa Q** | `q_steps = 72` | Thang Q từ 0.3 đến 10.0 chia làm 72 nấc logarit theo chuẩn X32/X-Air. | `[CẦN ĐO THẬT]` |
| **Giới hạn độ dốc PEQ** | `q_max = 10.0` | XR series sử dụng PEQ thông thường, giá trị Q cực đại là `10.0` (độ rộng ~1/7 octave). Bàn KHÔNG hỗ trợ notch filter siêu hẹp Q=60 như thiết bị chuyên dụng dbx AFS2. | Đã xác thực theo kiến trúc DSP XR18 |
| **Band PEQ khả dụng (Channel)** | `auto_notch_bands = [3, 4]` | Mỗi kênh mic đầu vào chỉ có 4 band PEQ. Hệ thống chỉ cho phép dùng Band 3 & 4 làm notch chống hú tự động để bảo toàn Band 1 & 2 cho kỹ sư âm thanh. | Thiết kế chuẩn mực cho show thật |
| **Band PEQ khả dụng (Main LR)** | `main_auto_notch_bands = [3, 4, 5, 6]` | Main Stereo Out trên XR12/XR16/XR18 có 6 band PEQ. Chế độ RTA mạng LAN sử dụng Band 3-6 để dập hú FOH, giữ Band 1 & 2 cho Soundman. | Đã kiểm chứng trên giao thức OSC |
| **Số band PEQ trên Bus** | `bus_auto_notch_bands = [5, 6]` | Bus Out trên XR series có 6 band PEQ. Khi mở rộng can thiệp bus, chỉ dùng Band 5 & 6. | `[CẦN ĐO THẬT]` trên firmware thực tế |
