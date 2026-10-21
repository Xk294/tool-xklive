# Kế Hoạch Thu Thập Dữ Liệu Thực Địa & Đánh Giá Detector (Data Collection Protocol)

Tài liệu hướng dẫn kỹ thuật viên âm thanh (Soundman) thực hiện thu thập dữ liệu âm thanh đa kênh thực tế nhằm xây dựng bộ dữ liệu kiểm định chuẩn cho hệ thống Auto Sound Engineer.

---

## 1. Mục Tiêu & Tiêu Chuẩn Bộ Dữ Liệu

Để đảm bảo thuật toán phát hiện hú đạt chuẩn công nghiệp, hạn chế tối đa báo động giả (False Positive) và không bỏ sót hú (False Negative / Recall ≥ 98%), bộ dữ liệu phải đáp ứng số lượng tối thiểu:

1. **≥ 100 mẫu hú thật (Howling Samples):**
   - Đa dạng dải tần: Bass/Low-mid (150 Hz - 500 Hz), Mid (500 Hz - 2 kHz), Treble/High-mid (2 kHz - 8 kHz), Ultra-high (8 kHz - 15 kHz).
   - Đa dạng loại micro: Dynamic (Shure SM58, Beta 58A, Sennheiser e835), Condenser (Rode M2, Shure SM86), Headset/Lavalier.
   - Đa dạng môi trường: Hội trường kín (nhiều vang dội), không gian ngoài trời, phòng tập hẹp.
   - Nguồn phát hồi tiếp: Loa Monitor kiểm âm sàn (Wedge), Loa FOH (Main PA), Loa In-ear (nếu rò rỉ âm học).

2. **≥ 250 mẫu không hú (Non-Howling / Clean Samples):**
   - **Giọng hát ngân dài (Vibrato/Soprano/Belting):** Thử thách lớn nhất gây báo động giả do phổ năng lượng đỉnh tập trung giống hú.
   - **Giọng nói MC/Diễn thuyết:** Năng lượng biến thiên nhanh, plosives (p, b), sibilance (s, x, ch).
   - **Nhạc cụ có hài âm đặc trưng:**
     - Guitar điện Solo/Distortion/Sustain cao.
     - Bộ gõ: Snare, Kick, Hi-hat, Ride/Crash Cymbal (năng lượng tần số cao rất lớn).
     - Sáo trúc, Đàn bầu, Nhạc cụ dân tộc (dễ trùng đỉnh đơn tần).
     - Bass guitar, Synth sub-bass.
   - **Tiếng ồn môi trường:** Khán giả vỗ tay, hò reo, tiếng ồn gió mic, tiếng rút cắm jack (thump).
   - **Nhạc nền phát lại (Backing Track):** Nhạc EDM, Pop, Rock, Bolero phát qua cổng USB 17/18.

---

## 2. Quy Tắc An Toàn Tuyệt Đối Khi Tạo Hú Thật

> ⚠️ **CẢNH BÁO NGUY HIỂM VỀ PHẦN CỨNG & THÍNH GIÁC:**
> Hú ở tần số cao (3 kHz - 12 kHz) với năng lượng liên tục có thể **cháy củ loa Treble (Diaphragm Tweeter)** chỉ trong 2-3 giây do quá nhiệt cuộn dây cone. Hú ở tần số trầm (sub-bass) có thể làm đứt gân loa bass do quá biên độ.

Khi chủ động kích hoạt hú phục vụ lấy mẫu, **BẮT BUỘC** tuân thủ:

1. **Hạ Master Fader (Main/Aux):** Luôn khống chế Fader tổng ở mức vừa đủ nghe rõ (khoảng -20 dB đến -12 dB), không bao giờ thử nghiệm ở mức công suất trình diễn tối đa của dàn loa.
2. **Bảo vệ loa Treble:**
   - Cài đặt sẵn Limiter/Compressor trên Master hoặc Aux Bus với ngưỡng trần (Threshold) an toàn.
   - Ngắt ngay tín hiệu (kéo Fader xuống hoặc bấm Mute) trong vòng **tối đa 2.5 - 3.0 giây** sau khi tiếng hú bùng phát.
3. **Bảo vệ tai người thử nghiệm:** Toàn bộ nhân sự trong phòng phải đeo nút bịt tai bảo hộ hoặc tai nghe chống ồn công nghiệp khi đo kiểm ở cự ly gần loa.
4. **Không thử nghiệm khi có khán giả:** Toàn bộ các buổi thu hú thực tế chỉ được diễn ra trong phiên Soundcheck hoặc buổi diễn tập (Rehearsal) không có công chúng.

