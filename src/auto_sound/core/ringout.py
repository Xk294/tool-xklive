"""Bộ điều khiển Ring-Out âm học phòng trước giờ diễn (Giai đoạn 2).

Nguyên tắc thực chiến:
1. Chỉ chạy khi soundman bấm Bắt đầu trên một đích cụ thể (Aux Monitor 1-6 hoặc Main L/R).
2. Tăng fader từng nấc nhỏ (+1 dB / 500 ms) có trần an toàn tuyệt đối.
3. Khi phát hiện đỉnh cộng hưởng nhô cao (> 12 dB so với floor): lập tức lùi fader (-3 dB) và ghim notch hẹp (Q=10, -4.5 dB).
4. Kết thúc: trả fader về đúng giá trị gốc ban đầu đọc từ mixer.
5. Nút dừng khẩn cấp và tự động hủy an toàn khi mất kết nối / PANIC.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import math
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from auto_sound.core.models import ActionProposal


@dataclass
class RingOutConfig:
    """Cấu hình an toàn cho quy trình Auto Ring-Out."""
    step_db: float = 1.0                    # Bước tăng fader (+1 dB)
    step_interval_s: float = 0.5            # Thời gian chờ giữa các nấc (500 ms)
    max_boost_above_start_db: float = 6.0   # Trần fader tối đa so với mức ban đầu (+6 dB)
    fader_retreat_db: float = -3.0          # Bước lùi fader ngay khi chớm hú (-3 dB)
    notch_gain_db: float = -4.5             # Độ sâu notch gài trước (-4.5 dB)
    notch_q: float = 10.0                   # Độ nhọn notch (Q hẹp = 10.0)
    prominence_threshold_db: float = 12.0   # Đỉnh nhô cao hơn sàn năng lượng để coi là cộng hưởng
    max_notches: int = 5                    # Số lượng notch tối đa cần gọt cho phòng (3-6)
    r_floor_db: float = -75.0               # Sàn năng lượng tối thiểu để xét peak


@dataclass
class RingOutReport:
    """Báo cáo kết quả sau khi hoàn thành Auto Room Ring-Out."""
    target_type: str
    target_id: int
    initial_fader_db: float
    final_fader_db: float
    total_duration_s: float
    notches_applied: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "COMPLETED"  # "COMPLETED", "ABORTED", "CEILING_REACHED"
    message: str = ""


class RingOutController:
    """Quản lý trạng thái và chu trình Ring-Out phòng trước giờ diễn."""

    def __init__(self, config: Optional[RingOutConfig] = None) -> None:
        self.config = config or RingOutConfig()
        self.is_active: bool = False
        self.target_type: str = "bus"  # "bus" hoặc "lr"
        self.target_id: int = 1        # Bus 1-6 hoặc 0 cho Main L/R

        self.initial_fader_val: float = 0.75   # Giá trị chuẩn hóa [0.0, 1.0]
        self.current_fader_val: float = 0.75
        self.initial_fader_db: float = 0.0     # dB quy đổi tương đối
        self.current_fader_db: float = 0.0

        self.start_time: float = 0.0
        self.last_step_time: float = 0.0
        self.notches_found: List[Dict[str, Any]] = []
        self.status_message: str = "Sẵn sàng"

        # RTA bin to frequency mapper (100 bins từ 20 Hz đến 20 kHz theo chuẩn ISO)
        self._frequencies = [
            20.0 * (1000.0 ** (i / 99.0)) for i in range(100)
        ]

    def start(
        self,
        target_type: str,
        target_id: int,
        initial_fader_val: float,
        initial_fader_db: float = 0.0,
        now: Optional[float] = None,
    ) -> bool:
        """Kích hoạt chu trình Ring-Out trên đích chỉ định."""
        if self.is_active:
            return False

        self.is_active = True
        self.target_type = target_type
        self.target_id = target_id
        self.initial_fader_val = initial_fader_val
        self.current_fader_val = initial_fader_val
        self.initial_fader_db = initial_fader_db
        self.current_fader_db = initial_fader_db

        cur_time = now if now is not None else time.time()
        self.start_time = cur_time
        self.last_step_time = cur_time
        self.notches_found.clear()
        self.status_message = f"Bắt đầu Ring-Out trên {self.target_type.upper()} {self.target_id}"
        return True

    def stop(self, reason: str = "aborted") -> RingOutReport:
        """Dừng khẩn cấp chu trình Ring-Out và trả về báo cáo khôi phục."""
        was_active = self.is_active
        self.is_active = False
        duration = time.time() - self.start_time if was_active else 0.0
        status = "ABORTED" if reason == "aborted" else ("COMPLETED" if reason == "completed" else "CEILING_REACHED")
        msg = "Đã dừng khẩn cấp Ring-Out" if reason == "aborted" else ("Hoàn tất Ring-Out" if reason == "completed" else "Đạt trần an toàn")
        self.status_message = msg

        return RingOutReport(
            target_type=self.target_type,
            target_id=self.target_id,
            initial_fader_db=self.initial_fader_db,
            final_fader_db=self.initial_fader_db,  # Luôn trả về fader ban đầu
            total_duration_s=round(duration, 1),
            notches_applied=list(self.notches_found),
            status=status,
            message=msg,
        )

    def process_frame(
        self,
        rta_levels_db: List[float],
        now: float,
    ) -> Tuple[Optional[float], Optional[ActionProposal], Optional[RingOutReport]]:
        """Phân tích RTA trong chu trình Ring-Out.
        
        Trả về:
            (new_fader_val_to_send, notch_proposal_if_detected, final_report_if_done)
        """
        if not self.is_active or len(rta_levels_db) < 100:
            return None, None, None

        # 1. Quét tìm đỉnh cộng hưởng (peak prominence)
        median_floor = float(sorted(rta_levels_db)[50])  # Trung vị làm sàn năng lượng phòng
        peak_bin = -1
        peak_prominence = 0.0
        peak_level = -120.0

        for b in range(1, 99):
            lvl = rta_levels_db[b]
            if lvl > self.config.r_floor_db and lvl > rta_levels_db[b - 1] and lvl > rta_levels_db[b + 1]:
                prom = lvl - median_floor
                if prom > peak_prominence:
                    peak_prominence = prom
                    peak_bin = b
                    peak_level = lvl

        # 2. Nếu phát hiện đỉnh cộng hưởng vượt ngưỡng
        if peak_bin != -1 and peak_prominence >= self.config.prominence_threshold_db:
            freq_hz = self._frequencies[peak_bin]
            # Kiểm tra xem tần số này đã được gọt trước đó chưa (trong phạm vi 5%)
            already_notched = any(
                abs(n["freq_hz"] - freq_hz) / freq_hz < 0.05
                for n in self.notches_found
            )
            if not already_notched:
                # Lập tức lùi fader an toàn
                self.current_fader_db += self.config.fader_retreat_db
                retreat_delta_val = -0.05  # Bước lùi tương đối chuẩn hóa
                self.current_fader_val = max(0.0, self.current_fader_val + retreat_delta_val)

                notch_info = {
                    "freq_hz": round(freq_hz, 1),
                    "gain_db": self.config.notch_gain_db,
                    "q": self.config.notch_q,
                    "prominence_db": round(peak_prominence, 1),
                    "level_db": round(peak_level, 1),
                    "timestamp": now,
                }
                self.notches_found.append(notch_info)

                target_str = "bus" if self.target_type == "bus" else "lr"
                prop = ActionProposal(
                    channel=0 if target_str in ("bus", "lr") else self.target_id,
                    bus=self.target_id if target_str == "bus" else None,
                    target=target_str,
                    freq_hz=freq_hz,
                    gain_db=self.config.notch_gain_db,
                    q=self.config.notch_q,
                    reason=f"Ring-Out phát hiện cộng hưởng phòng tại {freq_hz:.0f}Hz (+{peak_prominence:.1f}dB)",
                )

                self.status_message = f"Phát hiện đỉnh {freq_hz:.0f}Hz! Đã lùi fader và ghim notch ({len(self.notches_found)}/{self.config.max_notches})"
                self.last_step_time = now + 0.5  # Chờ 500ms cho notch ổn định trước khi tăng tiếp

                # Nếu đã gọt đủ số lượng notch mong muốn cho phòng -> Hoàn thành
                if len(self.notches_found) >= self.config.max_notches:
                    report = self.stop(reason="completed")
                    return self.initial_fader_val, prop, report

                return self.current_fader_val, prop, None

        # 3. Nếu chưa có đỉnh: Tăng fader từng nấc an toàn sau mỗi step_interval_s
        if now - self.last_step_time >= self.config.step_interval_s:
            self.last_step_time = now
            # Kiểm tra trần âm lượng an toàn
            if (self.current_fader_db - self.initial_fader_db) >= self.config.max_boost_above_start_db:
                # Đã đạt trần an toàn tối đa mà không còn tần số hú -> Hoàn tất sạch
                report = self.stop(reason="ceiling_reached")
                return self.initial_fader_val, None, report

            # Tăng fader 1 nấc (+1 dB tương đương ~+0.02 trên thang chuẩn hóa fader X-Air)
            self.current_fader_db += self.config.step_db
            self.current_fader_val = min(1.0, self.current_fader_val + 0.02)
            boost_so_far = self.current_fader_db - self.initial_fader_db
            self.status_message = f"Đang dò: Nâng fader {boost_so_far:+.1f}dB so với ban đầu..."
            return self.current_fader_val, None, None

        return None, None, None
