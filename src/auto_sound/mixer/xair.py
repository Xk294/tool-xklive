"""Driver điều khiển Behringer XR18 / Midas MR18 qua giao thức OSC/UDP."""

from __future__ import annotations
from dataclasses import dataclass
import math
import select
import socket
import struct
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set
from auto_sound.core.models import ConnectionState, PEQBand
from auto_sound.mixer.base import MixerDriver
from auto_sound.mixer.osc import decode_message, encode_message, OscParseError
from auto_sound.mixer.parameter_mapper import ParameterMapper


@dataclass(frozen=True)
class ExpectedEcho:
    """Ghi nhớ giá trị tham số hệ thống vừa gửi để nhận diện echo hợp lệ từ mixer."""
    expected_val: Any
    is_int: bool
    expiry: float


class XAirClient(MixerDriver):
    """Client giao tiếp mạng với Behringer XR18 có cơ chế Verified Write và State Machine tự hồi phục."""

    def __init__(
        self,
        ip: str = "127.0.0.1",
        port: int = 10024,
        mapper: Optional[ParameterMapper] = None,
        heartbeat_interval_s: float = 8.0,
        timeout_s: float = 0.5,
        reconnect_interval_s: float = 1.0,
    ) -> None:
        self.ip = ip
        self.port = port
        self.mapper = mapper or ParameterMapper.from_profile({
            "eq": {
                "freq_min_hz": 20.0, "freq_max_hz": 20000.0, "freq_steps": 201,
                "gain_min_db": -15.0, "gain_max_db": 15.0, "gain_steps": 121,
                "q_min": 0.3, "q_max": 10.0, "q_steps": 72,
            }
        })
        self.heartbeat_interval_s = heartbeat_interval_s
        self.timeout_s = timeout_s
        self.reconnect_interval_s = reconnect_interval_s

        self.on_param_update: Optional[Callable[[str, Any], None]] = None
        self.on_rta_update: Optional[Callable[[List[float]], None]] = None
        self._in_flight_writes: Set[str] = set()
        self.echo_ttl_s: float = 2.0
        self._expected_echoes: Dict[str, ExpectedEcho] = {}

        self._state = ConnectionState.DISCONNECTED
        self._socket: Optional[socket.socket] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Cache lưu trữ các tham số nhận được từ mixer (address -> float/int)
        self._params_cache: Dict[str, Any] = {}
        self._pending_queries: Dict[str, threading.Event] = {}

        self._last_rx_time = 0.0
        self._meter_levels: List[float] = [0.0] * 18
        self._rta_levels: List[float] = [-100.0] * 100
        self._rta_subscribed: bool = False

    def get_state(self) -> ConnectionState:
        with self._lock:
            return self._state

    def _set_state(self, new_state: ConnectionState) -> None:
        with self._lock:
            self._state = new_state

    def connect(self) -> bool:
        """Thực hiện kết nối và bắt tay /xinfo."""
        self._set_state(ConnectionState.CONNECTING)
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.setblocking(False)
        except Exception:
            self._set_state(ConnectionState.DISCONNECTED)
            return False

        self._running = True
        self._thread = threading.Thread(target=self._io_loop, daemon=True)
        self._thread.start()

        # Gửi bắt tay /xinfo
        success = self._send_and_wait_xinfo(timeout=self.timeout_s)
        if success:
            self._set_state(ConnectionState.CONNECTED)
            # Gửi ngay heartbeat đầu tiên
            self._send_raw(encode_message("/xremote"))
            return True
        else:
            self._set_state(ConnectionState.RECONNECTING)
            return False

    def disconnect(self) -> None:
        """Ngắt kết nối sạch sẽ."""
        self._running = False
        self._set_state(ConnectionState.DISCONNECTED)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None

    def close(self) -> None:
        self.disconnect()

    def _send_raw(self, data: bytes) -> bool:
        """Gửi gói tin UDP tới mixer."""
        sock = self._socket
        if not sock:
            return False
        try:
            sock.sendto(data, (self.ip, self.port))
            return True
        except Exception:
            return False

    def _send_and_wait_xinfo(self, timeout: float) -> bool:
        """Gửi /xinfo và chờ phản hồi xác thực."""
        evt = threading.Event()
        with self._lock:
            self._pending_queries["/xinfo"] = evt

        self._send_raw(encode_message("/xinfo"))
        success = evt.wait(timeout=timeout)

        with self._lock:
            self._pending_queries.pop("/xinfo", None)
        return success

    def _io_loop(self) -> None:
        """Vòng lặp thu nhận UDP và tự động hồi phục kết nối."""
        last_heartbeat = 0.0

        while self._running:
            now = time.time()
            sock = self._socket
            if not sock:
                break

            # Kiểm tra đọc dữ liệu qua select
            try:
                rlist, _, _ = select.select([sock], [], [], 0.05)
            except Exception:
                break

            if rlist:
                while True:
                    try:
                        data, _ = sock.recvfrom(4096)
                        self._last_rx_time = time.time()
                        self._handle_incoming_packet(data)
                    except (BlockingIOError, socket.error):
                        break
                    except Exception:
                        break

            curr_state = self.get_state()

            # Quản lý Heartbeat khi CONNECTED
            if curr_state == ConnectionState.CONNECTED:
                if now - last_heartbeat >= self.heartbeat_interval_s:
                    self._send_raw(encode_message("/xremote"))
                    if self._rta_subscribed:
                        self._send_raw(encode_message("/meters", "/meters/4"))
                    last_heartbeat = now

                # Nếu quá 15 giây không có bất kỳ phản hồi nào từ mixer -> Mất kết nối
                if self._last_rx_time > 0 and (now - self._last_rx_time > 15.0):
                    self._set_state(ConnectionState.RECONNECTING)

            # Quản lý tự kết nối lại trong <= 3s khi RECONNECTING
            elif curr_state == ConnectionState.RECONNECTING:
                if now - last_heartbeat >= self.reconnect_interval_s:
                    self._send_raw(encode_message("/xinfo"))
                    last_heartbeat = now

    def _handle_incoming_packet(self, data: bytes) -> None:
        """Giải mã gói tin nhận được và cập nhật cache/sự kiện."""
        try:
            address, args = decode_message(data)
        except OscParseError:
            return

        if address == "/xinfo":
            if self.get_state() == ConnectionState.RECONNECTING:
                self._set_state(ConnectionState.CONNECTED)
                self._send_raw(encode_message("/xremote"))
                if self._rta_subscribed:
                    self._send_raw(encode_message("/meters", "/meters/4"))

            with self._lock:
                evt = self._pending_queries.get("/xinfo")
                if evt:
                    evt.set()
            return

        # Giải mã RTA 100-band (/meters/4)
        if address == "/meters/4" and len(args) > 0:
            raw_blob = args[0]
            if isinstance(raw_blob, (bytes, bytearray)):
                offset = 4 if len(raw_blob) >= 204 else 0
                if len(raw_blob) >= offset + 200:
                    try:
                        shorts = struct.unpack_from("<100h", raw_blob, offset)
                        levels_db = [s / 256.0 for s in shorts]
                        with self._lock:
                            self._rta_levels = levels_db
                        if self.on_rta_update:
                            try:
                                self.on_rta_update(levels_db)
                            except Exception:
                                pass
                    except Exception:
                        pass
            return

        if address.startswith("/meters") and len(args) > 0:
            raw_blob = args[0]
            if isinstance(raw_blob, (bytes, bytearray)) and len(raw_blob) >= 4:
                # Đọc số lượng float có thể giải mã
                count = len(raw_blob) // 4
                try:
                    floats = struct.unpack(f"<{count}f", raw_blob[: count * 4])
                    with self._lock:
                        self._meter_levels = list(floats[:18])
                except Exception:
                    pass
            return

        # Cập nhật cache tham số
        if len(args) > 0:
            val = args[0]
            with self._lock:
                self._params_cache[address] = val
                evt = self._pending_queries.get(address)
                if evt:
                    evt.set()

            is_expected = self._is_expected_echo(address, val)

            # Nếu thay đổi không do lệnh nội bộ của hệ thống phát sinh -> Kích hoạt callback (soundman chỉnh tay)
            if not is_expected and self.on_param_update:
                try:
                    self.on_param_update(address, val)
                except Exception:
                    pass

    def register_expected_echo(
        self,
        address: str,
        val: Any,
        is_int: bool = False,
        ttl_s: Optional[float] = None,
    ) -> None:
        """Ghi nhận giá trị tham số kỳ vọng sẽ nhận lại từ mixer (echo /xremote) trong thời hạn TTL."""
        ttl = ttl_s if ttl_s is not None else self.echo_ttl_s
        with self._lock:
            self._expected_echoes[address] = ExpectedEcho(
                expected_val=int(val) if is_int else float(val),
                is_int=is_int,
                expiry=time.time() + ttl,
            )

    def _is_expected_echo(self, address: str, val: Any) -> bool:
        """Xác thực xem gói tin cập nhật nhận được có phải là echo từ chính lệnh của app hay không."""
        now = time.time()
        with self._lock:
            echo = self._expected_echoes.get(address)
            if echo is None:
                return False
            if now > echo.expiry:
                self._expected_echoes.pop(address, None)
                return False

            if echo.is_int:
                try:
                    return int(val) == int(echo.expected_val)
                except (ValueError, TypeError):
                    return False
            else:
                try:
                    return math.isclose(float(val), float(echo.expected_val), abs_tol=1e-3)
                except (ValueError, TypeError):
                    return False

    def _query_param_sync(self, address: str, timeout: float = 0.3) -> Optional[Any]:
        """Truy vấn giá trị tham số đồng bộ có timeout."""
        evt = threading.Event()
        with self._lock:
            self._pending_queries[address] = evt

        self._send_raw(encode_message(address))
        success = evt.wait(timeout=timeout)

        with self._lock:
            self._pending_queries.pop(address, None)
            if success:
                return self._params_cache.get(address)
            return None

    def _write_and_verify(self, address: str, target_val: float, is_int: bool = False) -> bool:
        """Ghi tham số, sau đó đọc lại xác nhận (Verified Write) với cơ chế thử lại tối đa 1 lần."""
        val_to_send = int(target_val) if is_int else float(target_val)
        # Đăng ký expected-echo với TTL để nhận diện bản echo broadcast từ /xremote
        self.register_expected_echo(address, val_to_send, is_int=is_int)

        with self._lock:
            self._in_flight_writes.add(address)
        try:
            for attempt in range(2):
                if attempt > 0:
                    self.register_expected_echo(address, val_to_send, is_int=is_int)
                self._send_raw(encode_message(address, val_to_send))

                # Đọc lại ngay lập tức để xác minh
                readback = self._query_param_sync(address, timeout=self.timeout_s)
                if readback is not None:
                    if is_int:
                        if int(readback) == int(target_val):
                            return True
                    else:
                        if math.isclose(float(readback), float(target_val), abs_tol=1e-3):
                            return True
                time.sleep(0.05)
            return False
        finally:
            with self._lock:
                self._in_flight_writes.discard(address)

    def set_peq(
        self,
        channel: int,
        band: int,
        freq_hz: float,
        gain_db: float,
        q: float,
        is_on: bool = True,
        target: str = "ch",
    ) -> bool:
        """Ghi toàn bộ tham số PEQ và xác minh từng bước (hỗ trợ kênh, main stereo và bus)."""
        if band <= 0:
            return False

        if target == "main" or channel == 0:
            prefix = f"/main/st/eq/{band}"
        elif target == "bus" or channel > 16:
            bus_idx = channel if target == "bus" else (channel - 16)
            prefix = f"/bus/{bus_idx}/eq/{band}"
        else:
            if channel <= 0:
                return False
            prefix = f"/ch/{channel:02d}/eq/{band}"

        # Bắt giá trị vật lý vào nấc rời rạc
        f_snap = self.mapper.freq.snap(freq_hz)
        g_snap = self.mapper.gain.snap(gain_db)
        q_snap = self.mapper.q.snap(q)

        # Chuyển đổi sang chuẩn hóa [0.0, 1.0]
        f_norm = self.mapper.freq.to_float(f_snap)
        g_norm = self.mapper.gain.to_float(g_snap)
        q_norm = self.mapper.q.to_float(q_snap)

        ok_f = self._write_and_verify(f"{prefix}/f", f_norm)
        ok_g = self._write_and_verify(f"{prefix}/g", g_norm)
        ok_q = self._write_and_verify(f"{prefix}/q", q_norm)
        ok_on = self._write_and_verify(f"{prefix}/on", 1 if is_on else 0, is_int=True)

        return ok_f and ok_g and ok_q and ok_on

    def get_peq(self, channel: int, band: int, target: str = "ch") -> Optional[PEQBand]:
        """Đọc tham số PEQ hiện tại và quy đổi sang đơn vị vật lý."""
        if target == "main" or channel == 0:
            prefix = f"/main/st/eq/{band}"
        elif target == "bus" or channel > 16:
            bus_idx = channel if target == "bus" else (channel - 16)
            prefix = f"/bus/{bus_idx}/eq/{band}"
        else:
            if channel <= 0:
                return None
            prefix = f"/ch/{channel:02d}/eq/{band}"

        f_norm = self._query_param_sync(f"{prefix}/f")
        g_norm = self._query_param_sync(f"{prefix}/g")
        q_norm = self._query_param_sync(f"{prefix}/q")
        on_val = self._query_param_sync(f"{prefix}/on")

        if f_norm is None or g_norm is None or q_norm is None:
            return None

        return PEQBand(
            channel=channel,
            band=band,
            freq_hz=self.mapper.freq.from_float(float(f_norm)),
            gain_db=self.mapper.gain.from_float(float(g_norm)),
            q=self.mapper.q.from_float(float(q_norm)),
            is_on=bool(on_val if on_val is not None else 1),
        )

    def subscribe_meters(self, enable: bool = True) -> None:
        if enable:
            self._send_raw(encode_message("/meters", "/meters/1"))

    def get_meter_levels(self) -> List[float]:
        with self._lock:
            return list(self._meter_levels)

    def subscribe_rta(self, enable: bool = True) -> None:
        """Đăng ký hoặc hủy luồng nhận phổ RTA 100-band (/meters/4)."""
        self._rta_subscribed = enable
        if enable:
            self._send_raw(encode_message("/meters", "/meters/4"))

    def get_rta_levels(self) -> List[float]:
        """Lấy danh sách mức năng lượng (dBFS) của 100 dải tần RTA gần nhất."""
        with self._lock:
            return list(self._rta_levels)
