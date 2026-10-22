"""Lớp giao tiếp trừu tượng và driver mô phỏng (Architectural Interface / Mock Driver) cho dòng mixer Behringer X32 / Midas M32."""

from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional
from auto_sound.core.models import ConnectionState, PEQBand
from auto_sound.mixer.base import MixerDriver
from auto_sound.mixer.parameter_mapper import ParameterMapper

logger = logging.getLogger("auto_sound.mixer.x32")


class X32Client(MixerDriver):
    """Driver mô phỏng giao tiếp Behringer X32 / Midas M32 (Architecture Interface & Mock Driver).

    LƯU Ý: Đây là lớp giao diện chuẩn bị cho lộ trình mở rộng đa mixer (Phase 6).
    Hiện tại hoạt động ở chế độ in-memory mô phỏng cấu trúc 32 kênh, 6 band PEQ và cổng 10023.

    Đặc tính kỹ thuật phần cứng X32/M32:
    - 32 kênh đầu vào micro (/ch/01 đến /ch/32)
    - 16 Aux / Mix Bus (/bus/01 đến /bus/16)
    - 6 Matrix Bus (/mtx/01 đến /mtx/06)
    - Main Stereo LR (/main/st) và Mono/Center (/main/m)
    - Mỗi kênh đầu vào có 6 Band PEQ vật lý (Band 1-6)
    - Cổng OSC UDP mặc định: 10023
    """

    def __init__(
        self,
        ip: str = "192.168.1.100",
        port: int = 10023,
        mapper: Optional[ParameterMapper] = None,
        heartbeat_interval_s: float = 8.0,
        timeout_s: float = 0.5,
    ) -> None:
        self.ip = ip
        self.port = port
        self.mapper = mapper
        self.heartbeat_interval_s = heartbeat_interval_s
        self.timeout_s = timeout_s

        self._state = ConnectionState.DISCONNECTED
        self.mixer_model = "X32"
        self.mixer_name = "Behringer X32"
        self.mixer_firmware = "4.09"
        self.channel_bands_count = 6
        self.total_channels = 32
        self.total_buses = 16

        self._meter_levels = [0.0] * 32
        self._rta_levels = [-80.0] * 100
        self._channel_names: Dict[int, str] = {ch: f"CH {ch:02d}" for ch in range(1, 33)}
        self._channel_mutes: Dict[int, bool] = {ch: False for ch in range(1, 33)}
        self._params_cache: Dict[str, Any] = {}

    def connect(self) -> bool:
        """Thực hiện kết nối và bắt tay với mixer X32."""
        logger.info("Đang kết nối tới Behringer X32/M32 tại %s:%d...", self.ip, self.port)
        self._state = ConnectionState.CONNECTED
        return True

    def disconnect(self) -> None:
        """Ngắt kết nối sạch sẽ."""
        self._state = ConnectionState.DISCONNECTED
        logger.info("Đã ngắt kết nối Behringer X32/M32.")

    def close(self) -> None:
        self.disconnect()

    def get_state(self) -> ConnectionState:
        return self._state

    def get_device_info(self) -> Dict[str, Any]:
        return {
            "ip": self.ip,
            "port": self.port,
            "model": self.mixer_model,
            "name": self.mixer_name,
            "firmware": self.mixer_firmware,
            "state": self._state.value,
            "total_channels": self.total_channels,
            "channel_bands_count": self.channel_bands_count,
        }

    def get_channel_info(self, channel: int) -> Dict[str, Any]:
        return {
            "channel": channel,
            "name": self._channel_names.get(channel, f"CH {channel:02d}"),
            "color": 0,
            "is_muted": self._channel_mutes.get(channel, False),
            "eq_on": True,
        }

    def is_channel_muted(self, channel: int) -> bool:
        return self._channel_mutes.get(channel, False)

    def get_channel_name(self, channel: int) -> str:
        return self._channel_names.get(channel, f"CH {channel:02d}")

    def subscribe_meters(self, enable: bool = True) -> None:
        logger.debug("X32 subscribe_meters: %s", enable)

    def get_meter_levels(self) -> List[float]:
        return list(self._meter_levels)

    def get_rta_levels(self) -> List[float]:
        return list(self._rta_levels)

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
        """Ghi tham số PEQ cho kênh (1-32), bus (1-16) hoặc main stereo trên X32."""
        if target == "main" or channel == 0:
            prefix = f"/main/st/eq/{band}"
        elif target == "bus":
            prefix = f"/bus/{channel:02d}/eq/{band}"
        else:
            prefix = f"/ch/{channel:02d}/eq/{band}"

        self._params_cache[f"{prefix}/f"] = freq_hz
        self._params_cache[f"{prefix}/g"] = gain_db
        self._params_cache[f"{prefix}/q"] = q
        self._params_cache[f"{prefix}/on"] = 1 if is_on else 0

        logger.debug("X32 set_peq %s -> %+.1fdB tại %.0fHz", prefix, gain_db, freq_hz)
        return True

    def get_peq(self, channel: int, band: int, target: str = "ch") -> Optional[PEQBand]:
        if target == "main" or channel == 0:
            prefix = f"/main/st/eq/{band}"
        elif target == "bus":
            prefix = f"/bus/{channel:02d}/eq/{band}"
        else:
            prefix = f"/ch/{channel:02d}/eq/{band}"

        if f"{prefix}/f" not in self._params_cache:
            return PEQBand(channel=channel, band=band, freq_hz=1000.0, gain_db=0.0, q=2.0)

        return PEQBand(
            channel=channel,
            band=band,
            freq_hz=float(self._params_cache.get(f"{prefix}/f", 1000.0)),
            gain_db=float(self._params_cache.get(f"{prefix}/g", 0.0)),
            q=float(self._params_cache.get(f"{prefix}/q", 2.0)),
            is_on=bool(self._params_cache.get(f"{prefix}/on", 1)),
        )
