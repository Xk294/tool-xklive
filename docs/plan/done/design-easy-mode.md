# DESIGN — Chế độ Easy (P1.1) & quy trình kết nối mixer (P1.2)

Thuộc `PLAN_GROWTH.md`. Đối tượng: người rất yếu kỹ thuật, show dân dã, chỉ tiếng Việt. Trạng thái: Đã triển khai (Implemented).

## 1. Hiện trạng giao diện (đã đọc `frontend/app/app.vue`)

Một màn hình dashboard 2 cột gồm: StatusBar (nhiều nút: mode, preset, dry-run, diagnostics, wizard, demo, dynamics, connect, signal-gen), RtaCanvas, MetersGrid 16 kênh, NotchesTable (có ô tiêm notch thủ công), ProposalsQueue, SnapshotSection, EventLogBox, 6 modal. Phím tắt: `P`/`Esc` = panic, `Space` = duyệt đề xuất. Đây là giao diện cho người rành kỹ thuật; người mới sẽ bị quá tải.

## 2. Nguyên tắc thiết kế

- Mỗi thời điểm chỉ **một việc** để làm; người dùng không bao giờ phải chọn tham số.
- Không dùng chữ: notch, PEQ, OSC, UDP, RTA, dry-run, xrun. Dùng: "chống hú", "mic", "phòng", "an toàn".
- Mọi lỗi nói rõ **nguyên nhân + việc cần làm** bằng tiếng Việt.
- Chữ lớn, nút lớn (dùng ngoài trời, trong tối, tay run). Tương phản cao.
- Giữ nguyên các giới hạn an toàn của `core/safety.rs`; Easy chỉ là lớp trình bày, **không nới giới hạn**.

## 3. Luồng Easy — 4 bước, tuần tự

```
[1 Kết nối] → [2 Kiểm tra mic] → [3 Cân phòng] → [4 Đang chạy show]
```
Thanh tiến trình 4 chấm ở trên cùng; có thể quay lại bước trước. Mở app lần sau: nếu nhớ được mixer cũ và tìm thấy trong ≤3 giây thì tự nhảy thẳng bước 2.

### Bước 1 — Kết nối
- Vào là tự quét (`discover_mixers_cmd`). Trạng thái: "Đang tìm bàn mixer…".
- Tìm thấy 1: thẻ lớn "Tìm thấy **XR18** — Kết nối" (`connect_mixer`). Tìm thấy nhiều: danh sách thẻ.
- Không tìm thấy sau ~5 giây: hộp "Chưa thấy mixer" với 3 mục kiểm tra bấm-để-xác-nhận:
  1. Mixer đã bật và đèn mạng sáng?
  2. Laptop và mixer cùng một Wi-Fi/router? (kèm hình minh họa 1 router rẻ + mixer + laptop)
  3. Bạn đang dùng Wi-Fi công cộng/khách sạn? (chặn thiết bị nhìn thấy nhau → cần router riêng)
- Nút "Quét lại". Liên kết "Nhập địa chỉ thủ công" ẩn trong "Nâng cao".
- Lỗi theo loại: sai model không hỗ trợ ("Bàn này chưa được hỗ trợ"), mất kết nối giữa chừng ("Mất kết nối — show vẫn chạy bình thường vì âm thanh không đi qua máy tính", tự thử lại).

### Bước 2 — Kiểm tra mic
- Hiện danh sách mic dạng ô lớn, mỗi ô: tên kênh + thanh mức + đèn Xanh/Vàng/Đỏ (dựa trên `gain_staging`).
- Hướng dẫn: "Nói hoặc hát vào từng mic". Mic đỏ → gợi ý "Mic X to quá, hạ gain xuống". Chỉ **gợi ý**, không tự chỉnh (khớp với hành vi `gain_staging` hiện tại).
- Nếu mixer thuộc nhóm USB (XR18/MR18) hướng dẫn chọn đường âm thanh cắm USB (`list_audio_devices`/`start_audio_capture`) tự động; nhóm XR12/XR16/MR12 dùng RTA qua mạng — người dùng không phải biết sự khác biệt.

### Bước 3 — Cân phòng
- Một nút to "BẮT ĐẦU CÂN PHÒNG" (`start_wizard`). Cảnh báo trước 1 lần: "Loa sẽ phát tiếng rít nhỏ vài giây, hạ âm lượng loa nếu cần" + nút "Dừng ngay" luôn hiện (`stop_wizard`).
- Hiện tiến độ bằng lời ("Đang tìm điểm hay hú… 3/5"), không hiện đồ thị mặc định.
- Kết thúc: "Xong! Đã xử lý N điểm hay hú. Phòng này an toàn hơn rồi." Tự `take_snapshot` để có điểm quay lại.
- Có nút "Bỏ qua" (người dùng vẫn vào show được).

