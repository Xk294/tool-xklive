# Trung tâm Tài liệu Dự án — Auto Sound Engineer (`tool xklive`)

Tài liệu kỹ thuật và vận hành cho ứng dụng **Auto Sound Engineer** (kiến trúc **Tauri v2 / Rust + Nuxt 4 / Vue 3**), hỗ trợ tự động phát hiện và cắt hú PEQ qua giao thức OSC (UDP cổng `10024`) cho dòng bàn mixer số Behringer X-Air (`XR12`, `XR16`, `XR18`) và Midas M-Air (`MR12`, `MR18`).

---

## Danh mục Tài liệu

- **[Hướng dẫn Cài đặt & Chạy thử (`../README.md`)](../README.md)**: Yêu cầu môi trường (Node.js, Rust), lệnh chạy chế độ phát triển (`npm run dev`), kiểm thử (`npm test`) và đóng gói.
- **[Báo cáo Hiện trạng Kỹ thuật (`../BAO_CAO_DU_AN.md`)](../BAO_CAO_DU_AN.md)**: Bảng đối chiếu chi tiết từng mô-đun trong `src-tauri/src/`, các giới hạn hiện tại và kết quả kiểm thử tự động.
- **[Tài liệu Lệnh Tauri IPC (`API.md`)](API.md)**: Đặc tả cấu trúc `FullStateSnapshot` và toàn bộ các lệnh Tauri IPC (`invoke`) kết nối giữa giao diện Nuxt 4 và nhân Rust.
- **[Quy trình Kiểm chứng Phần cứng (`HARDWARE_VALIDATION.md`)](HARDWARE_VALIDATION.md)**: Các bước kiểm tra thực tế trên bàn mixer vật lý trước khi đưa vào vận hành sân khấu.
- **[Quy trình Thu thập Dữ liệu Thực địa (`DATA_COLLECTION.md`)](DATA_COLLECTION.md)**: Hướng dẫn thu âm đa kênh 48kHz và đánh nhãn sự kiện âm thanh để tinh chỉnh thuật toán DSP.
- **[Danh mục Thành phần Phần mềm & Giấy phép (`SBOM.md`)](SBOM.md)**: Danh sách các crate Rust và gói npm sử dụng trong dự án (100% giấy phép mã nguồn mở Permissive).
- **[Kế hoạch Kiến trúc Engine (`plan/PLAN_AUTO_SOUND_ENGINE.md`)](plan/PLAN_AUTO_SOUND_ENGINE.md)**: Thiết kế chi tiết các thuật toán DSP, Safety Controller và giao thức điều khiển.
- **[Kế hoạch Chuẩn bị Phát hành (`plan/plan-release-readiness.md`)](plan/plan-release-readiness.md)**: Lộ trình đồng bộ tài liệu và hoàn thiện độ ổn định trước khi phát hành.
- **[Thiết kế Giao diện Easy Mode (`plan/done/design-easy-mode.md`)](plan/done/design-easy-mode.md)**: Đặc tả UX 4 bước tối giản và hệ thống thông điệp tiếng Việt thân thiện cho người vận hành không chuyên.
- **[Kế hoạch Mở rộng Tính năng (`plan/plan-growth.md`)](plan/plan-growth.md)**: Định hướng phát triển các mô-đun trợ lý âm thanh tự động theo giai đoạn.
- **[Nghiên cứu Lỗ hổng Vận hành Show Đơn Giản (`research/simple-show-gaps.md`)](research/simple-show-gaps.md)**: Báo cáo kiểm toán sâu 9 lỗi kỹ thuật và khoảng trống UX từ mã nguồn thực tế khi chạy một buổi diễn đơn giản.
- **[Kế hoạch Nâng cấp Trợ lý Show Đơn Giản (`plan/done/simple-show-upgrade.md`)](plan/done/simple-show-upgrade.md)**: Lộ trình 4 giai đoạn (đã hoàn tất) vá lỗi an toàn Fader/USB/Snapshot, kích hoạt `Talkover`/`GainStaging`/`Localizer` và nâng cấp màn hình chạy show Bước 4.
