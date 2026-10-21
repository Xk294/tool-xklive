#!/usr/bin/env python3
"""Công cụ kiểm thử ngâm tải liên tục (Soak Test CLI) cho hệ thống Auto Sound Engineer.

Mục tiêu kiểm định:
- Chạy liên tục (mặc định 4 giờ = 14400s) để phát hiện rò rỉ bộ nhớ (RAM leak).
- Giám sát độ giật thời gian (Jitter) của luồng audio callback do GIL của Python.
- Đếm số lỗi tràn bộ đệm (xruns) của SPSC Ring Buffer.
- Đếm số lần rớt mạng / mất kết nối (reconnects) với mixer.
- Đo thời gian xử lý DSP mỗi khung 2048 mẫu (DSP processing time).
"""

from __future__ import annotations
import argparse
import json
import resource
import signal
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any, Dict, List, Optional
import numpy as np

# Bổ sung src vào sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

from auto_sound.audio.io import AudioCapture
from auto_sound.core.config import AppConfig
from auto_sound.core.models import ConnectionState
from auto_sound.dsp.detector import FeedbackDetector
from auto_sound.mixer.fake import FakeXR18
from auto_sound.mixer.parameter_mapper import ParameterMapper
from auto_sound.mixer.xair import XAirClient


class SoakTester:
    """Điều phối và giám sát bài kiểm thử ngâm tải liên tục."""

    def __init__(
        self,
        duration_s: float = 14400.0,
        mock_mode: bool = True,
        mixer_ip: str = "127.0.0.1",
        mixer_port: int = 10024,
        output_file: Optional[Path] = None,
    ) -> None:
        self.duration_s = duration_s
        self.mock_mode = mock_mode
        self.mixer_ip = mixer_ip
        self.mixer_port = mixer_port
        self.output_file = output_file

        self._running = False
        self.fake_mixer: Optional[FakeXR18] = None
        self.mixer_client: Optional[XAirClient] = None
        self.audio_capture: Optional[AudioCapture] = None
        self.detector: Optional[FeedbackDetector] = None

        self.jitter_records_ms: List[float] = []
        self.dsp_duration_records_ms: List[float] = []
        self.reconnect_count = 0
        self.total_audio_blocks = 0

        signal.signal(signal.SIGINT, self._handle_sigint)

    def _handle_sigint(self, signum: int, frame: Any) -> None:
        print("\n[CẢNH BÁO] Nhận tín hiệu dừng từ người dùng. Đang tổng hợp báo cáo ngâm tải...")
        self._running = False

    def start(self) -> None:
        """Khởi tạo toàn bộ các thành phần hệ thống phục vụ kiểm thử tải."""
        if self.mock_mode:
            print("[SOAK TEST] Khởi động mixer ảo FakeXR18 trên localhost...")
            self.fake_mixer = FakeXR18(host="127.0.0.1", port=0)
            self.fake_mixer.start()
            self.mixer_ip = self.fake_mixer.host
            self.mixer_port = self.fake_mixer.port

        cfg_path = ROOT_DIR / "device_profiles" / "xr18.toml"
        mapper = ParameterMapper.from_profile(cfg_path)

        self.mixer_client = XAirClient(
            ip=self.mixer_ip,
            port=self.mixer_port,
            mapper=mapper,
            timeout_s=0.5,
            reconnect_interval_s=1.0,
        )
        self.mixer_client.connect()

        self.detector = FeedbackDetector(sample_rate=48000, frame_size=2048, hop_size=512)

        # Bộ sinh tín hiệu ảo có tải tính toán liên tục
        def mock_signal_generator(frames: int, counter: int) -> np.ndarray:
            block = np.zeros((frames, 18), dtype=np.float32)
            t = (counter + np.arange(frames)) / 48000.0
            # Giả lập 4 kênh có tín hiệu âm nhạc đa tần
            block[:, 0] = 0.2 * np.sin(2 * np.pi * 440.0 * t)
            block[:, 1] = 0.2 * np.sin(2 * np.pi * 1000.0 * t)
            block[:, 2] = 0.2 * np.sin(2 * np.pi * 2500.0 * t)
            block[:, 3] = 0.1 * np.sin(2 * np.pi * 5000.0 * t)
            return block

        self.audio_capture = AudioCapture(
            channels=18,
            sample_rate=48000,
            is_virtual=self.mock_mode,
            virtual_generator=mock_signal_generator if self.mock_mode else None,
        )
        self.audio_capture.start()

    def run(self) -> Dict[str, Any]:
        """Vòng lặp ngâm tải chính."""
        tracemalloc.start()
        start_time = time.time()
        self._running = True

        read_buffer = np.zeros((512, 18), dtype=np.float32)
        rolling_frame = np.zeros(2048, dtype=np.float32)

        nominal_block_duration_ms = (512 / 48000.0) * 1000.0  # ~10.67 ms
        last_block_time: Optional[float] = None
        last_status_print = start_time
        last_conn_state: Optional[ConnectionState] = None

        print(f"\n=== BẮT ĐẦU SOAK TEST LIÊN TỤC TRONG {self.duration_s:.0f} GIÂY ({self.duration_s / 3600:.2f} GIỜ) ===")
        print("Đang giám sát RAM, Jitter, xruns, độ trễ DSP mỗi giây...\n")

        try:
            while self._running:
                now = time.time()
                elapsed = now - start_time
                if elapsed >= self.duration_s:
                    break

                # 1. Đọc audio và đo Jitter chu kỳ đọc
                if self.audio_capture and self.audio_capture.ring_buffer.available_read() >= 512:
                    t_read_start = time.perf_counter()
                    n = self.audio_capture.ring_buffer.read(read_buffer)

                    if n == 512:
                        self.total_audio_blocks += 1
                        if last_block_time is not None:
                            actual_delta_ms = (t_read_start - last_block_time) * 1000.0
                            jitter_ms = abs(actual_delta_ms - nominal_block_duration_ms)
                            # Giới hạn kích thước mảng lưu jitter để tránh tốn RAM
                            if len(self.jitter_records_ms) < 20000:
                                self.jitter_records_ms.append(jitter_ms)
                        last_block_time = t_read_start

                        # 2. Xử lý DSP trên Kênh 1 và đo thời gian thực thi
                        rolling_frame[: 2048 - 512] = rolling_frame[512:]
                        rolling_frame[2048 - 512 :] = read_buffer[:, 0]

                        t_dsp_start = time.perf_counter()
                        if self.detector:
                            self.detector.process_channel_frame(1, rolling_frame)
                        t_dsp_end = time.perf_counter()

                        dsp_ms = (t_dsp_end - t_dsp_start) * 1000.0
                        if len(self.dsp_duration_records_ms) < 20000:
                            self.dsp_duration_records_ms.append(dsp_ms)
                else:
                    time.sleep(0.001)

                # 3. Giám sát trạng thái kết nối mixer (đếm sự kiện chuyển sang RECONNECTING)
                if self.mixer_client:
                    curr_conn_state = self.mixer_client.get_state()
                    if curr_conn_state == ConnectionState.RECONNECTING and last_conn_state != ConnectionState.RECONNECTING:
                        self.reconnect_count += 1
                    last_conn_state = curr_conn_state

                # 4. In tiến độ định kỳ mỗi 5 giây
                if now - last_status_print >= 5.0:
                    current_ram_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024 if sys.platform == "darwin" else 1024)
                    xruns = int(self.audio_capture.ring_buffer.xrun_count[0]) if self.audio_capture else 0
                    avg_jitter = np.mean(self.jitter_records_ms[-100:]) if self.jitter_records_ms else 0.0
                    avg_dsp = np.mean(self.dsp_duration_records_ms[-100:]) if self.dsp_duration_records_ms else 0.0

                    sys.stdout.write(
                        f"\r[SOAK {elapsed:.0f}s/{self.duration_s:.0f}s] "
                        f"RAM: {current_ram_mb:.1f}MB | "
                        f"Audio Blocks: {self.total_audio_blocks} | "
                        f"xruns: {xruns} | "
                        f"Jitter tb: {avg_jitter:.2f}ms | "
                        f"DSP tb: {avg_dsp:.2f}ms | "
                        f"Reconnects: {self.reconnect_count}"
                    )
                    sys.stdout.flush()
                    last_status_print = now

        finally:
            self._cleanup()

        # Tổng hợp số liệu
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        final_xruns = int(self.audio_capture.ring_buffer.xrun_count[0]) if self.audio_capture else 0
        final_ram_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024 if sys.platform == "darwin" else 1024)

        jitter_array = np.array(self.jitter_records_ms) if self.jitter_records_ms else np.array([0.0])
        dsp_array = np.array(self.dsp_duration_records_ms) if self.dsp_duration_records_ms else np.array([0.0])

        report: Dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "target_duration_s": self.duration_s,
            "actual_duration_s": round(time.time() - start_time, 2),
            "mock_mode": self.mock_mode,
            "total_audio_blocks_processed": self.total_audio_blocks,
            "xruns_count": final_xruns,
            "reconnect_events": self.reconnect_count,
            "ram_metrics": {
                "final_rss_mb": round(final_ram_mb, 2),
                "tracemalloc_peak_mb": round(peak / (1024 * 1024), 2),
            },
            "audio_jitter_ms": {
                "mean": round(float(np.mean(jitter_array)), 3),
                "p50": round(float(np.percentile(jitter_array, 50)), 3),
                "p95": round(float(np.percentile(jitter_array, 95)), 3),
                "p99": round(float(np.percentile(jitter_array, 99)), 3),
                "max": round(float(np.max(jitter_array)), 3),
            },
            "dsp_processing_time_ms": {
                "mean": round(float(np.mean(dsp_array)), 3),
                "p50": round(float(np.percentile(dsp_array, 50)), 3),
                "p95": round(float(np.percentile(dsp_array, 95)), 3),
                "max": round(float(np.max(dsp_array)), 3),
            },
            "passed": bool(final_xruns == 0 and self.reconnect_count == 0),
        }

        print("\n\n================ KẾT QUẢ SOAK TEST TỔNG HỢP ================")
        print(f"  Thời gian chạy thực tế: {report['actual_duration_s']} giây")
        print(f"  Tổng số block âm thanh: {report['total_audio_blocks_processed']}")
        print(f"  Bộ đệm xruns (rớt mẫu): {report['xruns_count']}")
        print(f"  Số lần rớt kết nối mạng: {report['reconnect_events']}")
        print(f"  RAM Peak: {report['ram_metrics']['tracemalloc_peak_mb']} MB | Final RSS: {report['ram_metrics']['final_rss_mb']} MB")
        print(f"  Jitter âm thanh (ms): p50={report['audio_jitter_ms']['p50']} | p95={report['audio_jitter_ms']['p95']} | Max={report['audio_jitter_ms']['max']}")
        print(f"  DSP Processing (ms): p50={report['dsp_processing_time_ms']['p50']} | p95={report['dsp_processing_time_ms']['p95']} | Max={report['dsp_processing_time_ms']['max']}")
        print(f"  Đánh giá đạt chuẩn: {'ĐẠT (PASSED)' if report['passed'] else 'CẦN KIỂM TRA (FAILED/WARNING)'}")
        print("============================================================")

        if self.output_file:
            self.output_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.output_file, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            print(f"Báo cáo chi tiết đã được ghi vào: {self.output_file}")

        return report

    def _cleanup(self) -> None:
        """Thu dọn tài nguyên an toàn."""
        self._running = False
        if self.audio_capture:
            self.audio_capture.stop()
        if self.mixer_client:
            self.mixer_client.disconnect()
        if self.fake_mixer:
            self.fake_mixer.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Công cụ kiểm thử ngâm tải liên tục (Soak Test)")
    parser.add_argument("--duration-s", type=float, default=14400.0, help="Thời gian chạy tính bằng giây (mặc định: 14400s = 4 giờ)")
    parser.add_argument("--mock", action="store_true", default=True, help="Chạy ở chế độ mô phỏng với FakeXR18")
    parser.add_argument("--real", action="store_true", help="Chạy với mixer thật trên mạng LAN (tắt mock)")
    parser.add_argument("--ip", default="192.168.1.100", help="Địa chỉ IP của mixer thật")
    parser.add_argument("--port", type=int, default=10024, help="Cổng OSC của mixer thật")
    parser.add_argument("--output", default="soak_report.json", help="Đường dẫn lưu file JSON báo cáo")

    args = parser.parse_args()

    mock_mode = False if args.real else args.mock
    tester = SoakTester(
        duration_s=args.duration_s,
        mock_mode=mock_mode,
        mixer_ip=args.ip,
        mixer_port=args.port,
        output_file=Path(args.output).resolve(),
    )
    tester.start()
    tester.run()


if __name__ == "__main__":
    main()
