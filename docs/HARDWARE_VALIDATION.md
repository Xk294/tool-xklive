# HƯỚNG DẪN KIỂM CHỨNG GIAO THỨC TRÊN PHẦN CỨNG THẬT
## Thiết bị: Behringer XR18 / XR12 / XR16 & Midas MR18 / MR12
**Mục tiêu:** Thu thập dữ liệu thực nghiệm để điền vào các thông số `[NEEDS HARDWARE VERIFICATION]` trong profile thiết bị.

---

## 1. CHUẨN BỊ THIẾT BỊ VÀ KẾT NỐI

### 1.1. Thiết bị cần có
1. Bàn mixer Behringer X-Air (XR18 / XR12 / XR16) hoặc Midas M-Air (MR18 / MR12).
2. Dây cáp mạng LAN Cat5e / Cat6 RJ45 chất lượng tốt.
3. Laptop cài Rust toolchain, Node.js và repo này (chạy bằng `npm run dev`).
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

> **Chưa có công cụ probe tự động.** Bảng đo ở mục 3 hiện được thực hiện thông qua phần mềm X-AIR Edit kết hợp màn hình Diagnostics và bảng Cắt Notch Thủ Công của ứng dụng Tauri.

Các phép đo cần thực hiện (giữ nguyên thang đo của quy trình cũ):
1. Handshake `/xinfo` (model, firmware), chạy ở chế độ chỉ đọc trước.
2. Giới hạn client `/xremote`.
3. RTT khứ hồi 200 lần trên Kênh 16, Band 4 (kênh cuối, ít dùng nhất).
4. Nấc lượng tử hóa của Gain, Q, Frequency.
5. Luồng phổ RTA 100-band và tần suất cập nhật.
6. Thời gian echo của `/xremote`.
7. Giới hạn tốc độ gửi lệnh.
8. Sao lưu PEQ gốc trước khi ghi và khôi phục nguyên trạng sau khi đo.

---

## 3. BẢNG MẪU ĐIỀN KẾT QUẢ ĐO KIỂM THỰC TẾ

Sau khi đo, điền số liệu vào bảng dưới đây và gửi lại cho nhóm phát triển:

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

Khi đã có kết quả đo:
1. Mở file profile tương ứng trong `device_profiles/` (ví dụ `xr18.toml`).
2. Điền các giá trị thực tế vào các trường `[NEEDS HARDWARE VERIFICATION]`.
3. Bổ sung trường xác thực:
   ```toml
   [validation]
   verified = true
   verified_date = "2026-10-21"
   firmware_version = "1.18"
   tester_name = "Tên Kỹ Sư / Soundman"
   connection_type = "Wired LAN Cat6"
   ```
4. Cập nhật test mô phỏng trong `src-tauri/src/mixer/` (hiện chưa có mixer giả) để phản ánh hành vi đo được từ phần cứng thật.
