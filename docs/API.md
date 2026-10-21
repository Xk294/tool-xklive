# Tài Liệu Đặc Tả Giao Thức API & WebSocket (Protocol Specification v1)

Hệ thống Auto Sound Engineer cung cấp giao diện lập trình ứng dụng REST và luồng dữ liệu thời gian thực hai chiều WebSocket (phiên bản `v1`).

---

## 1. Nguyên Tắc Thiết Kế & Bảo Mật LAN

1. **Mô hình kiến trúc Engine – UI độc lập:**
   - Tiến trình Engine xử lý DSP và Safety Controller chạy liên tục trong nền, hoàn toàn độc lập với việc có trình duyệt nào đang kết nối hay không.
   - Trình duyệt/iPad chỉ là giao diện hiển thị (View) và gửi ý định điều khiển (Intent). Mọi lệnh từ UI đều bắt buộc đi qua Safety Controller trước khi gửi tới mixer.
2. **Không kết nối Internet:**
   - 100% tài nguyên giao diện được phục vụ cục bộ từ máy tính chạy engine, **không sử dụng bất kỳ liên kết CDN bên ngoài nào**.
3. **Bảo mật mạng LAN (`--listen-lan`):**
   - Mặc định server chỉ bind địa chỉ loopback nội bộ `127.0.0.1:8000`.
   - Khi chạy với cờ `--listen-lan` (để kết nối từ iPad/điện thoại trong mạng LAN), hệ thống sinh một mã PIN ngẫu nhiên 4 chữ số hiển thị trên màn hình máy tính chủ.
   - Client phải thực hiện bắt tay tại endpoint `/api/v1/pair/verify` để nhận `pairing_token`.
   - Mọi yêu cầu ghi dữ liệu (POST, PUT, DELETE) từ client chưa ghép nối hợp lệ sẽ bị từ chối với mã lỗi `401 Unauthorized`.
   - Toàn bộ lệnh gửi đến server đều được ghi log kèm địa chỉ IP của client.

---

## 2. Các Endpoint REST API (`/api/v1`)

### 2.1. Trạng Thái Hệ Thống
- **`GET /api/v1/status`**
  - **Mô tả:** Lấy thông tin trạng thái hoạt động hiện tại của engine và mixer.
  - **Phản hồi mẫu (200 OK):**
    ```json
    {
      "mixer_state": "CONNECTED",
      "model": "XR18",
      "firmware": "1.18",
      "mode": "auto",
      "lan_rta_mode": false,
      "latency_ms": 64.0,
      "xruns": 0,
      "reconnect_count": 0,
      "uptime_s": 1420.5,
      "active_notches_count": 2,
      "pending_proposals_count": 0,
      "is_lan_locked": false
    }
    ```

### 2.2. Chế Độ Vận Hành
- **`POST /api/v1/mode`**
  - **Mô tả:** Thay đổi chế độ (`auto`, `semi`, `manual`). Khi chuyển từ `manual`/`semi` lên `auto`, bắt buộc phải có cờ `confirm: true`.
  - **Yêu cầu (Body JSON):**
    ```json
    {
      "mode": "auto",
      "confirm": true
    }
    ```
  - **Phản hồi mẫu (200 OK):**
    ```json
    {
      "success": true,
      "current_mode": "auto",
      "message": "Đã chuyển sang chế độ tự động can thiệp"
    }
    ```

### 2.3. Hàng Đợi Đề Xuất (Chế độ `semi`)
- **`GET /api/v1/proposals`**
  - **Mô tả:** Lấy danh sách các đề xuất hạ notch đang chờ duyệt.
  - **Phản hồi mẫu (200 OK):**
    ```json
    {
      "proposals": [
        {
          "id": "prop_101",
          "channel": 1,
          "bus": null,
          "target": "ch",
          "freq_hz": 3150.0,
          "gain_db": -3.0,
          "q": 8.0,
          "confidence_score": 0.82,
          "created_at": 1729480000.12,
          "ttl_remaining_s": 15.4,
          "reason": "Phát hiện hú 3150.0 Hz"
        }
      ]
    }
    ```

- **`POST /api/v1/proposals/{id}/approve`**
  - **Mô tả:** Kỹ sư âm thanh duyệt áp dụng đề xuất. Lệnh được đẩy ngay vào Safety Controller.
- **`POST /api/v1/proposals/{id}/reject`**
  - **Mô tả:** Kỹ sư từ chối đề xuất. Đề xuất bị xóa khỏi hàng đợi.
- **`POST /api/v1/proposals/{id}/snooze`**
  - **Mô tả:** Tạm thời bỏ qua kênh này trong 60 giây (tương đương khóa tạm thời kênh).

