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
from auto_sound.core.models import ConnectionState, PEQBand, CapabilityMap
from auto_sound.mixer.base import MixerDriver
from auto_sound.mixer.osc import decode_message, encode_message, OscParseError
from auto_sound.mixer.parameter_mapper import ParameterMapper


@dataclass(frozen=True)
class ExpectedEcho:
    """Ghi nhớ giá trị tham số hệ thống vừa gửi để nhận diện echo hợp lệ từ mixer."""
    expected_val: Any
    is_int: bool
    expiry: float


def discover_mixers(
    timeout_s: float = 0.6,
    port: int = 10024,
    targets: Optional[List[str]] = None,
) -> List[Dict[str, str]]:
    """Quét mạng LAN bằng OSC UDP Broadcast để tìm kiếm các mixer Behringer/Midas X-Air.
    
    Gửi gói tin /xinfo tới địa chỉ Broadcast và các địa chỉ IP mạng cục bộ phổ biến,
    sau đó phân tích các gói tin phản hồi để xác định IP, Model, Tên và Firmware.
    """
    discovered: List[Dict[str, str]] = []
    seen_ips: Set[str] = set()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    except Exception:
        pass
    sock.settimeout(0.08)

    default_targets = [
        "255.255.255.255",
        "192.168.1.255",
        "192.168.0.255",
        "192.168.1.100",
        "192.168.1.1",
        "127.0.0.1",
    ]
    query_targets = targets or default_targets
    msg = encode_message("/xinfo")

    for tgt in query_targets:
        try:
            sock.sendto(msg, (tgt, port))
        except Exception:
            pass

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            data, (from_ip, _) = sock.recvfrom(2048)
            addr, args = decode_message(data)
            if addr == "/xinfo":
                m_ip = str(args[0]) if len(args) > 0 else from_ip
                if m_ip not in seen_ips:
                    seen_ips.add(m_ip)
                    model = str(args[1]) if len(args) > 1 else "X-Air"
                    name = str(args[2]) if len(args) > 2 else "Mixer"
                    firmware = str(args[3]) if len(args) > 3 else "Unknown"
                    discovered.append({
                        "ip": m_ip,
                        "model": model,
                        "name": name,
                        "firmware": firmware,
                    })
        except (socket.timeout, BlockingIOError):
            time.sleep(0.01)
        except Exception:
            break

    try:
        sock.close()
    except Exception:
        pass

    return discovered


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
        self._meters_subscribed: bool = False
        self.meters_renew_interval_s: float = 7.0
        self._last_meters_renew_time: float = 0.0
        self._last_rta_renew_time: float = 0.0

        # RTT và thống kê giao tiếp OSC
        self.last_rtt_ms: Optional[float] = None
        self._last_ping_tx_time: Optional[float] = None
        self.osc_tx_count: int = 0
        self.osc_rx_count: int = 0
        self.last_error: Optional[str] = None

        # Thông tin định danh thực tế từ mixer
        self.mixer_ip: Optional[str] = None
        self.mixer_model: Optional[str] = None
        self.mixer_name: Optional[str] = None
        self.mixer_firmware: Optional[str] = None
        self.firmware_reason: Optional[str] = None

        # Trạng thái kênh đồng bộ trực tiếp từ X Air
        self._channel_names: Dict[int, str] = {}
        self._channel_colors: Dict[int, int] = {}
        self._channel_mutes: Dict[int, bool] = {}
        self._channel_eq_on: Dict[int, bool] = {}
        self._main_eq_on: bool = True
        self.capability_map: CapabilityMap = CapabilityMap()

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
            self.probe_capabilities(timeout_s=0.15)
            self.sync_mixer_state()
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
            self.osc_tx_count += 1
            return True
        except Exception as e:
            self.last_error = f"Lỗi gửi OSC UDP: {e}"
            return False

    def _send_and_wait_xinfo(self, timeout: float) -> bool:
        """Gửi /xinfo và chờ phản hồi xác thực."""
        evt = threading.Event()
        with self._lock:
            self._pending_queries["/xinfo"] = evt
            self._last_ping_tx_time = time.time()

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

            # Quản lý Heartbeat và Gia hạn RTA/Meters khi CONNECTED
            if curr_state == ConnectionState.CONNECTED:
                # 1. Heartbeat định kỳ
                if now - last_heartbeat >= self.heartbeat_interval_s:
                    self._send_raw(encode_message("/xremote"))
                    last_heartbeat = now

                # 2. Renew RTA luồng /meters/4 (mỗi 7 giây)
                if self._rta_subscribed and (now - self._last_rta_renew_time >= self.meters_renew_interval_s):
                    self._send_raw(encode_message("/meters", "/meters/4"))
                    self._last_rta_renew_time = now

                # 3. Renew Meters luồng /meters/1 (mỗi 7 giây)
                if self._meters_subscribed and (now - self._last_meters_renew_time >= self.meters_renew_interval_s):
                    self._send_raw(encode_message("/meters", "/meters/1"))
                    self._last_meters_renew_time = now

                # 4. Tự động đo ping RTT định kỳ mỗi 5.0s
                if self._last_ping_tx_time is None and (now - (self._last_rx_time or 0.0) < 15.0):
                    if not hasattr(self, "_last_auto_ping") or (now - self._last_auto_ping >= 5.0):
                        self._last_auto_ping = now
                        self._last_ping_tx_time = now
                        self._send_raw(encode_message("/xinfo"))

                # Nếu quá 15 giây không có bất kỳ phản hồi nào từ mixer -> Mất kết nối
                if self._last_rx_time > 0 and (now - self._last_rx_time > 15.0):
                    self._set_state(ConnectionState.RECONNECTING)
                    self.last_rtt_ms = None

            # Quản lý tự kết nối lại trong <= 3s khi RECONNECTING
            elif curr_state == ConnectionState.RECONNECTING:
                if now - last_heartbeat >= self.reconnect_interval_s:
                    self._last_ping_tx_time = now
                    self._send_raw(encode_message("/xinfo"))
                    last_heartbeat = now

    def _handle_incoming_packet(self, data: bytes) -> None:
        """Giải mã gói tin nhận được và cập nhật cache/sự kiện."""
        self.osc_rx_count += 1
        try:
            address, args = decode_message(data)
        except OscParseError as e:
            self.last_error = f"Lỗi giải mã OSC: {e}"
            return

        if address == "/xinfo":
            if self._last_ping_tx_time is not None:
                self.last_rtt_ms = round((time.time() - self._last_ping_tx_time) * 1000.0, 1)
                self._last_ping_tx_time = None

            if len(args) >= 4:
                a0, a1, a2, a3 = str(args[0]), str(args[1]), str(args[2]), str(args[3])
                self.mixer_ip = a0
                # Phân tích thông minh Model vs Name
                if any(prefix in a1.upper() for prefix in ("XR", "MR", "X18", "X32", "M32")):
                    self.mixer_model = a1
                    self.mixer_name = a2
                elif any(prefix in a2.upper() for prefix in ("XR", "MR", "X18", "X32", "M32")):
                    self.mixer_name = a1
                    self.mixer_model = a2
                else:
                    self.mixer_model = a1
                    self.mixer_name = a2
                self.mixer_firmware = a3
                self.firmware_reason = None
            elif len(args) >= 1:
                self.mixer_ip = str(args[0])
                self.firmware_reason = "Mixer phản hồi ít hơn 4 tham số trong /xinfo"
            else:
                self.firmware_reason = "Gói /xinfo không chứa tham số"

            if self.get_state() == ConnectionState.RECONNECTING:
                self._set_state(ConnectionState.CONNECTED)
                self._send_raw(encode_message("/xremote"))
                if self._rta_subscribed:
                    self._last_rta_renew_time = time.time()
                    self._send_raw(encode_message("/meters", "/meters/4"))
                if self._meters_subscribed:
                    self._last_meters_renew_time = time.time()
                    self._send_raw(encode_message("/meters", "/meters/1"))
                self.sync_mixer_state()

            with self._lock:
                evt = self._pending_queries.get("/xinfo")
                if evt:
                    evt.set()
            return

        # Cập nhật metadata cấu hình kênh từ X Air
        if address.startswith("/ch/") and address.endswith("/config/name") and len(args) > 0:
            try:
                ch = int(address.split("/")[2])
                with self._lock:
                    self._channel_names[ch] = str(args[0])
            except Exception:
                pass
        elif address.startswith("/ch/") and address.endswith("/config/color") and len(args) > 0:
            try:
                ch = int(address.split("/")[2])
                with self._lock:
                    self._channel_colors[ch] = int(args[0])
            except Exception:
                pass
        elif address.startswith("/ch/") and address.endswith("/mix/on") and len(args) > 0:
            try:
                ch = int(address.split("/")[2])
                with self._lock:
                    self._channel_mutes[ch] = (int(args[0]) == 0)
            except Exception:
                pass
        elif address.startswith("/ch/") and address.endswith("/eq/on") and len(args) > 0:
            try:
                ch = int(address.split("/")[2])
                with self._lock:
                    self._channel_eq_on[ch] = bool(int(args[0]))
            except Exception:
                pass
        elif address in ("/main/st/eq/on", "/lr/eq/on") and len(args) > 0:
            with self._lock:
                self._main_eq_on = bool(int(args[0]))

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
            is_query_reply = False
            with self._lock:
                self._params_cache[address] = val
                evt = self._pending_queries.get(address)
                if evt:
                    evt.set()
                    is_query_reply = True

            is_expected = self._is_expected_echo(address, val)

            # Nếu thay đổi không do lệnh nội bộ của hệ thống phát sinh -> Kích hoạt callback (soundman chỉnh tay)
            if not is_expected and not is_query_reply and self.on_param_update:
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
        """Ghi toàn bộ tham số PEQ và xác minh từng bước (hỗ trợ kênh, main stereo và bus).
        
        Đồng thời đảm bảo Master EQ của kênh được bật và Band Type được đặt chuẩn PEQ (type 2),
        tránh tình trạng notch filter bị vô hiệu hoặc bị cấu hình sai thành High Cut/Shelf.
        """
        if band <= 0:
            return False

        if target in ("main", "lr") or channel == 0:
            lr_p = self.capability_map.lr_prefix if hasattr(self, "capability_map") else "/lr"
            prefix = f"{lr_p}/eq/{band}"
            master_eq_addr = f"{lr_p}/eq/on"
        elif target == "bus" or channel > 16:
            bus_idx = channel if target == "bus" else (channel - 16)
            prefix = f"/bus/{bus_idx}/eq/{band}"
            master_eq_addr = f"/bus/{bus_idx}/eq/on"
        else:
            if channel <= 0:
                return False
            prefix = f"/ch/{channel:02d}/eq/{band}"
            master_eq_addr = f"/ch/{channel:02d}/eq/on"

        # Đảm bảo Master EQ của kênh được bật trên mixer
        self._write_and_verify(master_eq_addr, 1, is_int=True)

        # Đảm bảo band được chọn ở đúng chế độ Parametric EQ (type 2 trên X Air)
        self._write_and_verify(f"{prefix}/type", 2, is_int=True)

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

    def get_peq_gain_cached(self, channel: int, band: int, target: str = "ch") -> Optional[float]:
        """Truy xuất nhanh giá trị gain_db từ cache tham số nội bộ O(1), không block mạng I/O."""
        if target in ("main", "lr") or channel == 0:
            lr_p = self.capability_map.lr_prefix if hasattr(self, "capability_map") else "/lr"
            addr = f"{lr_p}/eq/{band}/g"
        elif target == "bus" or channel > 16:
            bus_idx = channel if target == "bus" else (channel - 16)
            addr = f"/bus/{bus_idx}/eq/{band}/g"
        else:
            if channel <= 0:
                return None
            addr = f"/ch/{channel:02d}/eq/{band}/g"

        with self._lock:
            g_norm = self._params_cache.get(addr)

        if g_norm is not None:
            return self.mapper.gain.from_float(float(g_norm))
        return None

    def set_fader(self, target: str, index: int, val: float) -> bool:
        """Đặt giá trị fader chuẩn hóa [0.0, 1.0] cho ch, bus, rtn, hoặc lr không block."""
        val_clamped = max(0.0, min(1.0, float(val)))
        if target in ("main", "lr") or index == 0:
            lr_p = self.capability_map.lr_prefix if hasattr(self, "capability_map") else "/lr"
            addr = f"{lr_p}/mix/fader"
        elif target == "bus":
            addr = f"/bus/{index}/mix/fader"
        elif target == "rtn":
            addr = f"/rtn/{index}/mix/fader"
        else:
            addr = f"/ch/{index:02d}/mix/fader"
        self._send_raw(encode_message(addr, val_clamped))
        return True

    def get_peq(self, channel: int, band: int, target: str = "ch") -> Optional[PEQBand]:
        """Đọc tham số PEQ hiện tại và quy đổi sang đơn vị vật lý."""
        if target in ("main", "lr") or channel == 0:
            lr_p = self.capability_map.lr_prefix if hasattr(self, "capability_map") else "/lr"
            prefix = f"{lr_p}/eq/{band}"
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
        type_val = self._query_param_sync(f"{prefix}/type")

        if f_norm is None or g_norm is None or q_norm is None:
            return None

        return PEQBand(
            channel=channel,
            band=band,
            freq_hz=self.mapper.freq.from_float(float(f_norm)),
            gain_db=self.mapper.gain.from_float(float(g_norm)),
            q=self.mapper.q.from_float(float(q_norm)),
            is_on=bool(on_val if on_val is not None else 1),
            filter_type=int(type_val) if type_val is not None else 2,
        )

    def sync_mixer_state(self, num_channels: int = 16) -> None:
        """Truy vấn metadata tên kênh, màu sắc, mute và EQ master từ mixer."""
        lr_p = self.capability_map.lr_prefix if hasattr(self, "capability_map") else "/lr"
        for ch in range(1, num_channels + 1):
            ch_str = f"{ch:02d}"
            self._send_raw(encode_message(f"/ch/{ch_str}/config/name"))
            self._send_raw(encode_message(f"/ch/{ch_str}/config/color"))
            self._send_raw(encode_message(f"/ch/{ch_str}/mix/on"))
            self._send_raw(encode_message(f"/ch/{ch_str}/eq/on"))
        self._send_raw(encode_message(f"{lr_p}/eq/on"))
        self._send_raw(encode_message(f"{lr_p}/mix/fader"))

    def get_device_info(self) -> Dict[str, Any]:
        """Lấy thông tin nhận diện mixer phần cứng và trạng thái truyền thông OSC."""
        with self._lock:
            return {
                "ip": self.mixer_ip or self.ip,
                "port": self.port,
                "model": self.mixer_model or "Behringer XR",
                "name": self.mixer_name or "X-Air Mixer",
                "firmware": self.mixer_firmware or "Unknown",
                "firmware_reason": self.firmware_reason,
                "state": self._state.value,
                "last_rtt_ms": self.last_rtt_ms,
                "osc_tx_count": self.osc_tx_count,
                "osc_rx_count": self.osc_rx_count,
                "last_error": self.last_error,
                "rta_subscribed": self._rta_subscribed,
                "meters_subscribed": self._meters_subscribed,
            }

    def ping(self, timeout_s: float = 0.5) -> Optional[float]:
        """Đo RTT thật với mixer bằng cách gửi /xinfo và chờ phản hồi."""
        t0 = time.time()
        evt = threading.Event()
        with self._lock:
            self._pending_queries["/xinfo"] = evt
            self._last_ping_tx_time = t0
        self._send_raw(encode_message("/xinfo"))
        success = evt.wait(timeout=timeout_s)
        with self._lock:
            self._pending_queries.pop("/xinfo", None)
        if success:
            rtt = round((time.time() - t0) * 1000.0, 1)
            self.last_rtt_ms = rtt
            return rtt
        self.last_rtt_ms = None
        return None

    def probe_channel_bands(self, channel: int = 1, max_bands: int = 6, timeout_s: float = 0.25) -> int:
        """Tự kiểm tra số band PEQ tồn tại trên kênh bằng cách truy vấn /ch/NN/eq/N/f."""
        ch_str = f"{channel:02d}"
        detected = 0
        for b in range(1, max_bands + 1):
            addr = f"/ch/{ch_str}/eq/{b}/f"
            val = self._params_cache.get(addr)
            if val is not None:
                detected = max(detected, b)
            else:
                res = self._query_param_sync(addr, timeout=timeout_s)
                if res is not None:
                    detected = max(detected, b)
        return max(4, detected)

    def get_capability_map(self) -> CapabilityMap:
        """Lấy bản đồ năng lực của mixer."""
        with self._lock:
            return self.capability_map

    def probe_capabilities(self, timeout_s: float = 0.25) -> CapabilityMap:
        """Thăm dò toàn diện năng lực và dialect OSC của mixer (chỉ GET / ĐỌC)."""
        cap = CapabilityMap(
            ip=self.mixer_ip or self.ip,
            port=self.port,
            model=self.mixer_model or "Unknown",
            firmware=self.mixer_firmware or "Unknown",
        )

        # 1. Thăm dò đường dẫn Main LR: /lr vs /main/st
        lr_fader = self._query_param_sync("/lr/mix/fader", timeout=timeout_s)
        if lr_fader is not None:
            cap.lr_prefix = "/lr"
            cap.verified_paths["/lr/mix/fader"] = True
            lr_eq = self._query_param_sync("/lr/eq/1/f", timeout=timeout_s)
            cap.verified_paths["/lr/eq/1/f"] = (lr_eq is not None)
        else:
            main_st_fader = self._query_param_sync("/main/st/mix/fader", timeout=timeout_s)
            main_st_eq = self._query_param_sync("/main/st/eq/on", timeout=timeout_s)
            if main_st_fader is not None or main_st_eq is not None:
                cap.lr_prefix = "/main/st"
                cap.verified_paths["/main/st/mix/fader"] = (main_st_fader is not None)
            else:
                cap.lr_prefix = "/lr"
                cap.verified_paths["/lr/mix/fader"] = False

        # 2. Thăm dò số lượng kênh khả dụng
        if self._query_param_sync("/ch/16/mix/fader", timeout=timeout_s) is not None:
            cap.num_channels = 16
            cap.verified_paths["/ch/16/mix/fader"] = True
            if self._query_param_sync("/ch/18/mix/fader", timeout=timeout_s) is not None:
                cap.num_channels = 18
        elif self._query_param_sync("/ch/12/mix/fader", timeout=timeout_s) is not None:
            cap.num_channels = 12
            cap.verified_paths["/ch/12/mix/fader"] = True
        else:
            cap.num_channels = 16

        # 3. Thăm dò số lượng Bus (Aux)
        if self._query_param_sync("/bus/6/mix/fader", timeout=timeout_s) is not None:
            cap.num_busses = 6
            cap.verified_paths["/bus/6/mix/fader"] = True
        elif self._query_param_sync("/bus/4/mix/fader", timeout=timeout_s) is not None:
            cap.num_busses = 4
            cap.verified_paths["/bus/4/mix/fader"] = True
        elif self._query_param_sync("/bus/2/mix/fader", timeout=timeout_s) is not None:
            cap.num_busses = 2
            cap.verified_paths["/bus/2/mix/fader"] = True
        else:
            cap.num_busses = 6

        # 4. Thăm dò số band EQ trên Channel, Bus và LR
        cap.channel_peq_bands = 4
        if self._query_param_sync("/bus/1/eq/6/f", timeout=timeout_s) is not None:
            cap.bus_peq_bands = 6
        elif self._query_param_sync("/bus/1/eq/4/f", timeout=timeout_s) is not None:
            cap.bus_peq_bands = 4

        lr_b6 = f"{cap.lr_prefix}/eq/6/f"
        if self._query_param_sync(lr_b6, timeout=timeout_s) is not None:
            cap.lr_peq_bands = 6
        else:
            cap.lr_peq_bands = 6

        # 5. Thăm dò Preamp Headamp Gain (/headamp/01/gain)
        headamp_check = self._query_param_sync("/headamp/01/gain", timeout=timeout_s)
        if headamp_check is not None:
            cap.supports_headamp = True
            cap.headamp_prefix = "/headamp"
            cap.verified_paths["/headamp/01/gain"] = True
        else:
            headamp_x32 = self._query_param_sync("/headamp/001/gain", timeout=timeout_s)
            if headamp_x32 is not None:
                cap.supports_headamp = True
                cap.headamp_prefix = "/headamp"
                cap.verified_paths["/headamp/001/gain"] = True
            else:
                cap.supports_headamp = False
                cap.verified_paths["/headamp/01/gain"] = False

        # 6. Thăm dò FX Return (/rtn/1/mix/fader hoặc /rtn/1/mix/on)
        rtn_check = self._query_param_sync("/rtn/1/mix/fader", timeout=timeout_s)
        if rtn_check is not None:
            cap.supports_fx_return = True
            cap.fx_return_prefix = "/rtn"
            cap.verified_paths["/rtn/1/mix/fader"] = True
        else:
            cap.supports_fx_return = False
            cap.verified_paths["/rtn/1/mix/fader"] = False

        # 7. Thăm dò Automixer (X-Air Dugan / config / amix)
        amix_check = self._query_param_sync("/config/amix/enable", timeout=timeout_s)
        if amix_check is not None:
            cap.supports_automix = True
            cap.automix_prefix = "/config/amix"
            cap.verified_paths["/config/amix/enable"] = True
        else:
            amix_alt = self._query_param_sync("/amix/01", timeout=timeout_s)
            if amix_alt is not None:
                cap.supports_automix = True
                cap.automix_prefix = "/amix"
                cap.verified_paths["/amix/01"] = True
            else:
                cap.supports_automix = False
                cap.automix_prefix = None
                cap.verified_paths["/config/amix/enable"] = False

        cap.probe_completed = True
        with self._lock:
            self.capability_map = cap

        return cap

    def get_channel_info(self, channel: int) -> Dict[str, Any]:
        """Lấy metadata cấu hình của kênh (Tên, Màu, Mute, EQ)."""
        with self._lock:
            name = self._channel_names.get(channel, f"CH {channel:02d}")
            color = self._channel_colors.get(channel, 0)
            is_muted = self._channel_mutes.get(channel, False)
            eq_on = self._channel_eq_on.get(channel, True)
            return {
                "channel": channel,
                "name": name,
                "color": color,
                "is_muted": is_muted,
                "eq_on": eq_on,
            }

    def is_channel_muted(self, channel: int) -> bool:
        """Kiểm tra kênh có đang bị MUTE trên mixer không."""
        with self._lock:
            return self._channel_mutes.get(channel, False)

    def get_channel_name(self, channel: int) -> str:
        """Lấy tên hiển thị của kênh trên bàn mixer (ưu tiên tên thật từ mixer, fallback CH NN)."""
        with self._lock:
            return self._channel_names.get(channel, f"CH {channel:02d}")

    def subscribe_meters(self, enable: bool = True) -> None:
        """Đăng ký hoặc hủy nhận luồng meter 16 kênh (/meters/1)."""
        self._meters_subscribed = enable
        if enable:
            self._last_meters_renew_time = time.time()
            self._send_raw(encode_message("/meters", "/meters/1"))

    def get_meter_levels(self) -> List[float]:
        with self._lock:
            return list(self._meter_levels)

    def subscribe_rta(self, enable: bool = True) -> None:
        """Đăng ký hoặc hủy luồng nhận phổ RTA 100-band (/meters/4)."""
        self._rta_subscribed = enable
        if enable:
            self._last_rta_renew_time = time.time()
            self._send_raw(encode_message("/meters", "/meters/4"))

    def get_rta_levels(self) -> List[float]:
        """Lấy danh sách mức năng lượng (dBFS) của 100 dải tần RTA gần nhất."""
        with self._lock:
            return list(self._rta_levels)
