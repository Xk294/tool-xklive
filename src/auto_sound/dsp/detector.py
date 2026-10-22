"""Bộ phát hiện tiếng hú (Feedback Detector) đa kênh với độ chính xác cao và loại trừ âm nhạc."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Set
import numpy as np
from scipy.ndimage import median_filter
from auto_sound.core.models import ActionProposal


@dataclass
class ChannelTrackedPeak:
    """Theo dõi tiến trình tăng trưởng của một đỉnh tần số trên một kênh."""
    bin_idx: int
    freq_hz: float
    last_mag_db: float
    accumulated_growth_db: float
    consecutive_frames: int
    is_reported: bool = False


class FeedbackDetector:
    """Phát hiện tiếng hú độc lập trên từng kênh micro USB dựa trên phân tích phổ FFT."""

    def __init__(
        self,
        sample_rate: int = 48000,
        frame_size: int = 2048,
        hop_size: int = 512,
        prominence_threshold_db: float = 10.0,
        growth_threshold_db: float = 2.0,
        confirmation_frames: int = 3,
        min_freq_hz: float = 100.0,
        max_freq_hz: float = 15000.0,
        min_peak_db: float = -50.0,
        default_notch_q: float = 8.0,
        probe_gain_db: float = -3.0,
    ) -> None:
        self.sample_rate = sample_rate
        self.frame_size = frame_size
        self.hop_size = hop_size
        self.prominence_threshold_db = prominence_threshold_db
        self.growth_threshold_db = growth_threshold_db
        self.confirmation_frames = confirmation_frames
        self.min_freq_hz = min_freq_hz
        self.max_freq_hz = max_freq_hz
        self.min_peak_db = min_peak_db
        self.default_notch_q = default_notch_q
        self.probe_gain_db = probe_gain_db

        # Khởi tạo cửa sổ Hann cấp phát sẵn
        self.window = np.hanning(self.frame_size).astype(np.float32)

        # Buffers tiền cấp phát (Zero-Allocation steady-state DSP)
        rfft_bins = self.frame_size // 2 + 1
        self._windowed = np.zeros(self.frame_size, dtype=np.float32)
        self._mag = np.zeros(rfft_bins, dtype=np.float32)
        self._mag_db = np.zeros(rfft_bins, dtype=np.float32)
        self._noise_floor = np.zeros(rfft_bins, dtype=np.float32)
        self._prominence = np.zeros(rfft_bins, dtype=np.float32)
        self._active_bins: Set[int] = set()
        self._detected_peaks: List[tuple[int, float, float]] = []
        self._stale_bins: List[int] = []

        # Tính bin tương ứng với dải tần số
        self.bin_res = self.sample_rate / self.frame_size  # ~23.44 Hz/bin @ 48kHz
        self.min_bin = max(2, int(np.floor(self.min_freq_hz / self.bin_res)))
        self.max_bin = min(self.frame_size // 2 - 2, int(np.ceil(self.max_freq_hz / self.bin_res)))

        # Lưu trữ trạng thái bám bắt đỉnh: channel_idx -> dict[bin_idx, ChannelTrackedPeak]
        self._tracked_peaks: Dict[int, Dict[int, ChannelTrackedPeak]] = {}

    def reset_channel(self, channel: int) -> None:
        """Xóa sạch lịch sử theo dõi của một kênh."""
        if channel in self._tracked_peaks:
            self._tracked_peaks[channel].clear()

    def reset_all(self) -> None:
        """Xóa sạch toàn bộ lịch sử theo dõi."""
        self._tracked_peaks.clear()

    def _is_musical_harmonic(self, mag_db: np.ndarray, bin_idx: int) -> bool:
        """Kiểm tra xem đỉnh tần số tại bin_idx có phải là nốt nhạc hay không (dựa trên họa âm và hạ âm)."""
        peak_mag = mag_db[bin_idx]
        total_bins = len(mag_db)

        # 1. Kiểm tra họa âm phía trên: 2*f0, 3*f0, 4*f0
        for mul in (2, 3, 4):
            target = mul * bin_idx
            if target < total_bins:
                local_max = max(mag_db[max(0, target - 1) : min(total_bins, target + 2)])
                if peak_mag - local_max < 15.0:
                    return True

        # 2. Kiểm tra hạ âm phía dưới: f0/2, f0/3, f0/4 (đỉnh hiện tại là họa âm của nốt nhạc trầm hơn)
        for div in (2, 3, 4):
            target = int(round(bin_idx / div))
            if target >= 2:
                local_max = max(mag_db[max(0, target - 1) : min(total_bins, target + 2)])
                if peak_mag - local_max < 15.0:
                    return True

        return False

    def process_channel_frame(self, channel: int, frame_samples: np.ndarray) -> List[ActionProposal]:
        """Phân tích 1 khung âm thanh (2048 mẫu) của 1 kênh micro cụ thể."""
        if len(frame_samples) != self.frame_size:
            raise ValueError(f"Khung âm thanh phải có độ dài đúng {self.frame_size} mẫu")

        # 1. Nhân cửa sổ Hann (In-place)
        np.multiply(frame_samples, self.window, out=self._windowed)

        # 2. Biến đổi Fourier thực (RFFT) & tính mag_db (In-place)
        spectrum = np.fft.rfft(self._windowed)
        np.abs(spectrum, out=self._mag)
        np.maximum(self._mag, 1e-8, out=self._mag)
        np.log10(self._mag, out=self._mag_db)
        np.multiply(self._mag_db, 20.0, out=self._mag_db)
        mag_db = self._mag_db

        # 3. Ước lượng mức nền nhiễu bằng median filter cục bộ (In-place)
        median_filter(mag_db, size=31, mode="nearest", output=self._noise_floor)
        np.subtract(mag_db, self._noise_floor, out=self._prominence)
        prominence = self._prominence

        # 4. Tìm các đỉnh cục bộ (Local Peaks)
        self._detected_peaks.clear()
        detected_peaks = self._detected_peaks

        for k in range(self.min_bin, self.max_bin):
            # Bỏ qua các tín hiệu dưới ngưỡng nhiễu nền tối thiểu (-50 dBFS)
            if mag_db[k] < self.min_peak_db:
                continue

            if mag_db[k] > mag_db[k - 1] and mag_db[k] > mag_db[k + 1]:
                if prominence[k] >= self.prominence_threshold_db:
                    # Loại trừ nốt nhạc nếu có họa âm bậc 2, bậc 3 hoặc hạ âm rõ rệt
                    if self._is_musical_harmonic(mag_db, k):
                        continue

                    # 5. Nội suy Parabol để xác định tần số chính xác
                    alpha = mag_db[k - 1]
                    beta = mag_db[k]
                    gamma = mag_db[k + 1]
                    denom = alpha - 2.0 * beta + gamma
                    p = 0.5 * (alpha - gamma) / denom if abs(denom) > 1e-7 else 0.0

                    exact_bin = k + p
                    exact_freq = exact_bin * self.bin_res
                    exact_mag = beta - 0.25 * (alpha - gamma) * p

                    detected_peaks.append((k, exact_freq, exact_mag))

        # 6. Bám bắt tiến trình tăng trưởng qua các khung liên tiếp (In-place dict reuse)
        if channel not in self._tracked_peaks:
            self._tracked_peaks[channel] = {}

        current_tracked = self._tracked_peaks[channel]
        self._active_bins.clear()
        active_bins = self._active_bins
        proposals: List[ActionProposal] = []

        for k, freq, mag_val in detected_peaks:
            active_bins.add(k)
            matched_prev_bin: Optional[int] = None
            for offset in (0, -1, 1):
                prev_bin = k + offset
                if prev_bin in current_tracked:
                    matched_prev_bin = prev_bin
                    break

            if matched_prev_bin is not None:
                peak_record = current_tracked[matched_prev_bin]
                growth = mag_val - peak_record.last_mag_db

                # Nếu năng lượng đang suy giảm mạnh (Decay < -1.0 dB, ví dụ cymbal tan dần):
                # Không tăng bộ đếm chu kỳ hú
                if growth < -1.0:
                    continue

                total_growth = peak_record.accumulated_growth_db + max(0.0, growth)
                consecutive = peak_record.consecutive_frames + 1
                is_reported = peak_record.is_reported

                # Cập nhật in-place thay vì cấp phát mới đối tượng
                peak_record.bin_idx = k
                peak_record.freq_hz = freq
                peak_record.last_mag_db = mag_val
                peak_record.accumulated_growth_db = total_growth
                peak_record.consecutive_frames = consecutive

                if matched_prev_bin != k:
                    del current_tracked[matched_prev_bin]
                    current_tracked[k] = peak_record

                # Điều kiện kết luận hú:
                # 1. Duy trì liên tục >= 3 khung (khoảng 32-42ms)
                # 2. Tổng mức tăng trưởng tích lũy >= 2.0 dB (chứng minh tính bùng nổ theo hàm mũ)
                if consecutive >= self.confirmation_frames and not is_reported:
                    if total_growth >= self.growth_threshold_db:
                        peak_record.is_reported = True
                        proposals.append(
                            ActionProposal(
                                channel=channel,
                                freq_hz=float(round(freq, 1)),
                                gain_db=self.probe_gain_db,
                                q=self.default_notch_q,
                                reason=f"Feedback {freq:.1f}Hz (+{total_growth:.1f}dB tích lũy)",
                            )
                        )
            else:
                # Đỉnh mới xuất hiện lần đầu ở khung này
                current_tracked[k] = ChannelTrackedPeak(
                    bin_idx=k,
                    freq_hz=freq,
                    last_mag_db=mag_val,
                    accumulated_growth_db=0.0,
                    consecutive_frames=1,
                    is_reported=False,
                )

        # Xóa các bin không còn xuất hiện trong khung này (tái sử dụng list đệm)
        self._stale_bins.clear()
        for b in current_tracked:
            if b not in active_bins:
                self._stale_bins.append(b)
        for b in self._stale_bins:
            del current_tracked[b]

        return proposals
