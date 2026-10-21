"""Giao diện dòng lệnh (CLI) tiếng Việt đơn giản, hiệu quả cho kỹ sư âm thanh."""

from __future__ import annotations
import argparse
import json
import logging
import os
import queue
import select
import sys
import threading
import time
from pathlib import Path
from typing import Any, List, Optional
import numpy as np

from auto_sound.audio.io import AudioCapture
from auto_sound.core.config import AppConfig
from auto_sound.core.models import ActionProposal, ConnectionState
from auto_sound.dsp.detector import FeedbackDetector
from auto_sound.dsp.rta_detector import RTADetector
from auto_sound.mixer.fake import FakeXR18
from auto_sound.mixer.parameter_mapper import ParameterMapper
from auto_sound.mixer.xair import XAirClient
from auto_sound.safety.controller import (
    SafetyState,
    check_auto_release,
    decide,
    handle_manual_override,
    panic_rollback,
)
from auto_sound.sim.room import RoomSimulator

# Mã màu ANSI hiển thị terminal
C_RESET = "\033[0m"
C_RED = "\033[1;31m"
C_GREEN = "\033[1;32m"
C_YELLOW = "\033[1;33m"
C_CYAN = "\033[1;36m"
C_BOLD = "\033[1m"


class AutoSoundApp:
    """Ứng dụng điều phối toàn bộ chu trình: Thu âm -> Dò hú -> Kiểm duyệt -> Gửi lệnh mixer."""

    def __init__(
        self,
        config: AppConfig,
        mapper: ParameterMapper,
        mock_mode: bool = False,
        mode: str = "auto",
    ) -> None:
        self.config = config
        self.mapper = mapper
        self.mock_mode = mock_mode
        self.mode = mode  # "auto", "semi", "manual"

        self.fake_mixer: Optional[FakeXR18] = None
        self.mixer_client: Optional[XAirClient] = None
        self.audio_capture: Optional[AudioCapture] = None
        self.detector: Optional[FeedbackDetector] = None
        self.rta_detector: Optional[RTADetector] = None

        self._cmd_queue: queue.Queue[ActionProposal] = queue.Queue()
        self._network_thread: Optional[threading.Thread] = None

        whitelist = set(self.config.channels.mic_channels)
        allowed_bands = {ch: tuple(self.config.eq.auto_notch_bands) for ch in self.config.channels.mic_channels}
        # Nếu thiết bị chạy chế độ RTA mạng LAN (XR12/XR16/MR12) -> Thêm kênh 0 (Main Stereo) vào whitelist
        if not self.config.device.has_multichannel_usb:
            whitelist.add(0)
            allowed_bands[0] = tuple(self.config.eq.main_auto_notch_bands)

        self.safety_state = SafetyState(
            whitelist=whitelist,
            allowed_bands=allowed_bands,
            max_boost_db=self.config.safety.max_boost_db,
            max_cut_db=self.config.safety.max_cut_db,
            probe_step_db=self.config.safety.probe_step_db,
            probe_wait_ms=self.config.safety.probe_wait_ms,
            max_transactions_per_sec=self.config.safety.max_transactions_per_sec,
            lock_duration_s=self.config.safety.manual_override_lock_s,
            reclaim_on_exhaustion=True,
            auto_release_wait_s=self.config.safety.auto_release_wait_s,
            auto_release_rate_db_per_s=self.config.safety.auto_release_rate_db_per_s,
            auto_release_enabled=True,
        )

        self.pending_proposals: List[ActionProposal] = []
        self._running = False

    def log_event(self, event_type: str, details: dict) -> None:
        """Ghi nhật ký JSON có cấu trúc dùng chung timestamp cho audio và mixer."""
        entry = {
            "timestamp": time.time(),
            "event": event_type,
            "data": details,
        }
        sys.stderr.write(json.dumps(entry, ensure_ascii=False) + "\n")
        sys.stderr.flush()

    def start(self) -> None:
        """Khởi động toàn bộ các thành phần."""
        print(f"{C_BOLD}=== KHỞI ĐỘNG HỆ THỐNG AUTO SOUND ENGINEER (XR18) ==={C_RESET}")

        target_ip = self.config.network.default_mixer_ip
        target_port = self.config.device.port

        if self.mock_mode:
            print(f"{C_YELLOW}[MÔ PHỎNG] Đang khởi động mixer ảo FakeXR18 trên localhost...{C_RESET}")
            self.fake_mixer = FakeXR18(host="127.0.0.1", port=0)
            self.fake_mixer.start()
            target_ip = self.fake_mixer.host
            target_port = self.fake_mixer.port

        # Khởi tạo mixer client
        self.mixer_client = XAirClient(
            ip=target_ip,
            port=target_port,
            mapper=self.mapper,
            heartbeat_interval_s=self.config.device.heartbeat_interval_s,
            timeout_s=1.0,
            reconnect_interval_s=self.config.device.reconnect_timeout_s,
        )
        self.mixer_client.connect()
        self.mixer_client.on_param_update = self._on_mixer_param_change

        # Khởi tạo detector & audio capture tùy theo loại thiết bị
        if not self.config.device.has_multichannel_usb:
            print(f"{C_CYAN}[CHẾ ĐỘ RTA MẠNG LAN] {self.config.device.name} không có USB đa kênh.{C_RESET}")
            print(f"{C_CYAN}  -> Kích hoạt tự động quét phổ RTA 100-band và hạ notch PEQ trên Main Stereo L/R.{C_RESET}")
            self.rta_detector = RTADetector(
                num_bins=100,
                f_min_hz=self.config.eq.freq_min_hz,
                f_max_hz=self.config.eq.freq_max_hz,
                prominence_threshold_db=10.0,
                growth_threshold_db=2.0,
                confirmation_frames=3,
                default_notch_q=self.config.eq.q_max,
                probe_gain_db=self.config.safety.probe_step_db,
            )
            self.mixer_client.on_rta_update = self._on_rta_levels_received
            self.mixer_client.subscribe_rta(enable=True)
            self.audio_capture = None
        else:
            self.detector = FeedbackDetector(
                sample_rate=48000,
                frame_size=2048,
                hop_size=512,
                prominence_threshold_db=10.0,
                growth_threshold_db=2.0,
                confirmation_frames=3,
                default_notch_q=self.config.eq.q_max,
                probe_gain_db=self.config.safety.probe_step_db,
            )

            # Khởi tạo bộ thu âm thanh
            if self.mock_mode:
                sim = RoomSimulator(sample_rate=48000, seed=42)
                # Tạo bộ sinh tín hiệu ảo có chèn tiếng hú định kỳ trên kênh 2
                def mock_audio_generator(frames: int, counter: int) -> np.ndarray:
                    block = np.zeros((frames, 18), dtype=np.float32)
                    t = (counter + np.arange(frames)) / 48000.0
                    # Kênh 1: Ca sĩ hát (nốt nhạc bình thường)
                    block[:, 0] = 0.2 * np.sin(2 * np.pi * 440.0 * t)
                    # Kênh 2: Sau 3 giây thì chớm hú tại 2500 Hz
                    if counter > 48000 * 2:
                        block[:, 1] = 0.4 * np.sin(2 * np.pi * 2500.0 * t)
                    return block

                self.audio_capture = AudioCapture(
                    channels=18,
                    sample_rate=48000,
                    is_virtual=True,
                    virtual_generator=mock_audio_generator,
                )
            else:
                self.audio_capture = AudioCapture(channels=18, sample_rate=48000, is_virtual=False)

            self.audio_capture.start()

        self._running = True

        # Khởi động worker mạng chạy nền để cách ly hoàn toàn độ trễ OSC khỏi luồng audio
        self._network_thread = threading.Thread(
            target=self._network_worker_loop, daemon=True, name="MixerNetworkWorker"
        )
        self._network_thread.start()

        self.log_event("system_start", {"mock_mode": self.mock_mode, "mode": self.mode, "mixer": f"{target_ip}:{target_port}"})

    def stop(self) -> None:
        """Dừng sạch sẽ toàn bộ hệ thống."""
        self._running = False
        if self._network_thread and self._network_thread.is_alive():
            self._network_thread.join(timeout=1.0)
        if self.audio_capture:
            self.audio_capture.stop()
        if self.mixer_client:
            self.mixer_client.disconnect()
        if self.fake_mixer:
            self.fake_mixer.stop()
        print(f"\n{C_YELLOW}Hệ thống đã dừng an toàn.{C_RESET}")

    def _network_worker_loop(self) -> None:
        """Worker chạy nền xử lý hàng đợi lệnh gửi tới mixer, không bao giờ làm block luồng audio."""
        while self._running:
            try:
                prop = self._cmd_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                self._send_proposal_to_mixer(prop)
            except Exception as e:
                self.log_event("network_worker_error", {"error": str(e)})
            finally:
                self._cmd_queue.task_done()

    def _on_rta_levels_received(self, levels_db: List[float]) -> None:
        """Xử lý gói tin RTA 100-band nhận được từ mixer qua mạng LAN."""
        if not self.rta_detector:
            return
        proposals = self.rta_detector.process_rta_frame(levels_db, target_name="main")
        now = time.time()
        for prop in proposals:
            self.safety_state, decision = decide(self.safety_state, prop, now=now)
            if decision.approved and decision.proposal:
                approved_p = decision.proposal
                if self.mode == "auto":
                    self.execute_proposal(approved_p)
                else:
                    self.pending_proposals.append(approved_p)
                    print(
                        f"\n{C_RED}[CẢNH BÁO ĐỎ] Dàn loa Main L/R chớm hú tại "
                        f"{approved_p.freq_hz:.0f}Hz! Bấm [SPACE] để duyệt hạ notch.{C_RESET}"
                    )

    def _on_mixer_param_change(self, address: str, val: Any) -> None:
        """Tự động khóa 10s khi phát hiện Soundman can thiệp thủ công từ iPad hoặc mặt bàn mixer."""
        if address.startswith("/ch/") and ("/eq/" in address or "/mix/" in address):
            try:
                parts = address.split("/")
                ch = int(parts[2])
                if ch in self.safety_state.whitelist:
                    now = time.time()
                    self.safety_state = handle_manual_override(self.safety_state, channel=ch, now=now)
                    print(
                        f"\n{C_YELLOW}[KHÓA AN TOÀN] Kỹ sư chỉnh tay Kênh {ch} — Tự động khóa can thiệp trong 10 giây.{C_RESET}"
                    )
                    self.log_event(
                        "manual_override_lock",
                        {"channel": ch, "address": address, "lock_until": now + self.safety_state.lock_duration_s},
                    )
            except Exception:
                pass

    def _send_proposal_to_mixer(self, prop: ActionProposal) -> bool:
        """Thực thi gửi lệnh notch PEQ đã được phê duyệt sang mixer và xác nhận."""
        if not self.mixer_client or self.mixer_client.get_state() != ConnectionState.CONNECTED:
            print(f"\n{C_RED}[LỖI MẠNG] Không thể gửi lệnh: Mixer chưa kết nối!{C_RESET}")
            return False

        target_name = "Main LR" if (prop.target == "main" or prop.channel == 0) else f"Kênh {prop.channel}"
        assert prop.band is not None
        success = self.mixer_client.set_peq(
            channel=prop.channel,
            band=prop.band,
            freq_hz=prop.freq_hz,
            gain_db=prop.gain_db,
            q=prop.q,
            is_on=True,
            target=prop.target,
        )

        if success:
            if "[CẠN BAND]" in prop.reason:
                print(f"\n{C_YELLOW}{prop.reason}{C_RESET}")
                self.log_event("band_exhaustion_reclaim", {
                    "channel": prop.channel,
                    "band": prop.band,
                    "freq_hz": prop.freq_hz,
                    "reason": prop.reason,
                })
            elif "Auto-release" in prop.reason:
                print(f"\n{C_CYAN}[AUTO-RELEASE] {target_name} | Band {prop.band} -> {prop.gain_db:+.1f}dB{C_RESET}")
                self.log_event("auto_release", {
                    "channel": prop.channel,
                    "band": prop.band,
                    "gain_db": prop.gain_db,
                    "reason": prop.reason,
                })
            else:
                print(
                    f"\n{C_GREEN}[ĐÃ HẠ NOTCH] {target_name} | Band {prop.band} | "
                    f"{prop.freq_hz:.1f}Hz | {prop.gain_db:+.1f}dB | Q={prop.q:.1f}{C_RESET}"
                )
            self.log_event("notch_applied", {
                "target": prop.target,
                "channel": prop.channel,
                "band": prop.band,
                "freq_hz": prop.freq_hz,
                "gain_db": prop.gain_db,
                "q": prop.q,
            })
            return True
        else:
            print(f"\n{C_RED}[THẤT BẠI] Gửi lệnh PEQ tới mixer không nhận được xác nhận!{C_RESET}")
            return False

    def execute_proposal(self, prop: ActionProposal, async_send: bool = True) -> bool:
        """Gửi lệnh notch PEQ sang mixer (mặc định gửi phi đồng bộ qua queue)."""
        if async_send:
            self._cmd_queue.put(prop)
            return True
        return self._send_proposal_to_mixer(prop)

    def run_loop(self, max_seconds: Optional[float] = None) -> None:
        """Vòng lặp chính xử lý âm thanh và tương tác người dùng."""
        start_time = time.time()
        read_buffer = np.zeros((512, 18), dtype=np.float32)
        channel_rolling_frames = {ch: np.zeros(2048, dtype=np.float32) for ch in self.config.channels.mic_channels}

        last_display_time = 0.0

        while self._running:
            now = time.time()
            if max_seconds and (now - start_time >= max_seconds):
                break

            # 1. Đọc dữ liệu từ Ring Buffer nếu có ít nhất 512 mẫu
            if self.audio_capture and self.audio_capture.ring_buffer.available_read() >= 512:
                n = self.audio_capture.ring_buffer.read(read_buffer)
                if n == 512 and self.detector:
                    # Cập nhật khung trượt 2048 mẫu cho từng kênh mic
                    for ch in self.config.channels.mic_channels:
                        ch_idx = ch - 1
                        rolling = channel_rolling_frames[ch]
                        rolling[: 2048 - 512] = rolling[512:]
                        rolling[2048 - 512 :] = read_buffer[:, ch_idx]

                        # Phân tích FFT tìm hú
                        proposals = self.detector.process_channel_frame(ch, rolling)
                        for prop in proposals:
                            # Chuyển qua Safety Controller kiểm duyệt
                            self.safety_state, decision = decide(self.safety_state, prop, now=now)
                            if decision.approved and decision.proposal:
                                approved_p = decision.proposal
                                if self.mode == "auto":
                                    self.execute_proposal(approved_p)
                                else:
                                    # Chế độ gợi ý / bán tự động: lưu vào danh sách chờ
                                    self.pending_proposals.append(approved_p)
                                    print(
                                        f"\n{C_RED}[CẢNH BÁO ĐỎ] Kênh {approved_p.channel} chớm hú tại "
                                        f"{approved_p.freq_hz:.1f}Hz! Bấm [SPACE] để duyệt hạ notch.{C_RESET}"
                                    )

            # 2. Kiểm tra Auto-Release nhả notch định kỳ (Phương án 3)
            if self.safety_state.auto_release_enabled and (now - last_display_time >= 1.0):
                self.safety_state, release_props = check_auto_release(
                    self.safety_state, now=now, step_db=self.config.safety.auto_release_rate_db_per_s
                )
                for r_prop in release_props:
                    self.execute_proposal(r_prop)

            # 3. Hiển thị trạng thái định kỳ mỗi 1.5 giây
            if now - last_display_time >= 1.5:
                dev_name = self.config.device.name
                target_mode = "RTA MAIN" if not self.config.device.has_multichannel_usb else "USB"
                state_str = (
                    f"{C_GREEN}[XANH] Đã kết nối {dev_name} ({self.config.network.default_mixer_ip}){C_RESET}"
                    if self.mixer_client and self.mixer_client.get_state() == ConnectionState.CONNECTED
                    else f"{C_RED}[ĐỎ] Mất kết nối {dev_name}{C_RESET}"
                )
                active_count = len(self.safety_state.active_notches)
                queue_count = self._cmd_queue.qsize()
                sys.stdout.write(
                    f"\rTrạng thái: {state_str} | Chế độ: {self.mode.upper()} ({target_mode}) | "
                    f"Notch: {active_count} | Hàng đợi: {queue_count} | Phím: [SPACE]=Duyệt, [P]=PANIC, [Q]=Thoát  "
                )
                sys.stdout.flush()
                last_display_time = now

            # 3. Lắng nghe phím bấm từ bàn phím (không block)
            if sys.stdin in select.select([sys.stdin], [], [], 0.02)[0]:
                key = sys.stdin.read(1)
                if key == " ":
                    if self.pending_proposals:
                        p_to_apply = self.pending_proposals.pop(0)
                        self.execute_proposal(p_to_apply)
                    else:
                        print(f"\n{C_CYAN}[THÔNG BÁO] Không có cảnh báo hú nào đang chờ duyệt.{C_RESET}")
                elif key in ("p", "P"):
                    print(f"\n{C_YELLOW}[PANIC] Đang hoàn tác toàn bộ notch về 0 dB...{C_RESET}")
                    self.safety_state, rollback_list = panic_rollback(self.safety_state, now=now)
                    for r_prop in rollback_list:
                        self.execute_proposal(r_prop)
                elif key in ("q", "Q"):
                    break

            time.sleep(0.01)


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto Sound Engineer - Tự động phát hiện hú và hạ notch PEQ cho XR18")
    parser.add_argument("--mock", action="store_true", help="Chạy ở chế độ mô phỏng (không cần mixer và soundcard thật)")
    parser.add_argument("--mode", choices=["auto", "semi", "manual"], default="auto", help="Chế độ vận hành (mặc định: auto)")
    parser.add_argument("--profile", default="device_profiles/xr18.toml", help="Đường dẫn file cấu hình profile thiết bị")
    parser.add_argument("--web", action="store_true", help="Khởi động Companion Web UI (Nuxt 4 / Vue 3) qua FastAPI")
    parser.add_argument("--host", default="127.0.0.1", help="Địa chỉ host bind Web server (mặc định 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Cổng chạy Web server (mặc định 8000)")
    parser.add_argument("--listen-lan", action="store_true", help="Cho phép các thiết bị iPad/điện thoại trong mạng LAN truy cập (kèm mã PIN ghép nối)")
    args = parser.parse_args()

    cfg_path = Path(args.profile)
    if not cfg_path.exists():
        cfg_path = Path(__file__).resolve().parent.parent.parent.parent / "device_profiles" / "xr18.toml"

    config = AppConfig.load(cfg_path)
    mapper = ParameterMapper.from_profile(cfg_path)

    app = AutoSoundApp(config=config, mapper=mapper, mock_mode=args.mock, mode=args.mode)

    if args.web:
        import uvicorn
        from auto_sound.app.server import create_app
        host = "0.0.0.0" if args.listen_lan else args.host
        web_app = create_app(engine=app, listen_lan=args.listen_lan, mock_mode=args.mock)
        print(f"\n⚡ Khởi chạy Nuxt 4 Companion UI tại: http://{args.host}:{args.port}")
        uvicorn.run(web_app, host=host, port=args.port, log_level="warning")
        return

    try:
        app.start()
        app.run_loop()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()


if __name__ == "__main__":
    main()
