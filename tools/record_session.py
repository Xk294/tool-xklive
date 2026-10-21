#!/usr/bin/env python3
"""Công cụ ghi âm phiên biểu diễn đa kênh kèm gắn nhãn thời gian thực (Data Recording CLI).

Mục tiêu (Giai đoạn C1):
- Ghi âm 16/18 kênh USB từ mixer Behringer XR/Midas MR (hoặc luồng ảo mô phỏng).
- Gắn nhãn thời gian thực (howl_start, howl_end, music, note) qua phím bấm hoặc CLI input.
- Xuất file âm thanh WAV đa kênh kèm cặp file nhãn labels.json và labels.csv.
- Phục vụ huấn luyện, tinh chỉnh ngưỡng và benchmark detector trên dữ liệu thực địa.
"""

from __future__ import annotations
import argparse
import csv
import json
import os
from pathlib import Path
import select
import sys
import termios
import threading
import time
import tty
import wave
from typing import Any, Dict, List, Optional
import numpy as np

# Bổ sung src vào sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

from auto_sound.audio.io import AudioCapture


class SessionRecorder:
    """Điều phối ghi âm đa kênh và đồng bộ nhãn thời gian thực."""

    def __init__(
        self,
        output_dir: Path,
        channels: int = 18,
        sample_rate: int = 48000,
        mock_mode: bool = False,
        session_name: Optional[str] = None,
    ) -> None:
        self.output_dir = output_dir
        self.channels = channels
        self.sample_rate = sample_rate
        self.mock_mode = mock_mode

        time_str = time.strftime("%Y%m%d_%H%M%S")
        self.session_id = session_name if session_name else f"session_{time_str}"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.wav_path = self.output_dir / f"{self.session_id}.wav"
        self.csv_path = self.output_dir / f"{self.session_id}_labels.csv"
        self.json_path = self.output_dir / f"{self.session_id}_labels.json"

        self._running = False
        self._wav_file: Optional[wave.Wave_write] = None
        self._audio_capture: Optional[AudioCapture] = None
        self._record_thread: Optional[threading.Thread] = None

        self.start_perf_time: float = 0.0
        self.total_frames_written: int = 0
        self.labels: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

        self._active_howl: Optional[Dict[str, Any]] = None

    def start(self) -> None:
        """Khởi động luồng thu âm và mở file WAV."""
        self._wav_file = wave.open(str(self.wav_path), "wb")
        self._wav_file.setnchannels(self.channels)
        self._wav_file.setsampwidth(2)  # 16-bit PCM
        self._wav_file.setframerate(self.sample_rate)

        # Trình sinh tín hiệu ảo nếu chạy mock
        def mock_signal_generator(frames: int, counter: int) -> np.ndarray:
            t = (counter + np.arange(frames)) / float(self.sample_rate)
            buf = np.zeros((frames, self.channels), dtype=np.float32)
            # Kênh 1: 1000 Hz nền nhỏ
            buf[:, 0] = 0.1 * np.sin(2 * np.pi * 1000.0 * t)
            # Kênh 2: Giọng nói giả lập
            buf[:, 1] = 0.05 * np.sin(2 * np.pi * 350.0 * t)
            return buf

        self._audio_capture = AudioCapture(
            channels=self.channels,
            sample_rate=self.sample_rate,
            is_virtual=self.mock_mode,
            virtual_generator=mock_signal_generator if self.mock_mode else None,
        )
        self._audio_capture.start()

        self._running = True
        self.start_perf_time = time.perf_counter()
        self._record_thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._record_thread.start()

    def _writer_loop(self) -> None:
        """Vòng lặp đọc SPSC ring buffer và ghi ra đĩa."""
        read_chunk_size = 512
        float_buf = np.zeros((read_chunk_size, self.channels), dtype=np.float32)

        while self._running:
            if not self._audio_capture:
                break

            if self._audio_capture.ring_buffer.available_read() >= read_chunk_size:
                n = self._audio_capture.ring_buffer.read(float_buf)
                if n > 0 and self._wav_file:
                    # Clip float [-1.0, 1.0] -> int16 [-32768, 32767]
                    clipped = np.clip(float_buf[:n], -1.0, 1.0)
                    pcm16 = (clipped * 32767.0).astype(np.int16)
                    self._wav_file.writeframes(pcm16.tobytes())
                    with self._lock:
                        self.total_frames_written += n
            else:
                time.sleep(0.002)

    def add_label(
        self,
        event_type: str,
        channel: Optional[int] = None,
        frequency_hz: Optional[float] = None,
        duration_s: Optional[float] = None,
        notes: str = "",
    ) -> Dict[str, Any]:
        """Ghi nhận sự kiện thời gian thực."""
        now_perf = time.perf_counter()
        timestamp_s = max(0.0, now_perf - self.start_perf_time)
        with self._lock:
            sample_idx = self.total_frames_written

        record = {
            "timestamp_s": round(timestamp_s, 3),
            "sample_index": sample_idx,
            "event_type": event_type,
            "duration_s": round(duration_s, 3) if duration_s is not None else None,
            "channel": channel,
            "frequency_hz": frequency_hz,
            "notes": notes,
        }
        with self._lock:
            self.labels.append(record)
        return record

    def tag_howl_start(self, channel: Optional[int] = None, freq_hz: Optional[float] = None, notes: str = "") -> None:
        """Bắt đầu tiếng hú."""
        now_perf = time.perf_counter()
        t_s = max(0.0, now_perf - self.start_perf_time)
        self._active_howl = {
            "start_perf": now_perf,
            "timestamp_s": t_s,
            "channel": channel,
            "freq_hz": freq_hz,
            "notes": notes,
        }
        self.add_label("howl_start", channel=channel, frequency_hz=freq_hz, notes=notes)
        print(f"\n[GẮN NHÃN] >>> BẮT ĐẦU HÚ (t={t_s:.2f}s | Kênh: {channel or 'All'} | Freq: {freq_hz or 'N/A'} Hz)")

    def tag_howl_end(self, notes: str = "") -> None:
        """Kết thúc tiếng hú và tính toán độ dài duration_s."""
        now_perf = time.perf_counter()
        duration_s: Optional[float] = None
        ch = None
        freq = None
        merged_notes = notes

        if self._active_howl:
            duration_s = now_perf - self._active_howl["start_perf"]
            ch = self._active_howl.get("channel")
            freq = self._active_howl.get("freq_hz")
            if not merged_notes:
                merged_notes = self._active_howl.get("notes", "")
            self._active_howl = None

        t_s = max(0.0, now_perf - self.start_perf_time)
        dur_str = f"{duration_s:.2f}s" if duration_s is not None else "N/A"
        self.add_label("howl_end", channel=ch, frequency_hz=freq, duration_s=duration_s, notes=merged_notes)
        print(f"\n[GẮN NHÃN] <<< KẾT THÚC HÚ (t={t_s:.2f}s | Độ dài: {dur_str})")

    def tag_music(self, notes: str = "Đoạn âm nhạc / ca sĩ ngân / nhạc cụ") -> None:
        """Ghi nhận phân đoạn âm nhạc mẫu (không hú)."""
        now_perf = time.perf_counter()
        t_s = max(0.0, now_perf - self.start_perf_time)
        self.add_label("music", notes=notes)
        print(f"\n[GẮN NHÃN] [♫] ĐOẠN ÂM NHẠC / KHÔNG HÚ (t={t_s:.2f}s | {notes})")

    def tag_custom_note(self, text: str) -> None:
        """Ghi chú tùy ý."""
        now_perf = time.perf_counter()
        t_s = max(0.0, now_perf - self.start_perf_time)
        self.add_label("note", notes=text)
        print(f"\n[GẮN NHÃN] [*] GHI CHÚ (t={t_s:.2f}s | {text})")

    def stop(self) -> None:
        """Dừng thu âm và kết xuất toàn bộ file."""
        self._running = False
        if self._audio_capture:
            self._audio_capture.stop()
        if self._record_thread and self._record_thread.is_alive():
            self._record_thread.join(timeout=1.0)
        if self._wav_file:
            self._wav_file.close()
            self._wav_file = None

        # Xuất file CSV
        fieldnames = ["timestamp_s", "sample_index", "event_type", "duration_s", "channel", "frequency_hz", "notes"]
        with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in self.labels:
                writer.writerow(row)

        # Xuất file JSON
        session_meta = {
            "session_id": self.session_id,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "channels": self.channels,
            "sample_rate": self.sample_rate,
            "total_frames": self.total_frames_written,
            "duration_s": round(self.total_frames_written / float(self.sample_rate), 2),
            "labels": self.labels,
        }
        with open(self.json_path, "w", encoding="utf-8") as f:
            json.dump(session_meta, f, ensure_ascii=False, indent=2)

        print("\n================ TỔNG KẾT PHIÊN GHI ÂM ================")
        print(f"  File âm thanh: {self.wav_path}")
        print(f"  File nhãn CSV: {self.csv_path}")
        print(f"  File nhãn JSON: {self.json_path}")
        print(f"  Tổng mẫu: {self.total_frames_written} frames ({session_meta['duration_s']}s)")
        print(f"  Tổng số nhãn: {len(self.labels)}")
        print("========================================================\n")


