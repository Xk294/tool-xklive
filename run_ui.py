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


def is_mixer_available(ip: str = "192.168.1.1", port: int = 10024, timeout: float = 0.2) -> bool:
    """Kiểm tra nhanh xem mixer phần cứng có đang online không."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        # Gửi truy vấn /xinfo
        sock.sendto(b"/xinfo\x00\x00", (ip, port))
        data, _ = sock.recvfrom(512)
        sock.close()
        return len(data) > 0
    except Exception:
        return False


if __name__ == "__main__":
    args = sys.argv[1:]

    # Tự động thêm cờ --web nếu chưa có
    if "--web" not in args:
        args.append("--web")

    # Nếu người dùng chưa chỉ định --mock, kiểm tra kết nối tới mixer
    if "--mock" not in args and "--no-mock" not in args:
        print("🔍 Đang tìm kiếm mixer Behringer XR18 trong mạng cục bộ...")
        if not is_mixer_available():
            print("💡 Không phát hiện mixer vật lý kết nối tại 192.168.1.1:10024.")
            print("👉 Tự động bật chế độ MÔ PHỎNG (--mock) với RTA và Meter ảo để trải nghiệm giao diện.")
            args.append("--mock")
        else:
            print("✅ Đã tìm thấy mixer phần cứng XR18.")

    if "--no-mock" in args:
        args.remove("--no-mock")

    sys.argv = [sys.argv[0]] + args
    main()
