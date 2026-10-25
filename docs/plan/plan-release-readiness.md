# PLAN — Release Readiness (bản trả phí ~500k, phân phối qua xkproduction)

Mục tiêu: biến dự án từ "đã test trong mô phỏng" thành sản phẩm bán được, có bằng chứng chạy thật với mixer, có trial + license, hỗ trợ thêm X32/M32.

## 0. Hiện trạng đã xác minh (2026-10-24)

- Mã nguồn đang sống là Rust/Tauri: `src-tauri/src/{audio,core,dsp,mixer}`, `commands.rs`, `state.rs`. Mixer chỉ có `mixer/xair.rs` và `mixer/mapper.rs`.
- `BAO_CAO_DU_AN.md` đã đồng bộ sang kiến trúc Rust/Tauri v0.2.0 (`32 passed, 0 failed` qua `cargo test`).
- `soak_report_mock.json`: đã gắn nhãn rõ `mock_mode: true` (10 giây mô phỏng) — chưa phải soak phần cứng thật.
- Không có X32/M32 và không có license/trial trong `src-tauri/src` (grep không ra kết quả).
- Báo cáo ghi nhận rõ: chưa kiểm chứng RTT/jitter UDP thật, USB 18x18 chạy dài giờ, benchmark dữ liệu âm thanh thật trên bàn mixer vật lý.

## 1. Giai đoạn A — Làm sạch sự thật (ĐÃ HOÀN TẤT)

| # | Việc | Tiêu chí xong |
| :--- | :--- | :--- |
| A1 | Xác định bản chính: Rust/Tauri (`v0.2.0`). Lưu kế hoạch đã xong vào `docs/plan/done/` | Một stack duy nhất trong `CLAUDE.md`, README, báo cáo |
| A2 | Chạy `cargo test`, ghi số test thật (`32 passed, 0 failed`) | Một con số duy nhất, kèm lệnh và ngày chạy |
| A3 | Viết lại `BAO_CAO_DU_AN.md`: tách rõ "đã test mô phỏng" / "đã test phần cứng thật" / "chưa" | Không còn "ĐÃ XONG" nào thiếu bằng chứng |
| A4 | Đổi tên `soak_report.json` thành `soak_report_mock.json`; soak thật làm ở giai đoạn B | File ghi rõ mode |

## 2. Giai đoạn B — Kiểm chứng phần cứng thật (bắt buộc trước khi bán)

Quy trình chi tiết đã có ở `docs/HARDWARE_VALIDATION.md`; plan này lập lịch và đặt ngưỡng đạt.

| # | Việc | Thiết bị | Ngưỡng đạt |
| :--- | :--- | :--- | :--- |
| B1 | Discovery `/xinfo`, handshake, `/xremote` heartbeat, reconnect | XR12 / XR16 / XR18 / MR | Tìm đúng IP, model, firmware; reconnect ≤ 3s sau rút cáp |
| B2 | Ghi PEQ có xác nhận: `eq/on=1`, type=2, freq/gain/Q lượng tử khớp nấc phần cứng | Như trên | Đọc lại == giá trị gửi; ghi lại sai số lượng tử |
| B3 | Đo RTT và mất gói UDP trên LAN và Wi-Fi sân khấu | Như trên | Báo cáo p50/p95/p99, % mất gói |
| B4 | RTA `/meters/4` (XR12/XR16/MR12) và gia hạn đăng ký | XR12 hoặc XR16 | Luồng không đứt ≥ 1 giờ |
| B5 | USB 18x18 ghi dữ liệu thật, bỏ skip cho benchmark dữ liệu thật | XR18 / MR18 | ≥ 100 mẫu hiện trường, recall/false-positive có CI |
| B6 | Soak thật ≥ 4 giờ, không mock | XR18 + mic thật | 0 xrun, RAM phẳng, 0 crash; rút laptop giữa show âm thanh không đứt |
| B7 | Thử hú thật có Soundman giám sát: semi → auto, panic, khóa tay 10s | Như trên | Ghi video + log; mọi invariant an toàn giữ nguyên |

