#!/usr/bin/env python3
"""Auto Sound Engineer - Web UI Companion Launcher.

Khởi chạy nhanh chóng giao diện Nuxt 4 / Vue 3 trên trình duyệt mặc định.
Tự động kích hoạt môi trường ảo .venv và tự động chuyển sang chế độ mô phỏng (--mock)
nếu không phát hiện mixer Behringer XR18 kết nối vật lý.
"""

import os
import sys
from pathlib import Path

# Đảm bảo sử dụng đúng môi trường ảo .venv nếu có
venv_python = Path(__file__).resolve().parent / ".venv" / "bin" / "python3"
if venv_python.exists() and sys.executable != str(venv_python):
    os.execv(str(venv_python), [str(venv_python), *sys.argv])

# Thêm src vào sys.path để import trực tiếp
src_dir = Path(__file__).resolve().parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

import socket
from auto_sound.app.cli import main
from auto_sound.mixer.xair import discover_mixers


def find_online_mixer(timeout_s: float = 0.6) -> tuple[bool, str, str]:
    """Quét tìm mixer X-Air phần cứng trong mạng LAN."""
    found = discover_mixers(timeout_s=timeout_s)
    if found:
        m = found[0]
        return True, m["ip"], f"{m['name']} ({m['model']}, FW: {m['firmware']})"

    # Thử kết nối trực tiếp IP mặc định
    for test_ip in ("192.168.1.100", "192.168.1.1"):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(0.15)
            # Gửi thông điệp OSC /xinfo chuẩn
            sock.sendto(b"/xinfo\x00\x00,\x00\x00\x00", (test_ip, 10024))
            data, _ = sock.recvfrom(512)
            sock.close()
            if len(data) > 0:
                return True, test_ip, f"Mixer tại {test_ip}"
        except Exception:
            pass

    return False, "", ""


if __name__ == "__main__":
    args = sys.argv[1:]

    # Xác định ngôn ngữ từ CLI args
    lang = "vi"
    if "--lang" in args:
        idx = args.index("--lang")
        if idx + 1 < len(args):
            lang = args[idx + 1]
    from auto_sound.i18n import set_language, t
    set_language(lang)

    # Tự động thêm cờ --web nếu chưa có
    if "--web" not in args:
        args.append("--web")

    # Nếu người dùng chưa chỉ định --mock, kiểm tra kết nối tới mixer
    if "--mock" not in args and "--no-mock" not in args:
        print(t("run_ui.scanning"))
        available, mixer_ip, desc = find_online_mixer()
        if not available:
            print(t("run_ui.no_hardware"))
            args.append("--mock")
        else:
            print(t("run_ui.found_hardware", desc=desc, ip=mixer_ip))
            if "--ip" not in args:
                args.extend(["--ip", mixer_ip])

    if "--no-mock" in args:
        args.remove("--no-mock")

    sys.argv = [sys.argv[0]] + args
    main()
