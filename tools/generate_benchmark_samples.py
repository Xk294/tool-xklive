"""Script sinh các mẫu âm thanh kiểm chuẩn mô phỏng (.wav) có nhãn vào data/synthetic_recordings/."""

from __future__ import annotations
import math
from pathlib import Path
import wave
import numpy as np

from auto_sound.sim.room import RoomSimulator


def generate_benchmark_dataset(output_dir: Path, sample_rate: int = 48000) -> int:
    """Sinh tập mẫu âm thanh có nhãn vào data/synthetic_recordings."""
    output_dir.mkdir(parents=True, exist_ok=True)
    sim = RoomSimulator(sample_rate=sample_rate, seed=42)
    created = 0

    # 1. Các mẫu hú (feedback) tại nhiều dải tần số
    freqs = [800.0, 1600.0, 2500.0, 3150.0, 4000.0, 6300.0]
    for f in freqs:
        sig = sim.generate_feedback_loop(duration_s=1.2, target_freq_hz=f)
        wav_path = output_dir / f"feedback_{int(f)}hz.wav"
        _save_wav(wav_path, sig, sample_rate)
        created += 1

    # 2. Các mẫu âm nhạc / nhạc cụ (không hú)
    # Vocal ngân dài
    vocal = sim.generate_vocal_sustain(duration_s=1.2, freq_hz=440.0, with_vibrato=True)
    _save_wav(output_dir / "no_feedback_vocal_440hz.wav", vocal, sample_rate)
    created += 1

    # Guitar distortion
    guitar = sim.generate_guitar_distortion(duration_s=1.2, note_hz=330.0)
    _save_wav(output_dir / "no_feedback_guitar_330hz.wav", guitar, sample_rate)
    created += 1

    # Cymbal crash
    cymbal = sim.generate_cymbal_crash(duration_s=0.8)
    _save_wav(output_dir / "no_feedback_cymbal.wav", cymbal, sample_rate)
    created += 1

    return created


def _save_wav(path: Path, sig: np.ndarray, sample_rate: int) -> None:
    # Scale float [-1.0, 1.0] sang int16
    clamped = np.clip(sig, -1.0, 1.0)
    int16_data = (clamped * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(int16_data.tobytes())


if __name__ == "__main__":
    target = Path(__file__).resolve().parent.parent / "data" / "synthetic_recordings"
    count = generate_benchmark_dataset(target)
    print(f"Đã tạo {count} mẫu âm thanh vào {target}")
