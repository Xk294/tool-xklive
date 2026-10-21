"""Bộ định vị nguồn hú hai nhân tố (Two-Factor Localizer).

Mục tiêu (Giai đoạn D1):
- Khi detector phát hiện tần số hú f0, định vị chính xác micro/nhạc cụ và bus gây quẩn âm.
- Kết hợp 2 nhân tố độc lập:
  1. Phổ năng lượng vi sai tại bin f0 trên từng kênh riêng biệt (không chỉ mức tổng RMS).
  2. Bảng định tuyến (Routing Table): send level (/ch/NN/mix/MM/level), trạng thái mute/on, fader level.
- Đầu ra danh sách ứng viên (kênh, bus) kèm điểm tin cậy [0.0 - 1.0].
- Tự động phát hiện trường hợp mơ hồ (ambiguous) để hạ cấp xuống chế độ `semi` cho soundman chọn.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional, Tuple
import numpy as np


@dataclass(frozen=True)
class LocalizerCandidate:
    """Ứng viên kênh và bus bị nghi ngờ tạo vòng lặp phản hồi âm học."""
    channel: int                      # Kênh 1-16
    bus: Optional[int]                # Bus 1-6 (hoặc None nếu ra Main/FOH)
    score: float                      # Điểm tin cậy tổng hợp [0.0, 1.0]
    spectral_energy_db: float         # Năng lượng phổ tại tần số f0 (dBFS)
    send_level_db: float              # Mức send tới bus (dB)
    is_channel_muted: bool = False
    is_bus_muted: bool = False


@dataclass
class LocalizationResult:
    """Kết quả định vị nguồn hú kèm khuyến nghị chế độ vận hành."""
    f0_hz: float
    candidates: List[LocalizerCandidate] = field(default_factory=list)
    top_candidate: Optional[LocalizerCandidate] = None
    is_ambiguous: bool = False
    ambiguity_delta: float = 0.0
    recommended_mode: str = "auto"     # "auto" nếu tin cậy tuyệt đối, "semi" nếu mơ hồ


@dataclass
class RoutingSnapshot:
    """Bản chụp trạng thái định tuyến và fader từ bàn mixer."""
    # (channel, bus) -> float [0.0, 1.0]
    bus_sends: Dict[Tuple[int, int], float] = field(default_factory=dict)
    # channel -> bool (True = Bật, False = Mute)
    channel_on: Dict[int, bool] = field(default_factory=lambda: {ch: True for ch in range(1, 17)})
    # channel -> float [0.0, 1.0]
    channel_faders: Dict[int, float] = field(default_factory=lambda: {ch: 0.75 for ch in range(1, 17)})
    # bus -> bool
    bus_on: Dict[int, bool] = field(default_factory=lambda: {b: True for b in range(1, 7)})
    # bus -> float [0.0, 1.0]
    bus_faders: Dict[int, float] = field(default_factory=lambda: {b: 0.75 for b in range(1, 7)})


class TwoFactorLocalizer:
    """Bộ xử lý định vị nguồn hú kết hợp phân tích phổ FFT và ma trận định tuyến."""

    def __init__(
        self,
        sample_rate: int = 48000,
        frame_size: int = 2048,
        spectral_weight: float = 0.65,
        routing_weight: float = 0.35,
        ambiguity_threshold: float = 0.15,
        min_confidence_for_auto: float = 0.50,
    ) -> None:
        self.sample_rate = sample_rate
        self.frame_size = frame_size
        self.spectral_weight = spectral_weight
        self.routing_weight = routing_weight
        self.ambiguity_threshold = ambiguity_threshold
        self.min_confidence_for_auto = min_confidence_for_auto

        self._window = np.hanning(self.frame_size)
        self._freq_bins = np.fft.rfftfreq(self.frame_size, d=1.0 / self.sample_rate)

    def compute_channel_bin_energy_db(self, channel_frame: np.ndarray, f0_hz: float) -> float:
        """Đo năng lượng phổ chính xác tại bin tần số f0 (áp dụng cửa sổ Hanning)."""
        if len(channel_frame) < self.frame_size:
            return -120.0

        # Áp cửa sổ và biến đổi FFT
        windowed = channel_frame[-self.frame_size :] * self._window
        spectrum = np.abs(np.fft.rfft(windowed))

        # Tìm bin gần f0 nhất và xét cửa sổ lân cận ±1 bin để chống lệch đỉnh do nội suy
        center_bin = int(np.argmin(np.abs(self._freq_bins - f0_hz)))
        bin_start = max(0, center_bin - 1)
        bin_end = min(len(spectrum), center_bin + 2)

        peak_mag = np.max(spectrum[bin_start:bin_end])
        energy_db = 20.0 * np.log10(max(peak_mag, 1e-6) / (self.frame_size / 2.0))
        return float(energy_db)

    def localize(
        self,
        multi_channel_frames: Dict[int, np.ndarray],
        f0_hz: float,
        routing: Optional[RoutingSnapshot] = None,
        suspected_bus: Optional[int] = None,
    ) -> LocalizationResult:
        """Định vị micro và bus gây hú dựa trên năng lượng phổ f0 và bảng routing.
        
        Args:
            multi_channel_frames: Bản đồ kênh -> mảng audio frame (2048 mẫu).
            f0_hz: Tần số hú được detector xác nhận.
            routing: Snapshot trạng thái bàn mixer (send level, mute, fader).
            suspected_bus: Bus cụ thể nghi ngờ (nếu có thông tin từ RTA hoặc soundman).
        """
        if routing is None:
            routing = RoutingSnapshot()

        channel_spectral_db: Dict[int, float] = {}
        for ch, frame in multi_channel_frames.items():
            channel_spectral_db[ch] = self.compute_channel_bin_energy_db(frame, f0_hz)

        # Chuẩn hóa năng lượng phổ giữa các kênh về thang điểm [0.0, 1.0]
        # (Chỉ xét kênh có năng lượng > -90 dBFS)
        active_energies = [db for db in channel_spectral_db.values() if db > -90.0]
        min_db = min(active_energies) if active_energies else -90.0
        max_db = max(active_energies) if active_energies else -30.0
        db_range = max(1.0, max_db - min_db)

        candidates: List[LocalizerCandidate] = []

        # Đánh giá từng cặp (kênh, bus)
        buses_to_eval = [suspected_bus] if suspected_bus is not None else list(range(1, 7))

        for ch, spec_db in channel_spectral_db.items():
            is_ch_on = routing.channel_on.get(ch, True)
            ch_fader = routing.channel_faders.get(ch, 0.75)

            # Điểm phổ chuẩn hóa [0.0, 1.0]
            if spec_db > -90.0:
                norm_spectral = max(0.0, min(1.0, (spec_db - min_db) / db_range))
            else:
                norm_spectral = 0.0

            for b in buses_to_eval:
                is_bus_on = routing.bus_on.get(b, True)
                bus_fader = routing.bus_faders.get(b, 0.75)
                send_val = routing.bus_sends.get((ch, b), 0.75)  # Mặc định 0.75 (~0 dB)

                # Nếu kênh bị Mute hoặc Bus bị Mute -> Không thể tạo vòng hồi tiếp
                if not is_ch_on or not is_bus_on:
                    total_score = 0.0
                else:
                    # Điểm định tuyến: Tích hợp send_level và fader kênh/bus
                    norm_routing = send_val * ch_fader * bus_fader
                    total_score = (self.spectral_weight * norm_spectral) + (self.routing_weight * norm_routing)

                # Chuyển đổi send_val thành dB ước lượng (-oo đến +10 dB)
                send_db = 20.0 * math.log10(max(send_val, 1e-4))

                candidate = LocalizerCandidate(
                    channel=ch,
                    bus=b,
                    score=round(float(total_score), 4),
                    spectral_energy_db=round(float(spec_db), 1),
                    send_level_db=round(float(send_db), 1),
                    is_channel_muted=not is_ch_on,
                    is_bus_muted=not is_bus_on,
                )
                candidates.append(candidate)

        # Sắp xếp ứng viên giảm dần theo điểm tin cậy
        candidates.sort(key=lambda c: c.score, reverse=True)

        top_cand = candidates[0] if candidates else None
        is_ambiguous = False
        ambiguity_delta = 1.0
        rec_mode = "auto"

        if top_cand is not None:
            # So sánh độ mơ hồ giữa kênh dẫn đầu và kênh đối thủ cạnh tranh gần nhất
            other_channel_cands = [c for c in candidates if c.channel != top_cand.channel]
            if other_channel_cands:
                second_cand = other_channel_cands[0]
                ambiguity_delta = top_cand.score - second_cand.score
                if ambiguity_delta < self.ambiguity_threshold:
                    is_ambiguous = True
            else:
                ambiguity_delta = 1.0
                is_ambiguous = False

            # Nếu điểm top_candidate thấp hơn ngưỡng tự động tin cậy -> Chuyển sang semi
            if top_cand.score < self.min_confidence_for_auto or is_ambiguous:
                rec_mode = "semi"
            else:
                rec_mode = "auto"

        return LocalizationResult(
            f0_hz=f0_hz,
            candidates=candidates,
            top_candidate=top_cand,
            is_ambiguous=is_ambiguous,
            ambiguity_delta=round(float(ambiguity_delta), 4),
            recommended_mode=rec_mode,
        )
