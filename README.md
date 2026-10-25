# Auto Sound Engineer (Behringer X-Air & Midas M-Air)

Hệ thống hỗ trợ kỹ sư âm thanh trực tiếp (Live Sound) tự động phát hiện hú (acoustic feedback) và can thiệp notch PEQ trực tiếp trên dòng mixer digital Behringer X-Air (XR12, XR16, XR18) & Midas M-Air (MR12, MR18) qua giao thức mạng OSC/UDP (cổng 10024) kết hợp giao diện Web Companion hiện đại (Nuxt 4 / Vue 3).

---

## 1. Nguyên Tắc Cốt Lõi

Đây là thiết kế và hành vi có trong mã nguồn Rust; chưa mục nào được kiểm chứng trên mixer thật (xem mục 5).

1. **Tách biệt tuyệt đối Audio Plane và Control Plane**:
   - Âm thanh của buổi biểu diễn đi trực tiếp từ micro -> mixer -> loa FOH/Monitor, hoàn toàn **KHÔNG đi qua laptop**.
   - Laptop chỉ thu bản sao tín hiệu (qua cổng USB 18x18 đối với XR18/MR18, hoặc qua gói tin phổ RTA 100-band đối với XR12/XR16/MR12) để phân tích DSP và gửi lệnh điều khiển PEQ qua mạng LAN (OSC/UDP).
   - **Cam kết an toàn**: Nếu laptop treo, phần mềm tắt hoặc đứt cáp USB, buổi diễn vẫn tiếp tục phát 100% bình thường, không bao giờ làm gián đoạn chương trình.

2. **Kỹ sư âm thanh (Soundman) luôn giữ quyền quyết định**:
   - Hỗ trợ 3 chế độ vận hành: Tự động (`auto`), Bán tự động (`semi` — cảnh báo đỏ, chờ Soundman bấm Space hoặc bấm Approve trên Web để hạ notch), và Gợi ý (`manual`).
   - Có nút **PANIC** (phím `P` hoặc `Esc`, hoặc nút đỏ khẩn cấp trên giao diện): Lập tức hoàn tác, trả toàn bộ các notch hệ thống về trạng thái gốc ban đầu (`original_gain_db`) chỉ trong 1 thao tác.

3. **Can thiệp Mixer An toàn & Tương tác Trực tiếp (Direct Interfacing)**:
   - **Tự động quét mạng (Auto-Discovery)**: Quét UDP broadcast `/xinfo` port 10024 để tìm mixer Behringer/Midas trên LAN không cần gán cứng IP.
   - **Đồng bộ Metadata thời gian thực**: Lấy tên kênh, trạng thái MUTE và trạng thái EQ on của kênh trực tiếp từ mixer.
   - **Mute-Aware DSP Skip**: Tự động bỏ qua phân tích các micro đang bị MUTE trên bàn mixer để triệt tiêu hoàn toàn báo động giả.
   - **Đảm bảo hiệu lực PEQ (Direct PEQ Enforcement)**: Hàm `set_peq()` tự động bật Master EQ kênh (`/eq/on = 1`) và ép loại Band về Parametric EQ (`type = 2`), chống tình trạng notch bị vô hiệu hoặc méo dải cao từ preset cũ.
   - **Cơ chế Expected-Echo**: Phân biệt chính xác giữa phản hồi của lệnh hệ thống ghi với thao tác vặn tay thực tế của soundman trên iPad/bàn mixer.
   - **Rate limit**: Tối đa 2 giao dịch/giây, tránh nghẽn buffer UDP và sập giao diện điều khiển X-Air-Edit.
   - **Cắt thăm dò vi phân**: Chớm hú hạ `-3.0 dB`, nếu hú tiếp tục mới hạ dần tới tối đa `-12.0 dB`. Tuyệt đối không bao giờ tăng gain quá `+4.0 dB`.
   - **Bảo toàn dải tần soundman**: Trên micro chỉ can thiệp Band 3 & 4 (giữ Band 1 & 2 cho Soundman căn tone giọng ca sĩ); trên Main L/R chỉ can thiệp Band 3, 4, 5, 6.
   - **Khóa an toàn khi chỉnh tay (Manual Override Lock)**: Nếu soundman tự vặn núm EQ trên iPad hoặc mixer, hệ thống tự động khóa can thiệp trên kênh đó 10 giây.
   - **Two-Factor Localizer**: Giải quyết hiện tượng crosstalk khi nhiều mic cùng bắt tiếng hú dựa trên ma trận phổ và routing Bus.
   - **Auto-Release & Reclaiming**: Tự động thu hồi notch nông nhất khi cạn band PEQ và từ từ nhả gain notch về 0 dB khi âm trường ổn định.