Kết quả mỗi bước ghi vào `docs/HARDWARE_VALIDATION.md` kèm ngày, model, firmware, phiên bản phần mềm.

## 3. Giai đoạn C — Hỗ trợ X32 / M32

Hiện chưa có dòng code nào cho X32. Chỉ ghi "hỗ trợ" sau khi chạy thật.

- C1: Đọc tài liệu OSC của X32 (cổng, đường dẫn tham số, dải giá trị, metering) và đối chiếu — **chưa xác minh trong plan này, không giả định giống X-Air**.
- C2: Tách trait `MixerDriver` ở `mixer/` (chỉ khi có implementation thứ hai thật là X32), thêm `mixer/x32.rs` + mapper riêng.
- C3: Profile thiết bị X32/M32 trong `device_profiles/`.
- C4: Test mô phỏng + test thật trên X32/M32. Không có máy thật thì ghi "Beta, chưa kiểm chứng" và không bán như tính năng chính.

## 4. Giai đoạn D — Trial + license + phân phối

Chưa có gì trong code. Cần quyết định trước (câu hỏi mở ở mục 6).

- D1: Mô hình: trial N ngày hoặc giới hạn tính năng; license khóa theo máy; kiểm tra offline (show live thường không có internet).
- D2: Ký license (khóa công khai nhúng trong app, khóa riêng giữ ở xkproduction); chỉ dùng thư viện permissive (MIT/BSD/Apache-2.0) theo `GEMINI.md`.
- D3: Quy tắc an toàn: hết hạn/lỗi license **không bao giờ** được làm gián đoạn show đang chạy — chỉ chặn khởi động phiên mới (tuân thủ cách ly Audio/Control plane).
- D4: Trang tải về + thanh toán + cấp license trên xkproduction.
- D5: Build, ký và notarize cho macOS; build Windows nếu thị trường cần (soundman VN dùng Windows nhiều — cần xác nhận).
- D6: Cập nhật `docs/SBOM.md` cho mọi dependency mới.

## 5. Giai đoạn E — Nâng cấp sản phẩm (sau khi A–B xong)

Các hạng mục này thêm giá trị nhưng không được làm trước B.

| # | Ý tưởng | Lý do |
| :--- | :--- | :--- |
| E1 | Cài đặt một lần: lưu IP/profile/chế độ, tự kết nối lại khi mở app | Giảm thao tác ngay trước show |
| E2 | Báo cáo show (notch đã hạ, tần số hú, thời điểm) xuất PDF/CSV | Soundman đưa cho khách |
| E3 | Preset phòng (lưu ring-out theo địa điểm) | Dùng lại khi quay lại địa điểm |
| E4 | Chẩn đoán một chạm: mạng, cổng, firmware, số client X-Air (tối đa 4) | Giảm hỗ trợ kỹ thuật |
| E5 | Hướng dẫn người dùng + video ngắn bằng tiếng Việt | Cần cho sản phẩm bán |
| E6 | Tự động cập nhật có ký số | Sửa lỗi sau phát hành |

## 6. Câu hỏi mở (cần chủ dự án quyết định)

1. Bản chính là Rust/Tauri (khớp thư mục hiện tại) — xác nhận?
2. Có XR18/XR12/X32 thật để test không, hay phải mượn/thuê?
3. Mô hình trial: số ngày hay giới hạn tính năng? License theo máy hay theo tài khoản?
4. Nền tảng cần bán: chỉ macOS hay thêm Windows?

## 7. Cổng phát hành

Chỉ push bản bán khi: A đủ, B1–B7 đạt, tính năng X32 hoặc đã chạy thật hoặc ghi rõ Beta, D3 đã có test (hết hạn license không ảnh hưởng show), `cargo test` và test frontend đều xanh với số liệu ghi trong báo cáo.