---

## 3. Quy Trình Thu Âm Đa Kênh Bằng `tools/record_session.py`

### 3.1. Kết Nối Phần Cứng
1. Cắm dây cáp USB từ cổng USB Audio của mixer Behringer XR18 / MR18 vào máy tính.
2. Kiểm tra Audio Interface trên máy tính nhận diện đúng: `18 in / 18 out, 48000 Hz, 24-bit`.
3. Bật X-Air Edit, vào mục **In/Out -> USB Returns** và **USB Sends**, đảm bảo 16 kênh mic/line và 2 kênh Main L/R được định tuyến trực tiếp vào luồng USB 1-18 (Tap Point: `Analog In` hoặc `Pre-EQ`).

### 3.2. Chạy Lệnh Ghi Âm Kèm Gắn Nhãn
Mở Terminal trên máy tính điều khiển và chạy:
```bash
.venv/bin/python3 tools/record_session.py \
    --output-dir data/recordings \
    --name soundcheck_show_01 \
    --channels 18 \
    --rate 48000
```

### 3.3. Thao Tác Gắn Nhãn Thời Gian Thực (Hotkeys)
Trong khi ghi âm đang chạy, kỹ thuật viên thao tác nhanh bằng bàn phím:
- **Bấm phím `h`:** Đánh dấu bắt đầu xuất hiện tiếng hú (`howl_start`).
- **Bấm phím `e`:** Đánh dấu kết thúc tiếng hú (`howl_end`) ngay sau khi kéo fader dập tắt hú. Hệ thống sẽ tự tính độ dài `duration_s`.
- **Bấm phím `m`:** Đánh dấu đoạn âm nhạc/nhạc cụ sạch không hú (`music`) để làm mẫu huấn luyện âm tính (negative samples).
- **Bấm phím `n`:** Nhập ghi chú bổ sung (ví dụ: *Mic ca sĩ đi lại gần monitor 2*, *Guitar lead solo*).
- **Bấm phím `q`:** Dừng phiên ghi và tự động lưu:
  - `soundcheck_show_01.wav` (WAV 18 kênh, 48kHz, 16-bit)
  - `soundcheck_show_01_labels.csv` (Bảng nhãn mốc thời gian dạng bảng)
  - `soundcheck_show_01_labels.json` (Dữ liệu nhãn định dạng JSON cho pipeline)

---

## 4. Cấu Trúc Thư Mục Lưu Trữ Bộ Dữ Liệu Chuẩn

Sau khi thu thập, các phiên ghi âm được phân loại theo cấu trúc:
```text
data/
└── recordings/
    ├── README.md                          # Ghi chú tổng quan về các buổi diễn
    ├── 20261021_stage_acoustic_hall/     # Buổi diễn tại phòng hoà nhạc
    │   ├── session_01.wav
    │   ├── session_01_labels.csv
    │   └── session_01_labels.json
    ├── 20261022_outdoor_rock_rehearsal/   # Buổi diễn tập nhạc Rock ngoài trời
    │   ├── session_01.wav
    │   ├── session_01_labels.csv
    │   └── session_01_labels.json
    └── benchmark_manifest.json            # Chỉ mục tổng hợp các đoạn audio đã cắt
```

---

## 5. Tiêu Chí Nghiệm Thu Benchmark Detector (Giai đoạn C3 & C4)

Sau khi bộ dữ liệu thực địa đạt đủ số lượng mẫu, chạy pipeline benchmark:
```bash
.venv/bin/pytest tests/test_detector_sim.py -k test_detector_benchmark_real_data -v
```

**Chỉ số bắt buộc để qua Cổng kiểm C:**
- **Recall (Độ nhạy phát hiện hú):** ≥ 98% (với 95% khoảng tin cậy Wilson [95.0% - 100.0%]).
- **False Positive Rate (Báo động giả):** < 0.5% trên tổng số 250 đoạn âm nhạc/giọng hát.
- **Thời gian phát hiện trung bình (Latency):** ≤ 70 ms từ khi biên độ vượt ngưỡng tăng trưởng đến lúc phát cờ hú.
- Nếu không đạt chỉ số trên, **giữ nguyên số liệu trung thực**, không điều chỉnh dữ liệu kiểm thử, chuyển sang phân tích ma trận nhầm lẫn (Confusion Matrix) để tinh chỉnh bộ trích xuất đặc trưng phổ.
