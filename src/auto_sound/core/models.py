"""Các dataclass và enum thuần túy định nghĩa dữ liệu cốt lõi của hệ thống."""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ConnectionState(Enum):
    """Trạng thái kết nối của Mixer Driver."""
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"


@dataclass(frozen=True)
class PEQBand:
    """Tham số của một dải lọc tham số (PEQ Band)."""
    channel: int            # Kênh 1-16 (hoặc số âm cho Bus nếu cần)
    band: int               # 1-4 trên kênh, 1-6 trên bus
    freq_hz: float          # 20.0 - 20000.0 Hz
    gain_db: float          # -15.0 - +15.0 dB
    q: float                # 0.3 - 10.0
    is_on: bool = True


@dataclass(frozen=True)
class ActionProposal:
    """Đề xuất can thiệp hạ notch từ detector hoặc thuật toán."""
    channel: int
    freq_hz: float
    gain_db: float
    q: float
    bus: Optional[int] = None
    band: Optional[int] = None
    target: str = "ch"  # "ch", "main", "bus"
    reason: str = "Acoustic feedback detected"


@dataclass(frozen=True)
class Decision:
    """Quyết định được đưa ra bởi Safety Controller."""
    approved: bool
    proposal: Optional[ActionProposal] = None
    effective_gain_db: float = 0.0
    reason: str = ""
    is_probing: bool = False
    transaction_id: str = ""


@dataclass
class DetectionCandidate:
    """Trạng thái ứng viên tần số hú đang được theo dõi trên một kênh."""
    channel: int
    freq_hz: float
    prominence_db: float
    growth_rate_db_per_frame: float
    persistence_frames: int
    last_energy_db: float
    is_confirmed: bool = False
