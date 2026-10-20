"""Bộ mô phỏng phản xạ phòng và sinh tín hiệu âm thanh phục vụ kiểm thử."""

from __future__ import annotations
import numpy as np


class RoomSimulator:
    """Mô phỏng vòng lặp phản hồi âm học (Mic-Loa-Phòng) và các loại nhạc cụ/giọng hát."""

    def __init__(self, sample_rate: int = 48000, seed: int = 42) -> None:
        self.sample_rate = sample_rate
        self.rng = np.random.default_rng(seed)

    def generate_feedback_loop(
        self,
        duration_s: float,
        target_freq_hz: float,
        growth_rate_db_per_s: float = 120.0,
        initial_snr_db: float = -40.0,
        noise_level: float = 0.002,
    ) -> np.ndarray:
        """Mô phỏng vòng lặp âm học kín mic -> loa -> phòng -> mic.
        
        Sử dụng phương trình tăng trưởng Logistic thực tế: Âm lượng tiếng hú bắt đầu từ mức nhiễu nền,
        tăng trưởng theo hàm mũ với tốc độ growth_rate_db_per_s và bão hòa êm ái khi chạm ngưỡng tối đa.
        """
        num_samples = int(duration_s * self.sample_rate)
        t = np.linspace(0, duration_s, num_samples, endpoint=False, dtype=np.float32)

        A0 = 10.0 ** (initial_snr_db / 20.0)  # Biên độ khởi đầu (nhỏ)
        Amax = 0.7  # Biên độ bão hòa tối đa (-3 dBFS)

        # Chuyển đổi tốc độ tăng trưởng từ dB/s sang hệ số alpha hàm mũ:
        # A(t) = A0 * exp(alpha * t) => 20 * log10(exp(alpha * t)) = alpha * 20 / ln(10)
        alpha = growth_rate_db_per_s * np.log(10.0) / 20.0

        # Đường bao tăng trưởng logistic phi tuyến
        envelope = Amax / (1.0 + ((Amax - A0) / A0) * np.exp(-alpha * t))

        # Sóng hình sin tại đúng tần số cộng hưởng phòng target_freq_hz + nhiễu nền
        noise = self.rng.normal(0, noise_level, num_samples).astype(np.float32)
        signal = envelope * np.sin(2.0 * np.pi * target_freq_hz * t) + noise
        return signal.astype(np.float32)

    def generate_vocal_sustain(
        self,
        duration_s: float,
        freq_hz: float = 440.0,
        with_vibrato: bool = True,
        vibrato_rate_hz: float = 6.0,
        vibrato_depth_hz: float = 10.0,
    ) -> np.ndarray:
        """Sinh giọng hát ngân dài với cấu trúc họa âm tự nhiên (f0, 2f0, 3f0, 4f0) và vibrato."""
        num_samples = int(duration_s * self.sample_rate)
        t = np.linspace(0, duration_s, num_samples, endpoint=False, dtype=np.float32)

        if with_vibrato:
            freq_mod = freq_hz + vibrato_depth_hz * np.sin(2.0 * np.pi * vibrato_rate_hz * t)
            phase = 2.0 * np.pi * np.cumsum(freq_mod) / self.sample_rate
        else:
            phase = 2.0 * np.pi * freq_hz * t

        # Họa âm giọng người tự nhiên: Bậc 1 (1.0), 2 (0.75), 3 (0.5), 4 (0.3)
        signal = (
            1.00 * np.sin(phase)
            + 0.75 * np.sin(2.0 * phase)
            + 0.50 * np.sin(3.0 * phase)
            + 0.30 * np.sin(4.0 * phase)
        )
        signal = 0.3 * (signal / np.max(np.abs(signal)))
        return signal.astype(np.float32)

    def generate_guitar_distortion(
        self, duration_s: float, note_hz: float = 330.0, drive: float = 4.0
    ) -> np.ndarray:
        """Sinh tiếng đàn guitar điện méo tiếng (Distortion) ngân dài giàu họa âm chẵn và lẻ."""
        num_samples = int(duration_s * self.sample_rate)
        t = np.linspace(0, duration_s, num_samples, endpoint=False, dtype=np.float32)

        clean = np.sin(2.0 * np.pi * note_hz * t) + 0.5 * np.sin(4.0 * np.pi * note_hz * t)
        distorted = np.tanh(drive * clean)
        envelope = np.exp(-1.5 * t)
        signal = 0.3 * (distorted * envelope)
        return signal.astype(np.float32)

    def generate_cymbal_crash(self, duration_s: float) -> np.ndarray:
        """Sinh tiếng đập chũm chọe (Cymbal) năng lượng dải cao suy giảm nhanh."""
        num_samples = int(duration_s * self.sample_rate)
        t = np.linspace(0, duration_s, num_samples, endpoint=False, dtype=np.float32)

        noise = self.rng.normal(0, 1.0, num_samples).astype(np.float32)
        from scipy.signal import butter, lfilter
        b, a = butter(4, 3000.0 / (self.sample_rate / 2.0), btype="high")
        filtered_noise = lfilter(b, a, noise).astype(np.float32)

        envelope = np.exp(-3.5 * t)  # Suy giảm nhanh trong 0.8 giây
        signal = 0.4 * (filtered_noise * envelope)
        return signal.astype(np.float32)