### Bước 4 — Đang chạy show
Màn hình chỉ có:
- **Đèn trạng thái cực lớn**: Xanh "Đang bảo vệ", Vàng "Vừa chặn hú ở mic X", Đỏ "Mất kết nối / cần chú ý".
- Một dòng thông báo gần nhất bằng tiếng Việt đời thường, ví dụ: "Mic 3 sắp hú — đã giảm nhẹ. Vẫn đang theo dõi."
- **Nút "DỪNG KHẨN / TRẢ LẠI NHƯ CŨ"** (panic → `panic_reset`, rollback snapshot), luôn ở cùng một chỗ; phím `Esc` giữ nguyên.
- Nút phụ nhỏ: "Chống hú: Tự động / Hỏi tôi trước" (ánh xạ `set_mode`; mặc định **Tự động** với giới hạn an toàn hiện có; chế độ "hỏi trước" hiện đề xuất một-nút Đồng ý/Bỏ qua).
- Kết show: nút "Kết thúc show" → tạo báo cáo 1 trang (`export_report`) và hiển thị số liệu thân thiện.

## 4. Những gì ẩn khỏi Easy

RtaCanvas, MetersGrid 16 kênh, NotchesTable + tiêm tay, whitelist/lock theo kênh, SnapshotSection, EventLog thô, Diagnostics, Dynamics, Signal Generator, nút demo-feedback, dry-run. Chúng gom vào menu "Nâng cao" (ẩn sau thao tác bấm giữ hoặc nhấn 5 lần vào logo) để người hỗ trợ từ xa/chủ dự án vẫn dùng được. Chủ dự án đã chọn Easy là mặc định duy nhất; menu nâng cao chỉ phục vụ gỡ lỗi, không quảng bá.

## 5. Preset (P1.3) gắn vào bước 3–4

Chọn loại show ngay đầu bước 2: Đám cưới / Karaoke / Quán cà phê acoustic / MC thuyết trình. Preset chỉ chọn các giá trị **bên trong** biên an toàn hiện có (độ nhạy dò hú, gợi ý gain, bật/tắt talkover). Cần quyết định giá trị cụ thể bằng dữ liệu thực địa, không phỏng đoán trong tài liệu này.

## 6. Chế độ demo (P1.6)

Nút "Thử không cần mixer" ở bước 1: dùng mixer giả + `trigger_demo_feedback` để người xem thấy chuỗi "hú → đèn vàng → đã chặn" trong ~10 giây. Gắn banner "ĐANG THỬ — chưa nối mixer thật" để không nhầm với show thật.

## 7. Việc kỹ thuật cần làm

| # | Việc | Ghi chú |
|---|---|---|
| 1 | Màn hình Easy mới, tách khỏi dashboard hiện tại | `frontend/app/`; dashboard cũ chuyển vào route nâng cao |
| 2 | Lớp dịch sự kiện kỹ thuật → câu tiếng Việt | Nguồn: `ActionProposal`, snapshot trạng thái; một nơi duy nhất chứa bảng thông điệp |
| 3 | Nhớ mixer lần trước + tự kết nối lại | Lưu cục bộ, không cần mạng |
| 4 | Mô tả lỗi kết nối theo loại | Cần phân loại lỗi từ `connect_mixer` (hiện chỉ trả `Result<bool,String>`) |
| 5 | Test giao diện | Frontend hiện không có script test nào |
| 6 | Thử nghiệm người dùng thật | 3–5 người dân dã, quan sát không hướng dẫn; đo: có tới bước 4 mà không hỏi ai không |

## 8. Tiêu chí hoàn thành

- Người chưa từng dùng đi từ mở app đến "Đang bảo vệ" trong ≤ 3 phút, không cần đọc hướng dẫn.
- Mọi trạng thái lỗi có thông điệp tiếng Việt kèm việc cần làm.
- Nút dừng khẩn luôn hiển thị và hoạt động ở mọi bước.
- Easy không làm thay đổi bất kỳ giới hạn nào của bộ an toàn.
- Toàn bộ chạy đúng trên phần cứng thật (phụ thuộc giai đoạn B của `PLAN_RELEASE_READINESS.md`).
