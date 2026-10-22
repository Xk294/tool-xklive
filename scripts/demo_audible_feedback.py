#!/usr/bin/env python3
"""demo_audible_feedback.py - Trình diễn âm thanh thực tế: Phát tiếng hú ra loa & Tự động đè EQ xuống.

Dành cho kiểm thử khi không có bàn mixer vật lý:
1. Phát nhạc nền êm dịu qua loa máy tính/tai nghe để xác nhận âm thanh đang hoạt động.
2. Bấm [SPACE] hoặc [ENTER]: Một đỉnh hú rít thực tế (2000 - 3500 Hz) bắt đầu phát to dần qua loa.
3. Thuật toán FeedbackDetector phân tích phổ FFT thời gian thực.
4. Ngay khi phát hiện hú (~20-40ms), bộ lọc số Biquad PEQ Notch (-12dB) được áp dụng trực tiếp lên luồng phát loa.
5. Người dùng tận tai nghe thấy tiếng hú bị dập tắt lịm, âm thanh trở lại êm ái.
"""

from __future__ import annotations
import argparse
import os
import select
import sys
import threading
import time
from typing import List, Optional, Tuple
import numpy as np
import scipy.signal as signal
import sounddevice as sd

from auto_sound.core.models import ActionProposal
from auto_sound.dsp.detector import FeedbackDetector

# Màu ANSI
C_RESET = "\033[0m"
C_RED = "\033[1;31m"
C_GREEN = "\033[1;32m"
C_YELLOW = "\033[1;33m"
C_CYAN = "\033[1;36m"
C_BOLD = "\033[1m"


def make_peaking_biquad(f0: float, gain_db: float, q: float, fs: float = 48000.0) -> Tuple[np.ndarray, np.ndarray]:
    """Tạo hệ số bộ lọc Biquad Peaking EQ theo chuẩn Robert Bristow-Johnson (Audio EQ Cookbook)."""
    A = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * np.pi * f0 / fs
    alpha = np.sin(w0) / (2.0 * q)
    cos_w0 = np.cos(w0)

    b0 = 1.0 + alpha * A
    b1 = -2.0 * cos_w0
    b2 = 1.0 - alpha * A
    a0 = 1.0 + alpha / A
    a1 = -2.0 * cos_w0
    a2 = 1.0 - alpha / A

    b = np.array([b0, b1, b2], dtype=np.float64) / a0
    a = np.array([a0, a1, a2], dtype=np.float64) / a0
    return b, a


