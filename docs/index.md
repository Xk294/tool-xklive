# Documentation Index — Auto Sound Engineer (tool xklive)

Trung tâm điều hướng tài liệu kỹ thuật, kế hoạch và quy chuẩn dự án **Auto Sound Engineer** (Hệ thống chống hú tự động theo thời gian thực cho Behringer X-Air & Midas M-Air qua giao thức OSC UDP 10024).

---

## 1. Tài liệu Tổng quan & Báo cáo
- [README.md](../README.md): Hướng dẫn cài đặt, khởi chạy CLI/Web, thông số kỹ thuật và luồng hoạt động.
- [BAO_CAO_DU_AN.md](../BAO_CAO_DU_AN.md): Báo cáo kiến trúc hệ thống toàn diện (DSP Engine, Safety Controller, OSC Client, Nuxt 4 Companion, Benchmark & Khuyến nghị vận hành).

---

## 2. Kế hoạch & Lộ trình (Plans)
- [docs/plan/PLAN_AUTO_SOUND_ENGINE.md](plan/PLAN_AUTO_SOUND_ENGINE.md): Bản kế hoạch chi tiết triển khai Auto Sound Engine từ Giai đoạn 0 đến Giai đoạn 6.
- `docs/plan/done/`: Lưu trữ các kế hoạch và mốc milestone đã hoàn thành.

---

## 3. Tài liệu Kỹ thuật & Thực nghiệm
- [docs/HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md): Quy trình kiểm chứng phần cứng thực tế trên mixer XR12/XR16/XR18 và MR12/MR18 (xinfo, client limit, roundtrip latency, quantization, RTA, echo window, rate limit).
- [docs/API.md](API.md): Đặc tả API REST v1 & WebSocket cho Web Companion UI.
- [docs/DATA_COLLECTION.md](DATA_COLLECTION.md): Quy trình thu thập dữ liệu âm thanh đa kênh USB 18x18 và gắn nhãn dataset.
- [docs/SBOM.md](SBOM.md): Kiểm toán bản quyền phần mềm (100% Permissive: MIT, BSD, Apache-2.0, Unlicense; nghiêm cấm GPL/AGPL).

---

## 4. Quy chuẩn & Luật phát triển (Rules)
- `docs/rule/`: Thư mục chứa các hướng dẫn và quy chuẩn mở rộng cho dự án.
- [GEMINI.md](../GEMINI.md): Guardrail và Bootstrap configuration cho Gemini/Antigravity agents.
- [CLAUDE.md](../CLAUDE.md): Stack overview và lệnh kiểm thử verification chuẩn.
- [.github/instructions/RULE.instructions.md](../.github/instructions/RULE.instructions.md): Nguyên tắc giao tiếp, triết lý lập trình và bất biến an toàn thời gian thực.