def run_interactive_session(recorder: SessionRecorder, max_duration_s: Optional[float] = None) -> None:
    """Vòng lặp tương tác phím nóng thời gian thực cho soundman."""
    recorder.start()
    print("\n=== ĐANG GHI ÂM PHIÊN DỮ LIỆU ĐA KÊNH ===")
    print("Phím nóng điều khiển:")
    print("  [h] : Đánh dấu BẮT ĐẦU HÚ (howl_start)")
    print("  [e] : Đánh dấu KẾT THÚC HÚ (howl_end)")
    print("  [m] : Đánh dấu ĐOẠN NHẠC / KHÔNG HÚ (music)")
    print("  [n] : Nhập GHI CHÚ tự do")
    print("  [q] : DỪNG GHI VÀ LƯU PHIÊN\n")

    start_t = time.time()
    old_term_settings = None
    is_tty = sys.stdin.isatty()

    if is_tty:
        try:
            old_term_settings = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
        except Exception:
            old_term_settings = None

    try:
        while True:
            elapsed = time.time() - start_t
            if max_duration_s and elapsed >= max_duration_s:
                print(f"\n[HẾT GIỜ] Đã đạt thời gian tối đa {max_duration_s}s.")
                break

            # Kiểm tra xem có phím nào được bấm không
            if is_tty and select.select([sys.stdin], [], [], 0.1)[0]:
                ch = sys.stdin.read(1)
                if ch.lower() == "h":
                    recorder.tag_howl_start()
                elif ch.lower() == "e":
                    recorder.tag_howl_end()
                elif ch.lower() == "m":
                    recorder.tag_music()
                elif ch.lower() == "n":
                    # Tạm khôi phục tty để nhập chuỗi
                    if old_term_settings:
                        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_term_settings)
                    try:
                        note_text = input("\nNhập nội dung ghi chú: ")
                        recorder.tag_custom_note(note_text)
                    finally:
                        if old_term_settings:
                            tty.setcbreak(sys.stdin.fileno())
                elif ch.lower() == "q":
                    print("\n[DỪNG] Người dùng yêu cầu kết thúc phiên.")
                    break
            else:
                time.sleep(0.05)

    except KeyboardInterrupt:
        print("\n[CẢNH BÁO] Nhận Ctrl-C. Đang lưu phiên ghi âm...")
    finally:
        if is_tty and old_term_settings:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_term_settings)
        recorder.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Công cụ ghi âm 16/18 kênh kèm gắn nhãn dữ liệu")
    parser.add_argument("--output-dir", default="data/recordings", help="Thư mục lưu trữ bản ghi")
    parser.add_argument("--name", default=None, help="Tên định danh phiên ghi (mặc định session_YYYYMMDD_HHMMSS)")
    parser.add_argument("--channels", type=int, default=18, help="Số kênh audio (mặc định 18 kênh cho XR18)")
    parser.add_argument("--rate", type=int, default=48000, help="Tần số lấy mẫu (mặc định 48000 Hz)")
    parser.add_argument("--mock", action="store_true", default=False, help="Chạy giả lập không cần soundcard thật")
    parser.add_argument("--duration-s", type=float, default=None, help="Tự động dừng sau N giây")

    args = parser.parse_args()

    rec = SessionRecorder(
        output_dir=Path(args.output_dir).resolve(),
        channels=args.channels,
        sample_rate=args.rate,
        mock_mode=args.mock,
        session_name=args.name,
    )
    run_interactive_session(rec, max_duration_s=args.duration_s)


if __name__ == "__main__":
    main()
