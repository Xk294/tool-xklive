# PLAN — Nâng cấp "wow" & mở rộng tệp người dùng (ưu tiên show bình dân)

Trạng thái: đề xuất, chờ chủ dự án duyệt. Không thay thế `PLAN_RELEASE_READINESS.md` — **giai đoạn B (kiểm chứng phần cứng thật) vẫn là điều kiện tiên quyết cho mọi mục dưới đây**.

## 1. Nhận định

- Người làm show bình dân (đám cưới, quán cà phê, sự kiện nhỏ, nhà thờ/chùa, ca nhạc đường phố, karaoke) thường: không có kỹ thuật viên âm thanh chuyên nghiệp, mixer rẻ, nỗi đau số 1 là **hú (feedback)**, nỗi đau số 2 là **không biết chỉnh EQ/gain**, và ngân sách gần như bằng 0.
- Lợi thế hiện có: phần mềm không nằm trên đường audio (an toàn), có bộ an toàn, ring-out, dò hú. Điểm yếu cho tệp này: yêu cầu hiểu OSC/IP/USB, chỉ hỗ trợ X-Air/M-Air, giao diện nghiêng về dân kỹ thuật.
- Thông điệp định vị đề xuất: **"Cắm vào mixer, bấm 1 nút, hết hú."** Không dùng thuật ngữ DSP trong màn hình chính.

## 2. Hạng mục theo mức ưu tiên

### P0 — Tiên quyết (không có thì không bán được)
| # | Việc | Lý do |
|---|---|---|
| P0.1 | Kiểm chứng phần cứng thật XR12/XR16/XR18 | Chưa có bằng chứng thực địa; xem `HARDWARE_VALIDATION.md` |
| P0.2 | Build ký + notarize (macOS) và Windows installer | Người dùng bình dân không vượt nổi cảnh báo "không rõ nhà phát hành" |
| P0.3 | Kiểm toán SBOM Rust/npm | SBOM hiện còn của bản Python |

### P1 — "Wow" tức thì với người không chuyên
| # | Việc | Mô tả |
|---|---|---|
| P1.1 | **Chế độ "Easy / 1 nút"** | Màn hình chính chỉ: trạng thái kết nối, nút "Cân phòng" (ring-out), đèn Xanh/Vàng/Đỏ. Ẩn bảng notch/proposals vào "Nâng cao" |
| P1.2 | **Tự tìm mixer + hướng dẫn kết nối từng bước** | Quét mạng, hiện "Tìm thấy XR18 — Kết nối?"; wizard có hình ảnh cho trường hợp thiếu router (hướng dẫn dùng router Wi-Fi rẻ/AP mode) |
| P1.3 | **Preset theo loại show** | "Đám cưới", "Hát karaoke", "Quán cà phê acoustic", "MC thuyết trình": đặt sẵn ngưỡng an toàn, gợi ý gain, talkover |
| P1.4 | **Thông báo tiếng Việt, ngôn ngữ đời thường** | Vd "Mic 3 sắp hú ở 2.5kHz — đã tự giảm nhẹ" thay vì tên tham số |
| P1.5 | **Báo cáo sau show 1 trang** | Xuất ảnh/PDF: số lần hú được chặn, mic nào hay hú; người dùng khoe cho khách → marketing tự nhiên |
| P1.6 | **Chế độ demo không cần mixer** | Mock mixer + hú giả có sẵn trong app để người xem thử/quay video quảng cáo; tăng chuyển đổi |

### P2 — Mở rộng thị trường
| # | Việc | Mô tả |
|---|---|---|
| P2.1 | **Hỗ trợ X32/M32 (và rack/Compact)** | Thị trường lớn hơn nhiều so với X-Air; nhưng X32 cao cấp hơn, ít "bình dân" — đặt sau nhóm bình dân |
| P2.2 | **Điều khiển từ điện thoại (web UI trong LAN, có PIN)** | Soundman đứng giữa phòng; bản Python từng có PIN LAN, bản Rust chưa có |
| P2.3 | **Hỗ trợ mixer rẻ phổ biến ở VN** | Khảo sát trước (Yamaha MG/TF, Soundcraft, mixer analog có USB): chỉ làm nếu có giao thức điều khiển mở; mixer analog không điều khiển được thì cân nhắc chế độ "chỉ cảnh báo/nghe" |
| P2.4 | **Chế độ chỉ-cảnh báo (không ghi vào mixer)** | Dùng được với mixer không có OSC: app nghe qua USB/line-in và báo "hú ở ~2.5kHz, hạ fader mic 3" |
| P2.5 | **Đa ngôn ngữ (Việt/Anh trước)** | UI + tài liệu |

### P3 — Kinh doanh & tăng trưởng
| # | Việc | Mô tả |
|---|---|---|
| P3.1 | Trial 14 ngày + license offline | Chưa có (nêu trong báo cáo dự án) |
| P3.2 | Giá bậc thang | Free (cảnh báo + ring-out thủ công), Pro (tự động notch), Crew (nhiều mixer/thuê show) |
| P3.3 | Video demo 60 giây trước/sau | Kênh TikTok/YouTube/group Facebook thợ âm thanh VN |
| P3.4 | Cộng đồng + thu thập dữ liệu hiện trường (có consent) | Khớp `DATA_COLLECTION.md`; cần cho benchmark ≥100 mẫu |
| P3.5 | Chương trình đối tác | Cửa hàng/ dịch vụ cho thuê âm thanh giới thiệu |

## 3. Thứ tự đề xuất

1. P0 hoàn tất (song song với phần cứng thật).
2. P1.1 + P1.2 + P1.6 (trải nghiệm đầu tiên + demo) → ra bản beta công khai.
3. P1.3–P1.5 → bản 1.0.
4. P3.1–P3.3 → bán.
5. P2 theo phản hồi thị trường.

## 4. Rủi ro cần lưu ý
- Hứa "tự động hoàn toàn" với người không chuyên làm tăng hậu quả khi hú xảy ra: mọi preset giữ nguyên các giới hạn an toàn trong `GEMINI.md` (rate limit, max cut/boost, khóa tay).
- Mở rộng mixer (P2) phải giữ nguyên nguyên tắc audio plane ≠ control plane.
- Chỉ dùng thư viện permissive (MIT/BSD/Apache-2.0/Unlicense) cho mọi thành phần mới.

## 5. Quyết định của chủ dự án (24/10/2026)
1. Giá: **mua một lần**, phân phối bằng file cài đặt `.pkg` (macOS) / `.exe` (Windows) tự tải về, **không** lên App Store / Google Play.
2. Thị trường: **chỉ Việt Nam** (giai đoạn đầu).
3. Đối tượng: người **rất yếu kỹ thuật**, làm show dân dã. **Không nhắm** show chuyên nghiệp cao cấp.

Hệ quả lên plan:
- P3.2 (giá bậc thang Free/Pro/Crew) → bỏ; thay bằng một giá duy nhất + license key offline.
- P2.1 (X32/M32) → hạ ưu tiên xuống thấp nhất; dân dã ít dùng.
- P2.5 (đa ngôn ngữ) → chỉ tiếng Việt.
- P0.2 → đổi thành: ký Developer ID + notarize cho `.pkg`, ký code cho `.exe` (tránh cảnh báo SmartScreen/Gatekeeper); không cần tài khoản store.
- P3.1 → cần cơ chế chống chia sẻ key lậu nhẹ nhàng, hoạt động offline (show thường không có Internet).
- P1.1 (chế độ Easy) trở thành mặc định duy nhất; chế độ nâng cao ẩn sâu hoặc bỏ.
