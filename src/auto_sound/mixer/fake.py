"""Bộ giả lập server UDP Behringer XR18 phục vụ kiểm thử và CI."""

from __future__ import annotations
import math
import socket
import struct
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from auto_sound.mixer.osc import decode_message, encode_message, OscParseError


class FakeXR18:
    """Server UDP giả lập bàn mixer Behringer XR18 trên cổng nội bộ.

    Mô phỏng đầy đủ:
    - Phản hồi /xinfo với model, name, firmware
    - Quản lý /xremote subscription (tối đa max_clients)
    - Push RTA /meters/4 định kỳ (~10 FPS) tới clients đã đăng ký
    - Push meter /meters/1 (16 kênh, mức ảo sinh động)
    - GET/SET tham số EQ, kênh, tên kênh
    - Tín hiệu ảo có thể inject tiếng hú qua set_fake_feedback_bin()
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 10024, max_clients: int = 4) -> None:
        self.host = host
        self.port = port
        self.max_clients = max_clients
        self.subscription_timeout_s = 10.0

        self._running = False
        self._socket: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._push_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Lưu trữ trạng thái các tham số mixer (địa chỉ OSC -> giá trị float)
        self.params: Dict[str, Any] = {}
        # Danh sách client đăng ký /xremote: (ip, port) -> timestamp lần heartbeat cuối
        self.clients: Dict[Tuple[str, int], float] = {}

        # Bin tần số hú ảo (None = không có hú)
        self._fake_feedback_bin: Optional[int] = None
        # Bộ đếm khung thời gian cho tín hiệu sinh động
        self._frame_counter: int = 0

        self._init_default_params()

    def _init_default_params(self) -> None:
        """Khởi tạo trạng thái EQ và tham số điều khiển mặc định cho 16 kênh và 6 bus."""
        for ch in range(1, 17):
            ch_str = f"{ch:02d}"
            # Tên kênh mặc định từ mixer thật (ví dụ Mic 1, Mic 2... hoặc do người dùng đặt)
            self.params[f"/ch/{ch_str}/config/name"] = f"Mic {ch}"
            self.params[f"/ch/{ch_str}/config/color"] = (ch % 15) + 1
            self.params[f"/ch/{ch_str}/mix/on"] = 1  # 1 = Unmuted, 0 = Muted
            self.params[f"/ch/{ch_str}/mix/fader"] = 0.75
            self.params[f"/ch/{ch_str}/eq/on"] = 1   # Master EQ enabled
            for band in range(1, 7):
                self.params[f"/ch/{ch_str}/eq/{band}/type"] = 2  # PEQ
                self.params[f"/ch/{ch_str}/eq/{band}/f"] = 0.5  # ~632 Hz
                self.params[f"/ch/{ch_str}/eq/{band}/g"] = 0.5  # 0.0 dB
                self.params[f"/ch/{ch_str}/eq/{band}/q"] = 0.5
                self.params[f"/ch/{ch_str}/eq/{band}/on"] = 1

        for bus in range(1, 7):
            self.params[f"/bus/{bus}/eq/on"] = 1
            for band in range(1, 7):
                self.params[f"/bus/{bus}/eq/{band}/type"] = 2
                self.params[f"/bus/{bus}/eq/{band}/f"] = 0.5
                self.params[f"/bus/{bus}/eq/{band}/g"] = 0.5
                self.params[f"/bus/{bus}/eq/{band}/q"] = 0.5
                self.params[f"/bus/{bus}/eq/{band}/on"] = 1

        self.params["/main/st/eq/on"] = 1
        for band in range(1, 7):
            self.params[f"/main/st/eq/{band}/type"] = 2
            self.params[f"/main/st/eq/{band}/f"] = 0.5
            self.params[f"/main/st/eq/{band}/g"] = 0.5
            self.params[f"/main/st/eq/{band}/q"] = 0.5
            self.params[f"/main/st/eq/{band}/on"] = 1

        # X-Air Native Main LR (/lr)
        self.params["/lr/mix/on"] = 1
        self.params["/lr/mix/fader"] = 0.75
        self.params["/lr/eq/on"] = 1
        for band in range(1, 7):
            self.params[f"/lr/eq/{band}/type"] = 2
            self.params[f"/lr/eq/{band}/f"] = 0.5
            self.params[f"/lr/eq/{band}/g"] = 0.5
            self.params[f"/lr/eq/{band}/q"] = 0.5
            self.params[f"/lr/eq/{band}/on"] = 1

        # Preamp Headamp Gain (1-16)
        for ch in range(1, 17):
            self.params[f"/headamp/{ch:02d}/gain"] = 0.5

        # FX Return (rtn 1-4)
        for rtn in range(1, 5):
            self.params[f"/rtn/{rtn}/mix/on"] = 1
            self.params[f"/rtn/{rtn}/mix/fader"] = 0.75

    def set_fake_feedback_bin(self, bin_idx: Optional[int]) -> None:
        """Inject tiếng hú ảo tại bin RTA chỉ định (None = tắt hú)."""
        with self._lock:
            self._fake_feedback_bin = bin_idx

    def _build_rta_blob(self) -> bytes:
        """Tạo blob RTA 100 bin sinh động (noise nền + đỉnh hú nếu có)."""
        t = self._frame_counter * 0.1
        rta_bins: List[int] = []
        for i in range(100):
            # Noise nền nhấp nhô tự nhiên: ~-50 dBFS ± 6 dBFS
            base = -12800 + int(1500 * math.sin(t * 0.3 + i * 0.07))
            rta_bins.append(base)

        # Inject đỉnh hú ảo nếu được kích hoạt
        fb_bin = self._fake_feedback_bin
        if fb_bin is not None and 0 <= fb_bin < 100:
            rta_bins[fb_bin] = -2560  # ~-10 dBFS

        # 4 byte size (200 = 100*2 bytes) + 100 int16 little-endian
        return struct.pack("<i", 200) + struct.pack("<100h", *rta_bins)

    def _build_meter_blob(self) -> bytes:
        """Tạo blob meter 16 kênh float32 sinh động (mức tín hiệu nhấp nhô)."""
        t = self._frame_counter * 0.1
        levels: List[float] = [
            0.15 + 0.10 * abs(math.sin(t * 0.5 + ch * 0.4))
            for ch in range(16)
        ]
        return struct.pack(f"<{16}f", *levels)

    def _push_meters_loop(self) -> None:
        """Push RTA + meter định kỳ ~10 FPS tới clients đăng ký /xremote."""
        while self._running:
            time.sleep(0.1)
            with self._lock:
                if not self.clients or not self._socket:
                    self._frame_counter += 1
                    continue

                now = time.time()
                expired = [a for a, ts in self.clients.items() if now - ts > self.subscription_timeout_s]
                for a in expired:
                    del self.clients[a]

                if not self.clients:
                    self._frame_counter += 1
                    continue

                rta_msg = encode_message("/meters/4", self._build_rta_blob())
                meter_msg = encode_message("/meters/1", self._build_meter_blob())
                for client_addr in list(self.clients.keys()):
                    try:
                        self._socket.sendto(rta_msg, client_addr)
                        self._socket.sendto(meter_msg, client_addr)
                    except Exception:
                        pass

                self._frame_counter += 1

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
        self._push_thread = threading.Thread(target=self._push_meters_loop, daemon=True)
        self._push_thread.start()

    def stop(self) -> None:
        """Dừng server và đóng socket sạch sẽ."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self._push_thread and self._push_thread.is_alive():
            self._push_thread.join(timeout=1.0)
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
            response = encode_message("/xinfo", "192.168.1.100", "XR18", "XR18-FakeSim", "1.18")
            self._socket.sendto(response, addr)
            return

        if address == "/xremote":
            if addr in self.clients:
                self.clients[addr] = now
            elif len(self.clients) < self.max_clients:
                self.clients[addr] = now
            # Đã đủ max_clients: bỏ qua client mới
            return

        # Yêu cầu RTA — trả tức thì; push loop cũng push định kỳ
        if address == "/meters/4" or (address == "/meters" and args and args[0] == "/meters/4"):
            self._socket.sendto(encode_message("/meters/4", self._build_rta_blob()), addr)
            return

        if address.startswith("/meters"):
            self._socket.sendto(encode_message(address, self._build_meter_blob()), addr)
            return

        # SET tham số
        if len(args) > 0:
            val = args[0]
            self.params[address] = val
            update_msg = encode_message(address, val)
            for client_addr in list(self.clients.keys()):
                try:
                    self._socket.sendto(update_msg, client_addr)
                except Exception:
                    pass
        else:
            # GET tham số
            if address in self.params:
                self._socket.sendto(encode_message(address, self.params[address]), addr)