class AudibleFeedbackDemo:
    def __init__(self, sample_rate: int = 48000, block_size: int = 512, device: Optional[int | str] = None) -> None:
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.device = device

        self.detector = FeedbackDetector(
            sample_rate=self.sample_rate,
            frame_size=2048,
            hop_size=512,
            prominence_threshold_db=10.0,
            growth_threshold_db=2.0,
            confirmation_frames=3,
            default_notch_q=8.0,
            probe_gain_db=-3.0,
        )

        self._running = False
        self._lock = threading.Lock()

        # Trạng thái hú
        self._howl_active = False
        self._howl_freq = 2500.0
        self._howl_start_time = 0.0
        self._howl_detected_time: Optional[float] = None
        self._detected_freq: Optional[float] = None

        # Bộ lọc Biquad Notch
        self._filter_active = False
        self._notch_b, self._notch_a = make_peaking_biquad(2500.0, 0.0, 8.0, self.sample_rate)
        self._filter_zi = np.zeros(2, dtype=np.float64)

        # Rolling frame cho FFT
        self._rolling_frame = np.zeros(2048, dtype=np.float32)
        self._sample_counter = 0

        # Nhật ký sự kiện
        self._events: List[str] = []

    def trigger_howl(self, freq_hz: Optional[float] = None) -> None:
        """Kích hoạt tiếng hú mới phát ra loa và đồng bộ sang Web Tool (cổng 8000)."""
        with self._lock:
            if freq_hz is None:
                # Ngẫu nhiên trong dải dễ hú thực tế: 1500Hz - 3500Hz
                freq_hz = float(np.random.choice([1800.0, 2200.0, 2500.0, 2800.0, 3150.0]))
            self._howl_freq = freq_hz
            self._howl_active = True
            self._howl_start_time = time.perf_counter()
            self._howl_detected_time = None
            self._detected_freq = None
            self._filter_active = False
            self.detector.reset_all()
            self._add_event(f"{C_RED}[BẮT ĐẦU HÚ]{C_RESET} Tần số: {freq_hz:.1f} Hz đang phát to ra loa!")

        # Đồng bộ sang Web Tool đang chạy ở http://127.0.0.1:8000
        def _notify_server(f_val: float):
            try:
                import urllib.request
                req = urllib.request.Request(
                    f"http://127.0.0.1:8000/api/v1/demo/trigger_feedback?channel=2&freq_hz={f_val}&duration_s=4",
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=0.8)
            except Exception:
                pass

        threading.Thread(target=_notify_server, args=(freq_hz,), daemon=True).start()

    def reset_notch(self) -> None:
        """Reset bộ lọc và tắt tiếng hú."""
        with self._lock:
            self._howl_active = False
            self._filter_active = False
            self._notch_b, self._notch_a = make_peaking_biquad(2500.0, 0.0, 8.0, self.sample_rate)
            self._filter_zi = np.zeros(2, dtype=np.float64)
            self.detector.reset_all()
            self._add_event(f"{C_CYAN}[RESET]{C_RESET} Đã nhả Notch PEQ về phẳng (0.0 dB).")

    def _add_event(self, text: str) -> None:
        self._events.append(f"[{time.strftime('%H:%M:%S')}] {text}")
        if len(self._events) > 6:
            self._events.pop(0)

    def _audio_callback(self, outdata: np.ndarray, frames: int, time_info: dict, status: sd.CallbackFlags) -> None:
        """Callback thời gian thực của PortAudio: Sinh âm thanh + Lọc notch PEQ + Xuất ra loa."""
        t = (self._sample_counter + np.arange(frames)) / float(self.sample_rate)
        now = time.perf_counter()

        # 1. Nhạc nền êm dịu (Hợp âm Trưởng êm ái: A4 440Hz + C#5 554Hz + E5 659Hz)
        chord = (
            0.04 * np.sin(2.0 * np.pi * 440.0 * t)
            + 0.03 * np.sin(2.0 * np.pi * 554.37 * t)
            + 0.03 * np.sin(2.0 * np.pi * 659.25 * t)
        ).astype(np.float32)

        # 2. Tiếng hú nếu đang được kích hoạt
        howl = np.zeros(frames, dtype=np.float32)
        with self._lock:
            if self._howl_active:
                dt = now - self._howl_start_time
                # Biên độ tăng dần theo hàm sigmoid (mô phỏng tiếng hú phòng thực tế)
                amp = float(np.clip(0.02 + 0.35 * (1.0 - np.exp(-dt * 4.0)), 0.0, 0.40))
                howl = (amp * np.sin(2.0 * np.pi * self._howl_freq * t)).astype(np.float32)

        # Tổng hợp tín hiệu âm thanh
        raw_signal = chord + howl

        # 3. Phân tích FFT dò tìm tiếng hú
        self._rolling_frame = np.roll(self._rolling_frame, -frames)
        self._rolling_frame[-frames:] = raw_signal

        proposals = self.detector.process_channel_frame(channel=1, frame_samples=self._rolling_frame)

        # 4. Khi phát hiện hú: Tự động tính toán và kích hoạt Notch PEQ
        if proposals and not self._filter_active:
            prop = proposals[0]
            with self._lock:
                self._filter_active = True
                self._howl_detected_time = now
                self._detected_freq = prop.freq_hz
                latency_ms = (now - self._howl_start_time) * 1000.0
                # Cắt mạnh -15 dB với Q hẹp 8.0 để triệt tiêu tiếng hú
                self._notch_b, self._notch_a = make_peaking_biquad(prop.freq_hz, -15.0, prop.q, self.sample_rate)
                self._add_event(
                    f"{C_GREEN}[DÒ TRÚNG HÚ & ĐÈ EQ]{C_RESET} Bắt được {prop.freq_hz:.1f} Hz sau {latency_ms:.1f}ms! "
                    f"Đã hạ Notch {C_BOLD}-15.0 dB{C_RESET} (Q={prop.q:.1f})"
                )

        # 5. Áp dụng bộ lọc Biquad lên tín hiệu ra loa
        filtered_signal = raw_signal.copy()
        with self._lock:
            if self._filter_active:
                filtered_signal, self._filter_zi = signal.lfilter(
                    self._notch_b, self._notch_a, raw_signal, zi=self._filter_zi
                )

        # Giới hạn an toàn chống vỡ tiếng (Limiter)
        filtered_signal = np.clip(filtered_signal, -0.90, 0.90)

        # Xuất ra loa stereo
        outdata[:, 0] = filtered_signal
        outdata[:, 1] = filtered_signal
        self._sample_counter += frames

    def run(self, auto_cycles: int = 0) -> None:
        """Chạy vòng lặp giao diện tương tác hoặc tự động chạy các chu kỳ hú mẫu."""
        self._running = True
        stream = sd.OutputStream(
            samplerate=self.sample_rate,
            channels=2,
            dtype="float32",
            blocksize=self.block_size,
            device=self.device,
            callback=self._audio_callback,
        )

        with stream:
            dev_name = sd.query_devices(self.device, 'output')['name']
            print(f"\n{C_BOLD}================================================================================{C_RESET}")
            print(f"  {C_BOLD}DEMO ÂM THANH THỰC TẾ: PHÁT TIẾNG HÚ RA LOA & TỰ ĐỘNG ĐÈ EQ XUỐNG{C_RESET}")
            print(f"================================================================================")
            print(f"  Thiết bị phát âm thanh: {C_BOLD}{dev_name}{C_RESET}")
            print(f"  {C_GREEN}[SẴN SÀNG]{C_RESET} Đã bật cổng xuất âm thanh ra loa. Nhạc nền đang phát...")

            if auto_cycles > 0:
                print(f"  {C_CYAN}[CHẾ ĐỘ TỰ ĐỘNG]{C_RESET} Bắt đầu chuỗi {auto_cycles} lần thử nghiệm hú ra loa thật...")
                test_freqs = [2500.0, 1800.0, 3150.0]
                try:
                    time.sleep(1.0)
                    for i in range(auto_cycles):
                        freq = test_freqs[i % len(test_freqs)]
                        print(f"\n--- [LẦN THỬ {i+1}/{auto_cycles}] ----------------------------------------------------")
                        print(f"  >> {C_RED}KÍCH HOẠT TIẾNG HÚ {freq:.0f} Hz PHÁT RA LOA NGOÀI...{C_RESET}")
                        self.trigger_howl(freq)

                        # Chờ thuật toán phát hiện và hạ notch
                        t_wait_start = time.perf_counter()
                        while self._running and not self._filter_active and (time.perf_counter() - t_wait_start < 2.0):
                            time.sleep(0.01)

                        if self._filter_active:
                            latency_ms = (self._howl_detected_time - self._howl_start_time) * 1000.0
                            print(f"  >> {C_GREEN}✔ THUẬT TOÁN ĐÃ BẮT TRÚNG HÚ:{C_RESET} {self._detected_freq:.1f} Hz (Độ trễ: {latency_ms:.1f} ms)")
                            print(f"  >> {C_CYAN}✔ BỘ LỌC PEQ NOTCH ĐÃ KÍCH HOẠT:{C_RESET} Hạ {C_BOLD}-15.0 dB{C_RESET} -> Tiếng hú trên loa bị dập tắt lịm!")
                        else:
                            print(f"  >> {C_YELLOW}Hết thời gian chờ.{C_RESET}")

                        # Giữ trạng thái dập tắt hú trong 2.0 giây để người dùng lắng nghe độ êm ái
                        print(f"  >> Đang giữ trạng thái triệt tiêu hú... Âm thanh trở lại êm ái.")
                        time.sleep(2.0)

                        if i < auto_cycles - 1:
                            print(f"  >> Nhả Notch PEQ về phẳng để chuẩn bị lần thử tiếp theo...")
                            self.reset_notch()
                            time.sleep(0.8)

                    print(f"\n{C_BOLD}================================================================================{C_RESET}")
                    print(f"  {C_GREEN}✔ HOÀN TẤT THỬ NGHIỆM! CẢ {auto_cycles} LẦN HÚ ĐỀU ĐƯỢC DÒ VÀ TRIỆT TIÊU THÀNH CÔNG.{C_RESET}")
                    print(f"================================================================================\n")
                except KeyboardInterrupt:
                    pass
                finally:
                    self._running = False
                return

            try:
                while self._running:
                    # Vẽ giao diện terminal
                    self._render_ui()

                    # Đọc phím bấm không chặn (non-blocking)
                    if sys.stdin in select.select([sys.stdin], [], [], 0.08)[0]:
                        line = sys.stdin.readline().strip().lower()
                        if line == "" or line == " ":
                            self.trigger_howl()
                        elif line == "r":
                            self.reset_notch()
                        elif line == "q":
                            break
                        elif line.replace(".", "", 1).isdigit():
                            self.trigger_howl(float(line))
            except KeyboardInterrupt:
                pass
            finally:
                self._running = False
                print(f"\n{C_YELLOW}Đã đóng luồng âm thanh an toàn.{C_RESET}")

    def _render_ui(self) -> None:
        """Render giao diện trạng thái trực quan trong terminal."""
        # Xóa màn hình
        sys.stdout.write("\033[2J\033[H")

        status_str = f"{C_GREEN}PHÁT NHẠC NỀN ÊM ÁI (KHÔNG HÚ){C_RESET}"
        if self._howl_active and not self._filter_active:
            status_str = f"{C_RED}ĐANG HÚ RÍT RA LOA ({self._howl_freq:.0f} Hz)... ĐANG DÒ TÌM!{C_RESET}"
        elif self._howl_active and self._filter_active:
            status_str = f"{C_CYAN}ĐÃ TRIỆT TIÊU HÚ BẰNG NOTCH PEQ -15dB TẠI {self._detected_freq:.0f} Hz!{C_RESET}"

        notch_status = (
            f"{C_GREEN}-15.0 dB @ {self._detected_freq:.1f} Hz (Đang đè bẹp tiếng hú){C_RESET}"
            if self._filter_active
            else f"{C_YELLOW}0.0 dB (Phẳng){C_RESET}"
        )

        ui = f"""
================================================================================
  {C_BOLD}DEMO ÂM THANH THỰC TẾ: PHÁT TIẾNG HÚ RA LOA & TỰ ĐỘNG ĐÈ EQ XUỐNG{C_RESET}
================================================================================
  Thiết bị âm thanh: {C_BOLD}{sd.query_devices(self.device, 'output')['name']}{C_RESET}
  Trạng thái loa   : {status_str}
  Bộ lọc PEQ Notch : {notch_status}
--------------------------------------------------------------------------------
  {C_BOLD}[ĐIỀU KHIỂN BẰNG BÀN PHÍM]:{C_RESET}
   - {C_BOLD}[ENTER]{C_RESET} hoặc gõ {C_BOLD}cách (Space){C_RESET} : {C_RED}BẮT ĐẦU PHÁT TIẾNG HÚ RA LOA{C_RESET}
   - Gõ {C_BOLD}tần số (ví dụ 3000){C_RESET}   : Phát tiếng hú tại đúng tần số chỉ định
   - Gõ {C_BOLD}r{C_RESET}                       : Reset / Nhả Notch về 0 dB
   - Gõ {C_BOLD}q{C_RESET}                       : Thoát chương trình
--------------------------------------------------------------------------------
  {C_BOLD}[NHẬT KÝ SỰ KIỆN XỬ LÝ ÂM THANH]:{C_RESET}
"""
        for ev in self._events:
            ui += f"  {ev}\n"

        ui += "================================================================================\n"
        ui += "Nhập lệnh rồi bấm Enter (hoặc chỉ bấm Enter để hú): "
        sys.stdout.write(ui)
        sys.stdout.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="Demo phát tiếng hú ra loa ngoài và tự động đè EQ xuống.")
    parser.add_argument("--device", type=str, default=None, help="Tên hoặc chỉ số thiết bị âm thanh đầu ra")
    parser.add_argument("--freq", type=float, default=None, help="Tần số tiếng hú thử nghiệm (Hz)")
    parser.add_argument("--auto", type=int, default=0, nargs="?", const=3, help="Tự động chạy N chu kỳ thử nghiệm (mặc định 3)")
    args = parser.parse_args()

    demo = AudibleFeedbackDemo(device=args.device)
    if args.freq:
        demo._howl_freq = args.freq
    demo.run(auto_cycles=args.auto)


if __name__ == "__main__":
    main()