### 2.4. Danh Sách Notch Đang Hoạt Động
- **`GET /api/v1/notches`**
  - **Mô tả:** Lấy danh sách toàn bộ các notch đang cắt trên mixer.
  - **Phản hồi mẫu (200 OK):**
    ```json
    {
      "notches": [
        {
          "channel": 1,
          "bus": null,
          "band": 3,
          "freq_hz": 3150.0,
          "gain_db": -6.0,
          "q": 8.0,
          "target": "ch",
          "age_s": 42.5,
          "is_locked": false,
          "step_count": 2,
          "remaining_bands_on_target": 1
        }
      ]
    }
    ```

- **`POST /api/v1/notches/release`**
  - **Mô tả:** Nhả một notch cụ thể hoặc toàn bộ về 0 dB.
  - **Yêu cầu (Body JSON):**
    ```json
    {
      "channel": 1,
      "band": 3,
      "target": "ch"
    }
    ```
- **`POST /api/v1/notches/lock`**
  - **Mô tả:** Khóa cố định một notch (không tự động nhả bằng auto-release, dùng cho soundcheck).

### 2.5. Nút Khẩn Cấp PANIC & Hoàn Tác
- **`POST /api/v1/panic`**
  - **Mô tả:** **KHẨN CẤP** - Nhả toàn bộ các notch hệ thống về 0 dB ngay lập tức trong 1 thao tác duy nhất.
  - **Phản hồi mẫu (200 OK):**
    ```json
    {
      "success": true,
      "released_count": 2,
      "message": "Đã thực thi PANIC: Hoàn tác toàn bộ notch về 0 dB"
    }
    ```

- **`POST /api/v1/panic/undo`**
  - **Mô tả:** Khôi phục lại trạng thái các notch trước khi bấm PANIC (nếu bấm nhầm).

### 2.6. Đồng Hồ Mức Tín Hiệu (Meters)
- **`GET /api/v1/meters`**
  - **Mô tả:** Đọc mức tín hiệu 18 kênh, trạng thái mute, trạng thái khóa tay và cảnh báo hú.

### 2.7. Snapshot & Rollback
- **`POST /api/v1/snapshot/take`**
  - **Mô tả:** Chụp lại toàn bộ trạng thái PEQ trước show.
- **`POST /api/v1/snapshot/rollback`**
  - **Mô tả:** Khôi phục toàn bộ PEQ về bản chụp snapshot trong thời gian < 1.0 giây.

### 2.8. Ghép Nối Thiết Bị LAN (Pairing)
- **`GET /api/v1/pair/pin`** (Chỉ khả dụng trên localhost)
  - **Mô tả:** Lấy mã PIN đang hiển thị.
- **`POST /api/v1/pair/verify`**
  - **Mô tả:** Gửi mã PIN để nhận `pairing_token` phục vụ các thao tác ghi.
  - **Yêu cầu (Body JSON):**
    ```json
    {
      "pin": "1234"
    }
    ```

---

## 3. Giao Thức WebSocket (`/ws`)

### 3.1. Kết Nối & Xác Thực
- Địa chỉ: `ws://<server_ip>:8000/ws` (hoặc `ws://<server_ip>:8000/ws?token=<token>`).
- Ngay khi kết nối thành công, Server gửi ngay một gói tin loại `state_snapshot`:
  ```json
  {
    "type": "state_snapshot",
    "timestamp": 1729480000.5,
    "status": { ... },
    "notches": [ ... ],
    "proposals": [ ... ],
    "meters": [ -60.0, -24.5, ... ]
  }
  ```

### 3.2. Các Gói Tin Phát Sóng (Server Broadcast)
1. **`proposal_added`:** Có đề xuất mới được sinh ra từ detector.
2. **`proposal_resolved`:** Đề xuất được duyệt, từ chối hoặc tự hết hạn.
3. **`notch_updated`:** Trạng thái danh sách notch thay đổi (cắt mới, nhả bước, nhả hết).
4. **`panic_event`:** Sự kiện Panic vừa được kích hoạt.
5. **`meter_frame`:** Mức âm lượng 18 kênh (cập nhật ~10 FPS).
6. **`rta_frame`:** Khung phổ năng lượng RTA 100-band hoặc FFT log-scale (~20-25 FPS).

### 3.3. Lệnh Gửi Từ Client Qua WebSocket (Client Message)
Client có thể gửi các lệnh JSON trực tiếp:
```json
{
  "action": "approve_proposal",
  "proposal_id": "prop_101",
  "token": "secret_token_if_lan"
}
```
hoặc:
```json
{
  "action": "panic",
  "token": "secret_token_if_lan"
}
```
