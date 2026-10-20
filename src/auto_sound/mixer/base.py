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

    @abstractmethod
    def close(self) -> None:
        """Đóng hoàn toàn driver."""
        pass
