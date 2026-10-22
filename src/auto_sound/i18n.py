"""Module i18n gọn nhẹ cho terminal CLI và backend log."""

from __future__ import annotations
from typing import Any, Dict

_CURRENT_LANG = "vi"

TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "vi": {
        "cli.start_banner": "=== KHỞI ĐỘNG HỆ THỐNG AUTO SOUND ENGINEER ({model}) ===",
        "cli.mock_starting": "[MÔ PHỎNG] Đang khởi động mixer ảo FakeXR18 trên localhost...",
        "cli.discovering": "[DÒ TÌM MIXER] Đang quét tìm mixer X-Air trong mạng LAN...",
        "cli.discovered": "[TỰ ĐỘNG PHÁT HIỆN] Đã tìm thấy mixer {name} ({model}) tại {ip} (FW: {firmware})",
        "cli.discover_default": "[DÒ TÌM] Chưa thấy phản hồi broadcast, kết nối tới IP mặc định: {ip}",
        "cli.adapting_lan_rta": "[TỰ ĐỘNG THÍCH ỨNG] Mixer kết nối là {model} (không có cổng USB 18x18). Tự động chuyển sang chế độ quét phổ LAN RTA và điều khiển Main L/R!",
        "cli.lan_rta_mode": "[CHẾ ĐỘ RTA MẠNG LAN] {model} không có USB đa kênh.\n  -> Kích hoạt tự động quét phổ RTA 100-band và hạ notch PEQ trên Main Stereo L/R.",
        "cli.feedback_alert": "[CẢNH BÁO ĐỎ] {target} chớm hú tại {freq:.1f}Hz! Bấm [SPACE] để duyệt hạ notch.",
        "cli.manual_lock": "[KHÓA AN TOÀN] Kỹ sư chỉnh tay {target} (Band {band}) — Tự động khóa can thiệp trong 10 giây.",
        "cli.notch_applied": "[ĐÃ HẠ NOTCH] {target} | Band {band} | {freq:.1f}Hz | {gain:+.1f}dB | Q={q:.1f}",
        "cli.notch_failed": "[THẤT BẠI] Gửi lệnh PEQ tới mixer không nhận được xác nhận!",
        "cli.network_error": "[LỖI MẠNG] Không thể gửi lệnh: Mixer chưa kết nối!",
        "cli.panic": "[PANIC] Đang làm rỗng hàng đợi và hoàn tác toàn bộ notch về 0 dB...",
        "cli.stopped": "Hệ thống đã dừng an toàn.",
        "cli.no_feedback": "[THÔNG BÁO] Không có cảnh báo hú nào đang chờ duyệt.",
        "cli.status_line": "Trạng thái: {state} | Chế độ: {mode} ({target_mode}) | Notch: {active_count} | Hàng đợi: {queue_count} | Phím: [SPACE]=Duyệt, [P]=PANIC, [Q]=Thoát  ",
        "cli.web_running": "⚡ ĐANG CHẠY NUXT 4 COMPANION UI TẠI: {url}\n👉 Mở trình duyệt web tại: {url}",
        "cli.web_tip": "💡 Mẹo: Để mở giao diện Web Nuxt 4 trực quan, chạy: auto-sound --web (hoặc: ./run_ui.py)\n",
        "run_ui.scanning": "🔍 Đang quét tìm kiếm mixer Behringer/Midas X-Air trong mạng cục bộ...",
        "run_ui.no_hardware": "💡 Không phát hiện mixer vật lý kết nối qua mạng LAN.\n👉 Tự động bật chế độ MÔ PHỎNG (--mock) với RTA và Meter ảo để trải nghiệm giao diện.",
        "run_ui.found_hardware": "✅ Đã tìm thấy mixer phần cứng: {desc} tại {ip}.",
    },
    "en": {
        "cli.start_banner": "=== STARTING AUTO SOUND ENGINEER ({model}) ===",
        "cli.mock_starting": "[MOCK] Starting virtual mixer FakeXR18 on localhost...",
        "cli.discovering": "[DISCOVERING MIXER] Scanning for X-Air mixers on LAN...",
        "cli.discovered": "[AUTO-DETECTED] Found mixer {name} ({model}) at {ip} (FW: {firmware})",
        "cli.discover_default": "[DISCOVER] No broadcast response, connecting to default IP: {ip}",
        "cli.adapting_lan_rta": "[AUTO-ADAPT] Connected mixer is {model} (no 18x18 USB). Switching to LAN RTA scan mode and Main L/R control!",
        "cli.lan_rta_mode": "[LAN RTA MODE] {model} lacks multichannel USB.\n  -> Automatically scanning 100-band RTA and applying PEQ notches on Main Stereo L/R.",
        "cli.feedback_alert": "[RED ALERT] {target} feedback detected at {freq:.1f}Hz! Press [SPACE] to approve notch.",
        "cli.manual_lock": "[SAFETY LOCK] Manual override detected on {target} (Band {band}) — Automatically locked for 10 seconds.",
        "cli.notch_applied": "[NOTCH APPLIED] {target} | Band {band} | {freq:.1f}Hz | {gain:+.1f}dB | Q={q:.1f}",
        "cli.notch_failed": "[FAILED] Sending PEQ command to mixer received no confirmation!",
        "cli.network_error": "[NETWORK ERROR] Cannot send command: Mixer not connected!",
        "cli.panic": "[PANIC] Draining command queue and rolling back all notches to 0 dB...",
        "cli.stopped": "System stopped safely.",
        "cli.no_feedback": "[NOTICE] No pending feedback alerts awaiting review.",
        "cli.status_line": "Status: {state} | Mode: {mode} ({target_mode}) | Notches: {active_count} | Queue: {queue_count} | Keys: [SPACE]=Approve, [P]=PANIC, [Q]=Quit  ",
        "cli.web_running": "⚡ RUNNING NUXT 4 COMPANION UI AT: {url}\n👉 Open browser at: {url}",
        "cli.web_tip": "💡 Tip: To open the Nuxt 4 Web UI, run: auto-sound --web (or: ./run_ui.py)\n",
        "run_ui.scanning": "🔍 Scanning for Behringer/Midas X-Air mixers on local network...",
        "run_ui.no_hardware": "💡 No physical mixer detected on LAN.\n👉 Automatically enabling SIMULATION (--mock) with virtual RTA and Meters for UI testing.",
        "run_ui.found_hardware": "✅ Found hardware mixer: {desc} at {ip}.",
    },
}


def set_language(lang: str) -> None:
    """Thiết lập ngôn ngữ hiển thị CLI: 'vi' hoặc 'en'."""
    global _CURRENT_LANG
    if lang in ("vi", "en"):
        _CURRENT_LANG = lang


def get_language() -> str:
    return _CURRENT_LANG


def t(key: str, **kwargs: Any) -> str:
    """Dịch chuỗi theo ngôn ngữ hiện tại kèm nội suy tham số."""
    catalog = TRANSLATIONS.get(_CURRENT_LANG, TRANSLATIONS["vi"])
    tmpl = catalog.get(key)
    if tmpl is None:
        tmpl = TRANSLATIONS["vi"].get(key, key)
    if kwargs:
        try:
            return tmpl.format(**kwargs)
        except Exception:
            return tmpl
    return tmpl
