# BẢN KÊ KHAI NGUYÊN VẬT LIỆU PHẦN MỀM (SBOM - SOFTWARE BILL OF MATERIALS)
## Dự án: Auto Sound Engineer (Pha 2)
**Ngày cập nhật:** 21/10/2026  
**Công cụ kiểm toán:** `pip-licenses --format=markdown` (Python 3.11)

---

## 1. NGUYÊN TẮC PHÁP LÝ & BẢN QUYỀN

1. **Tuyệt đối không sử dụng Copyleft lây nhiễm:** Cấm hoàn toàn mã nguồn mang giấy phép GPLv2, GPLv3, AGPL trong toàn bộ mã nguồn lõi và thư viện runtime phân phối.
2. **100% Giấy phép tự do thương mại (Permissive):** Chỉ chấp nhận các giấy phép MIT, BSD-2-Clause, BSD-3-Clause, Apache-2.0, Unlicense, MIT-0, Zlib, CC0.
3. **Phân tách rạch ròi Runtime vs Dev:** Các thư viện chỉ phục vụ kiểm thử (như `hypothesis` mang giấy phép MPL-2.0) bắt buộc phải nằm trong nhóm `optional-dependencies.dev`, tuyệt đối không lọt vào `dependencies` của gói cài đặt runtime sản phẩm.
4. **Không sử dụng FFTW:** Dự án sử dụng PocketFFT (tích hợp sẵn trong SciPy, giấy phép BSD-3-Clause) để tránh khoản phí bản quyền $12,500 của FFTW cho phần mềm thương mại đóng mã nguồn.

---

## 2. BẢNG KIỂM TOÁN DANH MỤC PHỤ THUỘC (PIP-LICENSES)

| Gói phụ thuộc | Phiên bản | Giấy phép khai báo | Phân loại | Mục đích sử dụng | Trạng thái thẩm định |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **auto-sound** | 0.1.0 | MIT | Lõi sản phẩm | Mã nguồn chính của hệ thống | ✅ Sạch (Bản quyền tác giả) |
| **numpy** | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | Runtime | Xử lý mảng số học đa chiều và đại số tuyến tính | ⚠️ Cần xác minh thành phần wheel (Xem mục 3) |
| **scipy** | 1.17.1 | BSD License (BSD-3-Clause) | Runtime | Bộ lọc median filter, biquad filter, PocketFFT | ⚠️ Cần xác minh thành phần wheel (Xem mục 3) |
| **python-osc** | 1.10.2 | Freely Distributable (The Unlicense) | Runtime | Giao thức mã hóa/giải mã OSC qua UDP | ✅ Sạch (Public Domain) |
| **sounddevice** | 0.5.6 | MIT | Runtime | Giao tiếp PortAudio thu nhận âm thanh USB | ✅ Sạch (MIT) |
| **cffi** | 2.1.1 | MIT-0 | Runtime (Chuyển tiếp) | C Foreign Function Interface cho sounddevice | ✅ Sạch (MIT-0) |
| **pycparser** | 3.11 | BSD-3-Clause | Runtime (Chuyển tiếp) | Bộ phân tích cú pháp C cho cffi | ✅ Sạch (BSD-3-Clause) |
| **Pygments** | 2.21.0 | BSD-2-Clause | Dev / Tool | Định dạng cú pháp code khi xuất tài liệu | ✅ Sạch (BSD-2-Clause) |
| **pytest** | 9.1.1 | MIT | Dev | Framework kiểm thử tự động | ✅ Sạch (Chỉ dùng test) |
| **iniconfig** | 2.3.1 | MIT | Dev (Chuyển tiếp) | Đọc file cấu hình cho pytest | ✅ Sạch (Chỉ dùng test) |
| **packaging** | 26.3 | Apache-2.0 OR BSD-2-Clause | Dev (Chuyển tiếp) | Xử lý phiên bản gói cho pytest | ✅ Sạch (Chỉ dùng test) |
| **pluggy** | 1.7.0 | MIT License | Dev (Chuyển tiếp) | Quản lý plugin cho pytest | ✅ Sạch (Chỉ dùng test) |
| **sortedcontainers** | 2.4.0 | Apache-2.0 | Dev (Chuyển tiếp) | Cấu trúc dữ liệu cho hypothesis | ✅ Sạch (Chỉ dùng test) |
| **hypothesis** | 6.170.5 | **MPL-2.0** | **Dev (Chỉ dùng test)** | Kiểm thử bất biến Property-based testing | ⚠️ **LƯU Ý:** Mang giấy phép Weak Copyleft MPL-2.0. Không được đóng gói vào runtime binary. |

---

## 3. XÁC MINH THỦ CÔNG THÀNH PHẦN KÈM THEO WHEEL (NUMPY & SCIPY)

Các wheel nhị phân cài đặt sẵn của NumPy và SciPy tải từ PyPI thường đóng gói sẵn một số thư viện nhị phân C/Fortran:

1. **OpenBLAS (kèm trong wheel NumPy & SciPy):**
   - Giấy phép: **BSD-3-Clause**.
   - Nghĩa vụ: Giữ nguyên thông báo bản quyền của OpenBLAS trong tài liệu hướng dẫn sản phẩm khi phân phối binary.
   - Kết luận: **Tương thích hoàn toàn với phân phối thương mại.**

2. **PocketFFT (kèm trong SciPy):**
   - Giấy phép: **BSD-3-Clause** (Tác giả: Martin Reinecke).
   - Nghĩa vụ: Giữ thông báo bản quyền BSD.
   - Kết luận: **Hợp pháp thương mại 100%, không bị dính GPL như FFTW.**

3. **PortAudio (kèm trong sounddevice wheel):**
   - Giấy phép: **PortAudio License (Tương tự MIT / BSD)**.
   - Kết luận: **Hợp pháp thương mại.**

---

## 4. KẾT LUẬN KIỂM TOÁN

- **Không có bất kỳ thư viện GPL, AGPL, LGPL nào trong danh mục Runtime.**
- `hypothesis` (MPL-2.0) được cô lập hoàn toàn trong môi trường phát triển `dev`, chỉ chạy khi thực thi lệnh `pytest` và không nằm trong dependencies đóng gói.
- Sản phẩm đáp ứng đầy đủ điều kiện pháp lý để đóng gói mã nguồn thương mại độc lập.
