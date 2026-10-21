# HƯỚNG DẪN KIỂM CHỨNG GIAO THỨC TRÊN PHẦN CỨNG THẬT
## Thiết bị: Behringer XR18 / XR12 / XR16 & Midas MR18 / MR12
**Mục tiêu:** Thu thập dữ liệu thực nghiệm để điền vào các thông số `[CẦN ĐO THẬT]` trong profile thiết bị.

---

## 1. CHUẨN BỊ THIẾT BỊ VÀ KẾT NỐI

### 1.1. Thiết bị cần có
1. Bàn mixer Behringer X-Air (XR18 / XR12 / XR16) hoặc Midas M-Air (MR18 / MR12).
2. Dây cáp mạng LAN Cat5e / Cat6 RJ45 chất lượng tốt.
3. Laptop cài đặt Python 3.11+ và repo `auto-sound`.
4. Phần mềm chính hãng **X-AIR Edit** trên laptop hoặc iPad để quan sát đối chiếu.

### 1.2. Thiết lập địa chỉ IP mạng có dây
1. **Trên mixer:**
   - Gạt công tắc mạng phía trước mixer về vị trí **ETHERNET** (không dùng Wi-Fi Access Point).
   - Mở X-AIR Edit -> Setup -> Network -> LAN: Chọn **DHCP** hoặc đặt **Static IP**:
     - IP: `192.168.1.100`
     - Subnet Mask: `255.255.255.0`
     - Gateway: `192.168.1.1`
2. **Trên laptop:**
   - Cắm dây mạng vào cổng Ethernet. Đặt IP tĩnh cho card mạng:
     - IP: `192.168.1.50`
     - Subnet Mask: `255.255.255.0`
3. **Kiểm tra ping:**
   ```bash
   ping 192.168.1.100
   # Đảm bảo ping phản hồi ổn định < 1ms
   ```

---

## 2. QUY TRÌNH THỰC HIỆN THĂM DÒ (HARDWARE PROBE)

### Bước 1: Chạy thử ở chế độ chỉ đọc (Dry-Read)
Để đảm bảo an toàn tuyệt đối, chạy lệnh probe ở chế độ không ghi:
```bash
.venv/bin/python tools/hw_probe.py --ip 192.168.1.100 --dry-read --output probe_dry_read.json
```
- Kiểm tra xem script có bắt tay `/xinfo` thành công không (hiển thị Model và Firmware version).

### Bước 2: Chạy thăm dò toàn diện (Ghi có phục hồi an toàn)
```bash
.venv/bin/python tools/hw_probe.py --ip 192.168.1.100 --target-ch 16 --target-band 4 --rtt-count 200 --output probe_xr18_lan.json
```
- **Kênh được chọn:** Kênh 16, Band 4 (kênh cuối, ít sử dụng nhất trong soundcheck).
- Script sẽ tự động:
  1. Đọc và sao lưu giá trị PEQ gốc của Kênh 16 Band 4.
  2. Đo giới hạn client `/xremote`.
  3. Đo độ trễ RTT khứ hồi 200 lần.
  4. Quét nấc lượng tử hóa của Gain, Q, Frequency.
  5. Thăm dò luồng phổ RTA 100-band.
  6. Đo thời gian echo của `/xremote`.
  7. Thăm dò giới hạn tốc độ truyền nhận lệnh.
  8. **Tự động khôi phục nguyên trạng tham số PEQ ban đầu.**

> **Lưu ý an toàn:** Nếu bạn bấm `Ctrl-C` bất cứ lúc nào, script sẽ tự động kích hoạt hàm khôi phục cài đặt gốc của mixer trước khi thoát.

---

## 3. BẢNG MẪU ĐIỀN KẾT QUẢ ĐO KIỂM THỰC TẾ

Sau khi chạy script, mở file `probe_xr18_lan.json` để lấy các số liệu điền vào bảng dưới đây và gửi lại cho nhóm phát triển:

| Thông số | Giả định hiện tại | Kết quả đo thực tế | Trạng thái xác minh | Ghi chú từ X-AIR Edit |
| :--- | :--- | :--- | :--- | :--- |
| **Model & Firmware** | XR18 firmware 1.18 | `....................` | Chờ đo | Đọc từ `/xinfo` |
| **Giới hạn Client /xremote** | Tối đa 4 client | `........ client` | Chờ đo | Thử mở 5 socket |
| **RTT Lệnh Ghi PEQ (LAN có dây)** | 50 – 100 ms | p50 = `...... ms`<br>p95 = `...... ms`<br>p99 = `...... ms` | Chờ đo | Thống kê trên 200 lần |
| **Tỷ lệ rớt gói UDP trên LAN** | 0.0% | `........ %` | Chờ đo | Số gói rớt trong 200 lần |
| **Số nấc Freq thực tế** | 201 bước (~67/decade) | `........ nấc` | Chờ đo | Quét 300 điểm |
| **Số nấc Gain thực tế** | 121 bước (~0.25 - 0.5dB) | `........ nấc` | Chờ đo | Quét 250 điểm |
| **Số nấc Q-factor thực tế** | 72 bước (0.3 - 10.0) | `........ nấc` | Chờ đo | Quét 150 điểm |
| **Định dạng RTA `/meters/4`** | Blob 204 bytes (100 short) | `........ bytes`<br>`........ bands` | Chờ đo | Có cần bật RTA trên app không? |
| **Tần suất cập nhật RTA** | ~50 ms (~20 FPS) | `........ ms/khung` | Chờ đo | Chu kỳ giữa các gói RTA |
| **Độ trễ echo `/xremote`** | < 50 ms | `........ ms` | Chờ đo | Thời gian echo phản hồi |
| **Tốc độ gửi tối đa an toàn** | $\le 2$ lệnh/giây | `........ lệnh/s` | Chờ đo | Mức bắt đầu rớt gói/lag mixer |

---

## 4. HƯỚNG DẪN CẬP NHẬT PROFILE THIẾT BỊ SAU KHI ĐO

Khi đã có file JSON kết quả đo:
1. Mở file profile tương ứng trong `device_profiles/` (ví dụ `xr18.toml`).
2. Điền các giá trị thực tế vào các trường `[CẦN ĐO THẬT]`.
3. Bổ sung trường xác thực:
   ```toml
   [validation]
   verified = true
   verified_date = "2026-10-21"
   firmware_version = "1.18"
   tester_name = "Tên Kỹ Sư / Soundman"
   connection_type = "Wired LAN Cat6"
   ```
4. Cập nhật `FakeXR18` trong `src/auto_sound/mixer/fake.py` để mô phỏng chính xác hành vi đo được từ phần cứng thật.
