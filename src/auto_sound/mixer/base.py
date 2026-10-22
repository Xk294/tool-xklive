"""Giao diện trừu tượng MixerDriver cho mọi dòng mixer kỹ thuật số."""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional, List
from auto_sound.core.models import ConnectionState, PEQBand


class MixerDriver(ABC):
    """Giao diện trừu tượng cơ bản điều khiển mixer."""

    @abstractmethod
    def connect(self) -> bool:
        """Thực hiện kết nối và bắt tay (handshake) với mixer."""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Ngắt kết nối sạch và giải phóng tài nguyên mạng."""
        pass

    @abstractmethod
    def get_state(self) -> ConnectionState:
        """Lấy trạng thái kết nối hiện tại của mixer driver."""
        pass

    @abstractmethod
    def set_peq(
        self,
        channel: int,
        band: int,
        freq_hz: float,
        gain_db: float,
        q: float,
        is_on: bool = True,
    ) -> bool:
        """Ghi tham số PEQ cho một kênh và band chỉ định. Có kiểm tra xác nhận."""
        pass

    @abstractmethod
    def get_peq(self, channel: int, band: int) -> Optional[PEQBand]:
        """Đọc trạng thái tham số PEQ hiện tại của kênh và band."""
        pass

    @abstractmethod
    def subscribe_meters(self, enable: bool = True) -> None:
        """Bật/tắt nhận luồng meter nhị phân thời gian thực."""
        pass

    @abstractmethod
    def get_meter_levels(self) -> List[float]:
        """Lấy mảng mức tín hiệu meter mới nhất (giá trị chuẩn hóa [0.0, 1.0])."""
        pass

    def get_rta_levels(self) -> List[float]:
        """Lấy mảng mức năng lượng 100 bin RTA gần nhất."""
        return [-80.0] * 100

    def ping(self, timeout_s: float = 0.5) -> Optional[float]:
        """Đo RTT thật với mixer (ms)."""
        return None

    def probe_channel_bands(self, channel: int = 1, max_bands: int = 6) -> int:
        """Kiểm tra số band PEQ tồn tại trên kênh."""
        return 4

    @abstractmethod
    def close(self) -> None:
        """Đóng hoàn toàn driver."""
        pass

    def get_device_info(self) -> dict:
        """Lấy thông tin thiết bị (Model, Tên, Firmware, IP)."""
        return {"model": "Generic", "name": "Mixer", "firmware": "Unknown", "ip": "127.0.0.1"}

    def get_channel_info(self, channel: int) -> dict:
        """Lấy thông tin kênh (Tên, Màu, Trạng thái Mute)."""
        return {"channel": channel, "name": f"CH {channel:02d}", "color": 0, "is_muted": False, "eq_on": True}

    def is_channel_muted(self, channel: int) -> bool:
        """Kiểm tra kênh có đang bị Mute trên mixer hay không."""
        return False

    def get_channel_name(self, channel: int) -> str:
        """Lấy tên hiển thị của kênh."""
        return f"CH {channel:02d}"
