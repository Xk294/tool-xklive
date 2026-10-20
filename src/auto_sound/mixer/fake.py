"""Bộ giả lập server UDP Behringer XR18 phục vụ kiểm thử và CI."""

from __future__ import annotations
import socket
import struct
import threading
import time
from typing import Any, Dict, Optional, Tuple
from auto_sound.mixer.osc import decode_message, encode_message, OscParseError


class FakeXR18:
    """Server UDP giả lập bàn mixer Behringer XR18 trên cổng nội bộ."""

    def __init__(self, host: str = "127.0.0.1", port: int = 10024, max_clients: int = 4) -> None:
        self.host = host
        self.port = port
        self.max_clients = max_clients
        self.subscription_timeout_s = 10.0

        self._running = False
        self._socket: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Lưu trữ trạng thái các tham số mixer (địa chỉ OSC -> giá trị float)
        self.params: Dict[str, Any] = {}
        # Danh sách client đăng ký /xremote: (ip, port) -> timestamp lần heartbeat cuối
        self.clients: Dict[Tuple[str, int], float] = {}

        self._init_default_params()

    def _init_default_params(self) -> None:
        """Khởi tạo trạng thái EQ mặc định cho 16 kênh và 6 bus."""
        for ch in range(1, 17):
            ch_str = f"{ch:02d}"
            for band in range(1, 5):
                self.params[f"/ch/{ch_str}/eq/{band}/f"] = 0.5  # ~632 Hz
                self.params[f"/ch/{ch_str}/eq/{band}/g"] = 0.5  # 0.0 dB
                self.params[f"/ch/{ch_str}/eq/{band}/q"] = 0.5
                self.params[f"/ch/{ch_str}/eq/{band}/on"] = 1   # Bật

        for bus in range(1, 7):
            for band in range(1, 7):
                self.params[f"/bus/{bus}/eq/{band}/f"] = 0.5
                self.params[f"/bus/{bus}/eq/{band}/g"] = 0.5
                self.params[f"/bus/{bus}/eq/{band}/q"] = 0.5
                self.params[f"/bus/{bus}/eq/{band}/on"] = 1

        for band in range(1, 7):
            self.params[f"/main/st/eq/{band}/f"] = 0.5
            self.params[f"/main/st/eq/{band}/g"] = 0.5
            self.params[f"/main/st/eq/{band}/q"] = 0.5
            self.params[f"/main/st/eq/{band}/on"] = 1

    def start(self) -> None:
        """Khởi động server UDP trong thread chạy ngầm."""
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((self.host, self.port))
        # Lấy cổng thực tế nếu port=0
        self.port = self._socket.getsockname()[1]
        self._socket.settimeout(0.2)

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Dừng server và đóng socket sạch sẽ."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None

    def _prune_expired_clients(self, now: float) -> None:
        """Xóa các client đã hết hạn đăng ký /xremote (>10s không có heartbeat)."""
        expired = [addr for addr, last_seen in self.clients.items() if now - last_seen > self.subscription_timeout_s]
        for addr in expired:
            del self.clients[addr]

    def _run_loop(self) -> None:
        """Vòng lặp chính tiếp nhận và phản hồi các gói tin UDP."""
        while self._running:
            try:
                if not self._socket:
                    break
                data, addr = self._socket.recvfrom(4096)
            except (socket.timeout, BlockingIOError):
                continue
            except Exception:
                if not self._running:
                    break
                continue

            try:
                address, args = decode_message(data)
            except OscParseError:
                continue

            now = time.time()
            with self._lock:
                self._prune_expired_clients(now)
                self._handle_request(address, args, addr, now)

    def _handle_request(self, address: str, args: list[Any], addr: Tuple[str, int], now: float) -> None:
        """Xử lý từng loại lệnh OSC."""
        if address == "/xinfo":
            # Phản hồi thông tin định danh của XR18
            response = encode_message(
                "/xinfo",
                "192.168.1.100",
                "XR18",
                "XR18-FakeSim",
                "1.18",
            )
            self._socket.sendto(response, addr)
            return

        if address == "/xremote":
            # Quản lý giới hạn tối đa 4 client
            if addr in self.clients:
                self.clients[addr] = now
            else:
                if len(self.clients) < self.max_clients:
                    self.clients[addr] = now
                else:
                    # Đã đủ 4 client: bỏ qua client thứ 5
                    pass
            return

        # Yêu cầu đọc meter hoặc RTA
        if address == "/meters/4" or (address == "/meters" and args and args[0] == "/meters/4"):
            # Trả về 100 bins RTA giả lập: 4 byte size header + 100 int16
            rta_bins = [-12000] * 100  # ~ -47 dBFS
            if hasattr(self, "_fake_feedback_bin") and self._fake_feedback_bin is not None:
                rta_bins[self._fake_feedback_bin] = -2560  # ~ -10 dBFS (peak hú)
            raw_blob = struct.pack(">i", 200) + struct.pack("<100h", *rta_bins)
            response = encode_message("/meters/4", raw_blob)
            self._socket.sendto(response, addr)
            return

        if address.startswith("/meters"):
            # Sinh 16 kênh giả lập mức tín hiệu 0.1
            meter_data = struct.pack(f"<{16}f", *([0.1] * 16))
            response = encode_message(address, meter_data)
            self._socket.sendto(response, addr)
            return

        # Nếu có args: đây là lệnh SET tham số
        if len(args) > 0:
            val = args[0]
            self.params[address] = val
            # Broadcast cập nhật trạng thái về tất cả các client /xremote đang hoạt động
            update_msg = encode_message(address, val)
            for client_addr in list(self.clients.keys()):
                try:
                    self._socket.sendto(update_msg, client_addr)
                except Exception:
                    pass
        else:
            # Không có args: đây là lệnh GET tham số (truy vấn)
            if address in self.params:
                current_val = self.params[address]
                response = encode_message(address, current_val)
                self._socket.sendto(response, addr)