4. **Quy ước giấy phép thư viện**:
   - Chỉ dùng thư viện MIT, BSD, Apache-2.0, Unlicense; không GPL/AGPL, không FFTW (chi tiết tại `docs/SBOM.md`).

---

## 2. Cài Đặt Môi Trường

Stack duy nhất: Tauri v2 + Rust (`src-tauri/`) cho lõi, DSP và mixer; Nuxt 4 / Vue 3 (`frontend/`) cho giao diện.

Yêu cầu:
- Rust toolchain (`rustup`), Node.js + npm, hệ điều hành hỗ trợ Tauri v2 (macOS đang là môi trường phát triển).
- Phần cứng: cáp mạng LAN RJ45 Cat5e/Cat6, cáp USB 2.0 Type-B nối XR18/MR18 (XR12/XR16/MR12 chỉ cần LAN).

```bash
# Cài dependency gốc (Tauri CLI) và giao diện
npm install
npm --prefix frontend install

# Chạy ứng dụng ở chế độ phát triển (Tauri + Nuxt)
npm run dev

# Build ứng dụng desktop
npm run build
```

---

## 3. Kiểm Thử

```bash
# Chạy toàn bộ test Rust
npm test    # tương đương: cargo test --manifest-path src-tauri/Cargo.toml
```

Số liệu test và hiện trạng kiểm chứng: xem `BAO_CAO_DU_AN.md` mục 5. Frontend chưa có test tự động.

---

## 4. Vận Hành

Mở ứng dụng, quét mixer trong mạng LAN (UDP broadcast `/xinfo`, cổng 10024) hoặc nhập IP, rồi kết nối. Chế độ `auto` / `semi` / `manual` và nút PANIC nằm trên giao diện.

### Kết nối XR18 / MR18 (USB 18x18 + LAN)
1. Nối cáp mạng RJ45 trực tiếp từ laptop tới mixer (hoặc qua switch có dây). Tránh Wi-Fi 2.4GHz ở nơi đông người.
2. Đặt IP tĩnh cùng subnet, ví dụ laptop `192.168.1.50`, mixer `192.168.1.100`, subnet `255.255.255.0`. Cổng OSC mặc định `10024`.
3. Nối USB từ cổng USB B của mixer vào laptop; trong X-Air Edit, định tuyến 16 kênh micro tới USB Sends (`Direct Out`, pre-gain).

### Kết nối XR12 / XR16 / MR12 (RTA LAN)
Các model này không có USB audio đa kênh. Hệ thống dùng luồng phổ RTA 100-band (`/meters/4`) qua LAN để dò hú trên Main L/R và hạ notch ở Band 3–6 (giữ Band 1–2 cho Soundman).

Profile thiết bị: thư mục `device_profiles/`.

---

## 5. Hiện Trạng Kiểm Chứng

Chưa có bằng chứng chạy với mixer thật. Số liệu test mô phỏng và danh sách phần chưa kiểm chứng: `BAO_CAO_DU_AN.md` mục 3.

Kế hoạch đưa sản phẩm tới mức bán được: `docs/plan/plan-release-readiness.md`. Quy trình đo phần cứng: `docs/HARDWARE_VALIDATION.md`.

---

## 6. Cấu Trúc Dự Án

```text
xklive/
├── src-tauri/src/
│   ├── core/        # models, safety (rate limit, probing, khóa tay), ringout
│   ├── mixer/       # xair.rs (OSC driver), mapper.rs (float <-> Hz/dB)
│   ├── dsp/         # detector (FFT), rta_detector, localizer, gain_staging, talkover
│   ├── audio/       # thu âm CPAL + ring buffer SPSC
│   ├── commands.rs  # lệnh Tauri cho giao diện
│   └── state.rs     # trạng thái ứng dụng
├── frontend/        # Nuxt 4 / Vue 3 SPA + Scoped CSS
├── device_profiles/ # profile từng model (TOML)
├── docs/            # kế hoạch, API, SBOM, quy trình kiểm chứng phần cứng
└── BAO_CAO_DU_AN.md # báo cáo trạng thái
```

---

## 7. Giấy Phép & Bản Quyền

Repo chưa có file `LICENSE`; chủ dự án cần quyết định giấy phép trước khi phát hành.
