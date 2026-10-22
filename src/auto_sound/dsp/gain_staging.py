"""Module Auto Preamp Gain Staging và Clip Guardian bảo vệ micro thời gian thực (Giai đoạn 3).

Mục tiêu chuẩn công nghiệp:
- Cân Gain Micro trong 10 giây: Target RMS ≈ -18 dBFS, True Peak ≤ -6 dBFS.
- Clip Guardian: Giám sát tình trạng đỏ vạch (Clipping > 300ms) trong show và đề xuất hạ Gain an toàn.
- Phân tách rõ Semi (mặc định) và Auto (phải có xác nhận tường minh từ soundman).
"""

from __future__ import annotations
from dataclasses import dataclass, field
import math
import time
from typing import Dict, List, Optional, Tuple


@dataclass
class GainCalibrationSession:
    """Phiên đo và tính toán cân gain tự động cho một kênh micro."""
    channel: int
    duration_s: float = 10.0
    start_time: float = 0.0
    is_active: bool = False
    samples_peak: List[float] = field(default_factory=list)
    samples_rms: List[float] = field(default_factory=list)
    current_headamp_gain_db: float = 0.0
    proposed_gain_db: Optional[float] = None
    target_rms_dbfs: float = -18.0
    max_peak_dbfs: float = -6.0
    status: str = "IDLE"  # "IDLE", "MEASURING", "READY", "APPLIED", "CANCELLED"


@dataclass
class ClipAlert:
    """Cảnh báo tín hiệu micro bị vượt ngưỡng (Clip Overload)."""
    channel: int
    channel_name: str
    clip_duration_ms: float
    current_gain_db: float
    suggested_reduction_db: float = -3.0
    timestamp: float = 0.0


class GainStagingManager:
    """Quản lý cân Gain tự động và bảo vệ Clip cho 16 kênh Micro."""

    def __init__(
        self,
        target_rms_dbfs: float = -18.0,
        max_peak_dbfs: float = -6.0,
        max_gain_step_db: float = 6.0,
        headamp_min_db: float = -12.0,
        headamp_max_db: float = 60.0,
        clip_threshold_dbfs: float = -0.5,
        clip_persist_ms: float = 300.0,
    ) -> None:
        self.target_rms_dbfs = target_rms_dbfs
        self.max_peak_dbfs = max_peak_dbfs
        self.max_gain_step_db = max_gain_step_db
        self.headamp_min_db = headamp_min_db
        self.headamp_max_db = headamp_max_db
        self.clip_threshold_dbfs = clip_threshold_dbfs
        self.clip_persist_ms = clip_persist_ms

        # Phiên đo Auto-Gain theo kênh: channel -> GainCalibrationSession
        self.sessions: Dict[int, GainCalibrationSession] = {}
        # Theo dõi thời gian clip liên tục: channel -> timestamp bắt đầu clip
        self._clip_start_times: Dict[int, float] = {}
        # Cấu hình Clip Guardian Auto-Tame (mặc định TẮT - an toàn tuyệt đối)
        self.auto_tame_enabled: bool = False

    def start_calibration(self, channel: int, current_headamp_gain_db: float = 0.0) -> bool:
        """Bắt đầu phiên đo 10 giây cho một kênh micro."""
        session = GainCalibrationSession(
            channel=channel,
            start_time=time.time(),
            is_active=True,
            current_headamp_gain_db=current_headamp_gain_db,
            target_rms_dbfs=self.target_rms_dbfs,
            max_peak_dbfs=self.max_peak_dbfs,
            status="MEASURING",
        )
        self.sessions[channel] = session
        return True

    def cancel_calibration(self, channel: int) -> None:
        """Hủy phiên đo."""
        if channel in self.sessions:
            self.sessions[channel].is_active = False
            self.sessions[channel].status = "CANCELLED"

    def process_meter_sample(
        self,
        channel: int,
        peak_level_dbfs: float,
        rms_level_dbfs: float,
        now: float,
    ) -> Tuple[Optional[float], Optional[ClipAlert]]:
        """Tiếp nhận mẫu đo tín hiệu (thường từ /meters/1 hoặc USB audio loop).
        
        Trả về:
            (proposed_gain_db_if_session_complete, clip_alert_if_persistent_clip)
        """
        proposed_gain: Optional[float] = None
        clip_alert: Optional[ClipAlert] = None

        # 1. Cập nhật phiên đo nếu đang chạy
        session = self.sessions.get(channel)
        if session and session.is_active:
            session.samples_peak.append(peak_level_dbfs)
            session.samples_rms.append(rms_level_dbfs)

            # Nếu đã hết 10 giây đo
            if (now - session.start_time) >= session.duration_s:
                session.is_active = False
                session.status = "READY"

                # Tính toán giá trị trung vị RMS và True Peak cao nhất
                if session.samples_rms and session.samples_peak:
                    valid_rms = [r for r in session.samples_rms if r > -80.0]
                    avg_rms = float(sum(valid_rms) / len(valid_rms)) if valid_rms else -50.0
                    max_peak = float(max(session.samples_peak))

                    # Công thức: Delta Gain để RMS đạt Target (-18 dBFS)
                    delta_rms = self.target_rms_dbfs - avg_rms
                    # Kiểm tra trần Peak (-6 dBFS): Không để delta làm vượt Peak
                    peak_headroom = self.max_peak_dbfs - max_peak
                    safe_delta = min(delta_rms, peak_headroom)

                    # Giới hạn bước nhảy tối đa (±6 dB) mỗi lần cân
                    clamped_delta = max(-self.max_gain_step_db, min(self.max_gain_step_db, safe_delta))

                    target_gain = session.current_headamp_gain_db + clamped_delta
                    # Kẹp vào giới hạn vật lý của preamp mixer (-12 dB đến +60 dB)
                    final_gain = max(self.headamp_min_db, min(self.headamp_max_db, target_gain))
                    session.proposed_gain_db = round(final_gain, 1)
                    proposed_gain = session.proposed_gain_db

        # 2. Clip Guardian: Theo dõi tình trạng đỏ vạch liên tục
        if peak_level_dbfs >= self.clip_threshold_dbfs:
            if channel not in self._clip_start_times:
                self._clip_start_times[channel] = now
            else:
                elapsed_ms = (now - self._clip_start_times[channel]) * 1000.0
                if elapsed_ms >= self.clip_persist_ms:
                    clip_alert = ClipAlert(
                        channel=channel,
                        channel_name=f"CH {channel:02d}",
                        clip_duration_ms=round(elapsed_ms, 1),
                        current_gain_db=session.current_headamp_gain_db if session else 0.0,
                        suggested_reduction_db=-3.0,
                        timestamp=now,
                    )
                    # Reset lại bộ đếm để không spam alert liên tục mỗi ms
                    self._clip_start_times[channel] = now
        else:
            self._clip_start_times.pop(channel, None)

        return proposed_gain, clip_alert
