"""Bộ dò hú qua phổ tần số RTA 100-band nhận từ mạng LAN (dành cho Behringer XR12 / XR16 / MR12)."""

from __future__ import annotations
import numpy as np
import scipy.ndimage
from typing import Dict, List, Optional
from auto_sound.core.models import ActionProposal


class RTADetector:
    """Phát hiện tiếng hú dựa trên luồng RTA 100-band gửi qua OSC /meters/4."""

    def __init__(
        self,
        num_bins: int = 100,
        f_min_hz: float = 20.0,
        f_max_hz: float = 20000.0,
        prominence_threshold_db: float = 10.0,
        min_peak_db: float = -50.0,
        growth_threshold_db: float = 2.0,
        confirmation_frames: int = 3,
        default_notch_q: float = 10.0,
        probe_gain_db: float = -3.0,
    ) -> None:
        self.num_bins = num_bins
        self.f_min_hz = f_min_hz
        self.f_max_hz = f_max_hz
        self.prominence_threshold_db = prominence_threshold_db
        self.min_peak_db = min_peak_db
        self.growth_threshold_db = growth_threshold_db
        self.confirmation_frames = confirmation_frames
        self.default_notch_q = default_notch_q
        self.probe_gain_db = probe_gain_db

        # Bảng 100 tần số trung tâm logarit: f_i = f_min * (f_max / f_min) ** (i / (num_bins - 1))
        indices = np.arange(num_bins, dtype=np.float64)
        self.bin_center_freqs = f_min_hz * ((f_max_hz / f_min_hz) ** (indices / (num_bins - 1.0)))

        # Lịch sử theo dõi ứng viên hú: bin_idx -> {frames: int, last_energy: float, accumulated_growth: float}
        self._history: Dict[int, Dict[str, float]] = {}

    def bin_to_freq(self, bin_idx: int) -> float:
        """Quy đổi chỉ số bin RTA sang tần số trung tâm (Hz)."""
        idx = max(0, min(self.num_bins - 1, int(bin_idx)))
        return float(self.bin_center_freqs[idx])

    def freq_to_bin(self, freq_hz: float) -> int:
        """Tìm chỉ số bin RTA gần nhất với tần số freq_hz."""
        clipped = max(self.f_min_hz, min(self.f_max_hz, freq_hz))
        ratio = clipped / self.f_min_hz
        log_span = self.f_max_hz / self.f_min_hz
        bin_float = (np.log(ratio) / np.log(log_span)) * (self.num_bins - 1.0)
        return int(np.clip(np.round(bin_float), 0, self.num_bins - 1))

    def process_rta_frame(
        self,
        levels_db: List[float] | np.ndarray,
        target_name: str = "main",
    ) -> List[ActionProposal]:
        """Xử lý 1 khung phổ RTA 100 nấc và trả về danh sách đề xuất hạ notch nếu phát hiện hú."""
        levels = np.asarray(levels_db, dtype=np.float32)
        if len(levels) != self.num_bins:
            return []

        # 1. Ước lượng sàn phổ nền bằng bộ lọc trung vị (Median Filter) cửa sổ 11 bins
        baseline = scipy.ndimage.median_filter(levels, size=11, mode="nearest")
        prominence = levels - baseline

        # 2. Tìm các đỉnh năng lượng nổi bật
        candidates: List[int] = []
        for i in range(1, self.num_bins - 1):
            # Điều kiện cực đại địa phương (Local peak)
            if levels[i] > levels[i - 1] and levels[i] > levels[i + 1]:
                # Vượt ngưỡng nổi bật so với nền và vượt mức năng lượng tối thiểu
                if prominence[i] >= self.prominence_threshold_db and levels[i] >= self.min_peak_db:
                    candidates.append(i)

        current_active_bins = set(candidates)
        # Giảm dần hoặc xóa các bin không còn xuất hiện
        for b in list(self._history.keys()):
            if b not in current_active_bins:
                del self._history[b]

        proposals: List[ActionProposal] = []

        # 3. Theo dõi sự tích lũy qua các khung liên tiếp
        for b in candidates:
            current_energy = float(levels[b])
            if b not in self._history:
                self._history[b] = {
                    "frames": 1,
                    "last_energy": current_energy,
                    "accumulated_growth": 0.0,
                }
            else:
                entry = self._history[b]
                entry["frames"] += 1
                growth = current_energy - entry["last_energy"]
                if growth > 0:
                    entry["accumulated_growth"] += growth
                entry["last_energy"] = current_energy

                # Khi đã tồn tại đủ confirmation_frames (khoảng 3 khung = ~150ms)
                # và có dấu hiệu tăng trưởng năng lượng
                if entry["frames"] >= self.confirmation_frames and entry["accumulated_growth"] >= self.growth_threshold_db:
                    f_hz = self.bin_to_freq(b)
                    prop = ActionProposal(
                        channel=0,  # 0 đại diện cho Main Stereo LR
                        target=target_name,
                        freq_hz=f_hz,
                        gain_db=self.probe_gain_db,
                        q=self.default_notch_q,
                        reason=f"Phát hiện hú qua RTA {target_name.upper()} tại {f_hz:.0f}Hz (nổi bật {prominence[b]:.1f}dB)",
                    )
                    proposals.append(prop)
                    # Xóa lịch sử của bin này sau khi đã phát cảnh báo
                    del self._history[b]

        return proposals
