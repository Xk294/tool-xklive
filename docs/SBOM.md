# Danh mục Thành phần Phần mềm & Giấy phép (SBOM)

Dự án **Auto Sound Engineer (`tool xklive`)** tuân thủ nghiêm ngặt chính sách **100% Giấy phép Mã nguồn mở Permissive** (`MIT`, `Apache-2.0`, `BSD-2-Clause`, `BSD-3-Clause`, `ISC`, `Unlicense`). Tuyệt đối **không** sử dụng bất kỳ thư viện nào mang giấy phép `GPL`, `LGPL`, `AGPL` hoặc `FFTW`.

---

## 1. Thư viện Backend Rust (`src-tauri/Cargo.toml`)

| Crate | Phiên bản | Giấy phép | Vai trò trong hệ thống |
| :--- | :--- | :--- | :--- |
| `tauri` | `2.x` | `Apache-2.0 OR MIT` | Khung ứng dụng Desktop đa nền tảng và cầu nối IPC. |
| `tauri-build` | `2.x` | `Apache-2.0 OR MIT` | Công cụ đóng gói tài nguyên Tauri lúc biên dịch. |
| `serde` | `1.x` | `MIT OR Apache-2.0` | Tuần tự hóa / giải tuần tự hóa dữ liệu cấu trúc. |
| `serde_json` | `1.x` | `MIT OR Apache-2.0` | Xử lý dữ liệu JSON cho Tauri IPC và xuất báo cáo. |
| `tokio` | `1.x` | `MIT` | Runtime bất đồng bộ cho các tác vụ nền và điều phối luồng. |
| `rosc` | `0.10` | `MIT` | Mã hóa và giải mã gói tin giao thức Open Sound Control (OSC 1.0) qua UDP. |
| `rustfft` | `6.2` | `MIT OR Apache-2.0` | Thuật toán biến đổi Fourier nhanh (FFT) thuần Rust cho bộ phát hiện hú 2048 mẫu. |
| `cpal` | `0.15` | `Apache-2.0` | Giao tiếp thu âm đa kênh thời gian thực đa nền tảng (CoreAudio / WASAPI / ALSA). |
| `rtrb` | `0.3` | `MIT OR Apache-2.0` | Bộ đệm vòng SPSC Lock-Free không cấp phát bộ nhớ động (0 heap allocation) trong luồng âm thanh thời gian thực. |
| `parking_lot` | `0.12` | `MIT OR Apache-2.0` | Các cấu trúc đồng bộ hóa (`Mutex`) hiệu năng cao, không gây nhiễm độc khóa (poisoning). |
| `log` | `0.4` | `MIT OR Apache-2.0` | Giao diện ghi nhận nhật ký nhẹ tiêu chuẩn của Rust. |
| `tauri-plugin-log` | `2.x` | `Apache-2.0 OR MIT` | Plugin quản lý và xuất nhật ký chuẩn cho Tauri v2. |
| `chrono` | `0.4` | `MIT OR Apache-2.0` | Định dạng nhãn thời gian cho nhật ký sự kiện và báo cáo JSON/CSV. |

---

## 2. Thư viện Frontend & Công cụ Đóng gói (`package.json`, `frontend/package.json`)

| Gói (Package) | Phiên bản | Giấy phép | Vai trò trong hệ thống |
| :--- | :--- | :--- | :--- |
| `nuxt` | `^4.0.0` | `MIT` | Khung ứng dụng giao diện SPA dựa trên Vue 3. |
| `vue` | `^3.5.0` | `MIT` | Thư viện giao diện phản ứng (Reactivity & Component UI). |
| `vue-router` | `^4.4.0` (tích hợp qua Nuxt 4) | `MIT` | Điều hướng trạng thái giao diện trong Nuxt. |
| `@tauri-apps/api` | `^2.12.4` | `Apache-2.0 OR MIT` | Thư viện JavaScript gọi lệnh IPC (`invoke`) xuống nhân Rust. |
| `@tauri-apps/cli` | `^2.0.0` | `Apache-2.0 OR MIT` | Công cụ dòng lệnh chạy phát triển (`tauri dev`) và đóng gói (`tauri build`). |

---

## 3. Cách Kiểm tra Lại Giấy phép

Để kiểm tra độc lập cây phụ thuộc Rust và Frontend bất kỳ lúc nào:

```bash
# Kiểm tra cây phụ thuộc và giấy phép các crate Rust
cargo metadata --manifest-path src-tauri/Cargo.toml --format-version 1
```
