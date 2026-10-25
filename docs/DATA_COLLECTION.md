# QUY TRÌNH THU THẬP DỮ LIỆU ÂM THANH THỰC TẾ (FIELD DATA COLLECTION)

Tài liệu này hướng dẫn cách thu thập các bản ghi âm thanh đa kênh (Multitrack WAV) và nhật ký trạng thái mixer tại hiện trường (phòng họp, hội trường, sân khấu). Dữ liệu thu được dùng để tinh chỉnh ngưỡng phát hiện hú (`FeedbackDetector`) và kiểm thử hồi quy.

> **LƯU Ý HIỆN TRẠNG**: Kịch bản thu thập tự động bằng Python trước đây đã được gỡ bỏ khi dự án chuyển sang kiến trúc Rust/Tauri (`src-tauri/`). Hiện tại, việc thu âm thực địa được thực hiện bằng phần mềm DAW tiêu chuẩn (Reaper, Audacity, Waves Tracks Live) kết hợp ghi chú biên bản hiện trường theo quy trình dưới đây, hoặc xuất báo cáo sự kiện trực tiếp từ ứng dụng Tauri (`Export JSON/CSV`).

---

## 1. Mục tiêu Thu thập Dữ liệu

Một bộ dữ liệu chuẩn giúp thuật toán phân biệt chính xác giữa **tiếng hú thật (Acoustic Feedback)** và **âm thanh biểu diễn bình thường (Nhạc cụ, Giọng hát)**:

1. **Dữ liệu Dương tính (True Positives - Tiếng hú thật)**:
   - Tiếng hú chớm nở (Ringing) ở dải tần thấp (150Hz – 400Hz - um tiếng), dải trung (800Hz – 2.5kHz - giọng nói) và dải cao (3kHz – 8kHz - chói gắt).
   - Tiếng hú xuất hiện khi ca sĩ đưa micro lại gần loa kiểm âm (Monitor) hoặc đi ra trước loa chính (FOH).

2. **Dữ liệu Âm tính khó (Hard Negatives - Dễ gây cắt nhầm / False Positives)**:
   - Tiếng ngân giọng hát dài (Sustained Vocal / Opera / Bolero).
   - Tiếng sáo trúc, đàn bầu, violin, guitar điện có hiệu ứng sustain/overdrive.
   - Tiếng còi, chuông hoặc hiệu ứng âm thanh tổng hợp (Synth Pad) trong nhạc nền.

---

## 2. Thiết bị & Kết nối Chuẩn bị

1. **Bàn Mixer**: Behringer XR18 / Midas MR18 (hỗ trợ ghi âm 18 kênh qua USB) hoặc XR12/XR16/MR12 (thu qua ngõ USB 2-track hoặc soundcard rời).
2. **Cáp kết nối**:
   - Cáp mạng LAN kết nối máy tính với cổng Ethernet của Mixer (đặt công tắc ở vị trí **ETHERNET**) để ứng dụng Tauri giám sát OSC.
   - Cáp USB 2.0 kết nối từ cổng USB của Mixer vào máy tính để thu âm đa kênh.
3. **Cấu hình định tuyến USB Sends trên Mixer (XR18/MR18)**:
   - Đặt **Channel 1–16 USB Sends** ở vị trí **Analog (Pre-EQ / Pre-Fader)**.
   - Đặt **USB 17–18** ở vị trí **Main L/R (Post-EQ)** để đối chiếu tín hiệu tổng trước và sau khi cắt PEQ.

---

## 3. Quy trình Thu âm & Đánh nhãn tại Hiện trường

### 3.1. Thiết lập dự án thu âm trên DAW
1. Mở phần mềm thu âm (ví dụ: Reaper), chọn thiết bị đầu vào là `X18/XR18 USB Audio` ở tần số lấy mẫu **48000 Hz**, định dạng **24-bit PCM WAV**.
2. Tạo 18 rãnh (tracks) tương ứng với 18 kênh đầu vào USB và bật chế độ chờ ghi âm (Record Arm).

### 3.2. Thực hiện ghi âm và đánh dấu mốc thời gian (Marker)
Trong suốt buổi tổng duyệt (Soundcheck) hoặc biểu diễn:
- Nhấn phím tạo Marker trên DAW (phím `M` trong Reaper) ngay tại thời điểm xảy ra sự kiện và ghi nhãn thống nhất:
  - `HOWL`: Bắt đầu nghe thấy tiếng hú rít rõ rệt.
  - `RING`: Tiếng ngân đuôi tần số (chớm hú khi nói lớn).
  - `MUSIC`: Độc tấu nhạc cụ ngân dài (Sáo, Violin, Guitar Lead) — không được phép cắt nhầm.
  - `VOCAL`: Ca sĩ ngân nốt cao kéo dài — không được phép cắt nhầm.

### 3.3. Xuất dữ liệu sau buổi diễn
1. Xuất các rãnh âm thanh từ DAW ra thư mục phiên đo kiểm kèm tệp danh sách Marker (`.csv`).
2. Trên giao diện **Auto Sound Engineer**, nhấn nút **Xuất JSON** hoặc **Xuất CSV** tại bảng *Bộ lọc Notch đang hoạt động* để lưu lại lịch sử các điểm tần số đã can thiệp trong phiên.

---

## 4. Cấu trúc Lưu trữ Phiên Đo kiểm

Mỗi phiên thu thập dữ liệu được lưu thành một thư mục riêng biệt (không đưa các tệp `.wav` dung lượng lớn lên kho mã nguồn Git):

```text
session_YYYYMMDD_HHMMSS_<ten_dia_diem>/
├── session_metadata.json     # Thông tin phòng, dòng mixer, firmware, cấu hình loa
├── markers.csv               # Các mốc thời gian đánh nhãn (HOWL, RING, MUSIC, VOCAL)
├── auto_sound_report.json    # Báo cáo xuất từ ứng dụng Tauri
└── audio_18ch.wav            # Tệp âm thanh đa kênh 48kHz PCM
```

---

## 5. Kịch bản Thu thập Mẫu (15 Phút tại Sân khấu)

| Thời lượng | Nội dung thực hiện | Nhãn đánh dấu |
| :--- | :--- | :--- |
| **3 phút đầu** | Để phòng yên tĩnh, bật toàn bộ micro để thu nền nhiễu tự nhiên (Noise Floor) của phòng và hệ thống. | `NOISE_FLOOR` |
| **4 phút tiếp** | Đọc thử micro ("Một, hai, ba, bốn, sáu, bảy..."), đi lại quanh sân khấu ở mức âm lượng bình thường. | `SPEECH` |
| **4 phút tiếp** | Mở nhạc nền có nhiều nhạc cụ ngân dài (Sáo, Guitar, Synth) và hát thử các câu ngân dài. | `MUSIC` / `VOCAL` |
| **4 phút cuối** | (Chỉ thực hiện khi không có khán giả) Tăng nhẹ fader từng bước nhỏ (+1dB) qua công cụ **Ring-out Wizard** cho đến khi chớm nghe tiếng ngân/hú nhẹ, đánh dấu rồi hạ fader ngay. | `RING` / `HOWL` |
