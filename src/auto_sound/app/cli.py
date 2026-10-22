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
from auto_sound.i18n import set_language, t
from auto_sound.mixer.fake import FakeXR18
from auto_sound.mixer.parameter_mapper import ParameterMapper
from auto_sound.mixer.xair import XAirClient, discover_mixers
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
        self._dsp_thread: Optional[threading.Thread] = None

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
        print(f"{C_BOLD}{t('cli.start_banner', model=self.config.device.name)}{C_RESET}")

        target_ip = self.config.network.default_mixer_ip
        target_port = self.config.device.port

        if self.mock_mode:
            print(f"{C_YELLOW}{t('cli.mock_starting')}{C_RESET}")
            self.fake_mixer = FakeXR18(host="127.0.0.1", port=0)
            self.fake_mixer.start()
            target_ip = self.fake_mixer.host
            target_port = self.fake_mixer.port
        else:
            if target_ip == "auto":
                print(f"{C_CYAN}{t('cli.discovering')}{C_RESET}")
                found = discover_mixers(timeout_s=0.8, port=target_port)
                if found:
                    target_ip = found[0]["ip"]
                    print(
                        f"{C_GREEN}{t('cli.discovered', name=found[0]['name'], model=found[0]['model'], ip=target_ip, firmware=found[0]['firmware'])}{C_RESET}"
                    )
                else:
                    target_ip = "192.168.1.100"
                    print(f"{C_YELLOW}{t('cli.discover_default', ip=target_ip)}{C_RESET}")

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

        # Kiểm tra tự động thích ứng với model thực tế của mixer
        actual_model = (self.mixer_client.mixer_model or "").upper()
        if actual_model in ("XR12", "XR16", "MR12") and self.config.device.has_multichannel_usb:
            print(f"{C_YELLOW}{t('cli.adapting_lan_rta', model=actual_model)}{C_RESET}")
            self.config.device.has_multichannel_usb = False
            self.safety_state.whitelist.add(0)
            self.safety_state.allowed_bands[0] = tuple(self.config.eq.main_auto_notch_bands)

        # Khởi tạo detector & audio capture tùy theo loại thiết bị
        if not self.config.device.has_multichannel_usb:
            print(f"{C_CYAN}{t('cli.lan_rta_mode', model=self.config.device.name)}{C_RESET}")
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

        # Khởi động worker DSP chạy nền để xử lý âm thanh độc lập với giao diện
        self._dsp_thread = threading.Thread(
            target=self._dsp_worker_loop, daemon=True, name="AudioDspWorker"
        )
        self._dsp_thread.start()

        self.log_event("system_start", {"mock_mode": self.mock_mode, "mode": self.mode, "mixer": f"{target_ip}:{target_port}"})

    def drain_cmd_queue(self) -> None:
        """Làm rỗng hàng đợi lệnh, ưu tiên tuyệt đối cho PANIC."""
        while not self._cmd_queue.empty():
            try:
                self._cmd_queue.get_nowait()
                self._cmd_queue.task_done()
            except (queue.Empty, ValueError):
                break

    def stop(self) -> None:
        """Dừng sạch sẽ toàn bộ hệ thống."""
        self._running = False
        if self._dsp_thread and self._dsp_thread.is_alive():
            self._dsp_thread.join(timeout=1.0)
        if self._network_thread and self._network_thread.is_alive():
            self._network_thread.join(timeout=1.0)
        if self.audio_capture:
            self.audio_capture.stop()
        if self.mixer_client:
            self.mixer_client.disconnect()
        if self.fake_mixer:
            self.fake_mixer.stop()
        print(f"\n{C_YELLOW}{t('cli.stopped')}{C_RESET}")

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
                        f"\n{C_RED}{t('cli.feedback_alert', target='Main L/R', freq=approved_p.freq_hz)}{C_RESET}"
                    )

    def _on_mixer_param_change(self, address: str, val: Any) -> None:
        """Tự động khóa 10s khi phát hiện Soundman can thiệp thủ công từ iPad hoặc mặt bàn mixer."""
        # Chỉ khóa khi Soundman can thiệp vào các dải EQ cụ thể (ví dụ: /ch/02/eq/1/g, /ch/02/eq/3/f...)
        if address.startswith("/ch/") and "/eq/" in address:
            try:
                parts = address.strip("/").split("/")
                # Địa chỉ band EQ có dạng ch/02/eq/1/g (5 phần, parts[3] là số band 1-4)
                if len(parts) >= 5 and parts[0] == "ch" and parts[2] == "eq" and parts[3].isdigit():
                    ch = int(parts[1])
                    if ch in self.safety_state.whitelist:
                        now = time.time()
                        self.safety_state = handle_manual_override(self.safety_state, channel=ch, now=now)
                        ch_name = self.mixer_client.get_channel_name(ch) if self.mixer_client else f"CH {ch:02d}"
                        print(
                            f"\n{C_YELLOW}{t('cli.manual_lock', target=ch_name, band=parts[3])}{C_RESET}"
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
            print(f"\n{C_RED}{t('cli.network_error')}{C_RESET}")
            return False

        if prop.target == "main" or prop.channel == 0:
            target_name = "Main LR"
        elif prop.target == "bus":
            target_name = f"Bus {prop.bus}"
        else:
            ch_name = self.mixer_client.get_channel_name(prop.channel) if self.mixer_client else f"CH {prop.channel:02d}"
            target_name = f"{ch_name} (Ch {prop.channel:02d})"
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
                    f"\n{C_GREEN}{t('cli.notch_applied', target=target_name, band=prop.band, freq=prop.freq_hz, gain=prop.gain_db, q=prop.q)}{C_RESET}"
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
            print(f"\n{C_RED}{t('cli.notch_failed')}{C_RESET}")
            return False

    def execute_proposal(self, prop: ActionProposal, async_send: bool = True) -> bool:
        """Gửi lệnh notch PEQ sang mixer (mặc định gửi phi đồng bộ qua queue)."""
        if async_send:
            self._cmd_queue.put(prop)
            return True
        return self._send_proposal_to_mixer(prop)

    def _dsp_worker_loop(self) -> None:
        """Worker chạy nền xử lý phân tích FFT và tự động nhả notch, hoạt động liên tục cả ở chế độ CLI lẫn Web."""
        read_buffer = np.zeros((512, 18), dtype=np.float32)
        channel_rolling_frames = {ch: np.zeros(2048, dtype=np.float32) for ch in self.config.channels.mic_channels}
        last_auto_release_check = time.time()

        while self._running:
            now = time.time()

            # 1. Đọc dữ liệu từ Ring Buffer nếu có ít nhất 512 mẫu
            if self.audio_capture and self.audio_capture.ring_buffer.available_read() >= 512:
                n = self.audio_capture.ring_buffer.read(read_buffer)
                if n == 512 and self.detector:
                    for ch in self.config.channels.mic_channels:
                        # Bỏ qua kênh nếu đang bị Mute trên X Air để tránh phân tích và báo động giả
                        if self.mixer_client and self.mixer_client.is_channel_muted(ch):
                            continue

                        ch_idx = ch - 1
                        rolling = channel_rolling_frames[ch]
                        rolling[: 2048 - 512] = rolling[512:]
                        rolling[2048 - 512 :] = read_buffer[:, ch_idx]

                        proposals = self.detector.process_channel_frame(ch, rolling)
                        for prop in proposals:
                            self.safety_state, decision = decide(self.safety_state, prop, now=now)
                            if decision.approved and decision.proposal:
                                approved_p = decision.proposal
                                if self.mode == "auto":
                                    self.execute_proposal(approved_p)
                                else:
                                    self.pending_proposals.append(approved_p)
                                    ch_name = self.mixer_client.get_channel_name(approved_p.channel) if self.mixer_client else f"CH {approved_p.channel:02d}"
                                    print(
                                        f"\n{C_RED}{t('cli.feedback_alert', target=ch_name, freq=approved_p.freq_hz)}{C_RESET}"
                                    )
            else:
                time.sleep(0.002)

            # 2. Kiểm tra Auto-Release nhả notch định kỳ mỗi 1.0 giây
            if self.safety_state.auto_release_enabled and (now - last_auto_release_check >= 1.0):
                self.safety_state, release_props = check_auto_release(
                    self.safety_state, now=now, step_db=self.config.safety.auto_release_rate_db_per_s
                )
                for r_prop in release_props:
                    self.execute_proposal(r_prop)
                last_auto_release_check = now

    def run_loop(self, max_seconds: Optional[float] = None) -> None:
        """Vòng lặp tương tác người dùng trên giao diện terminal dòng lệnh."""
        start_time = time.time()
        last_display_time = 0.0

        while self._running:
            now = time.time()
            if max_seconds and (now - start_time >= max_seconds):
                break

            # 1. Hiển thị trạng thái định kỳ mỗi 1.5 giây
            if now - last_display_time >= 1.5:
                dev_info = self.mixer_client.get_device_info() if self.mixer_client else {}
                dev_name = dev_info.get("name") or self.config.device.name
                model_name = dev_info.get("model") or self.config.device.name
                fw_str = f" v{dev_info['firmware']}" if dev_info.get("firmware") and dev_info.get("firmware") != "Unknown" else ""
                target_mode = "RTA MAIN" if not self.config.device.has_multichannel_usb else "USB"
                state_str = (
                    f"{C_GREEN}[XANH] {model_name} '{dev_name}'{fw_str} ({dev_info.get('ip', self.config.network.default_mixer_ip)}){C_RESET}"
                    if self.mixer_client and self.mixer_client.get_state() == ConnectionState.CONNECTED
                    else f"{C_RED}[ĐỎ] Mất kết nối {model_name}{C_RESET}"
                )
                active_count = len(self.safety_state.active_notches)
                queue_count = self._cmd_queue.qsize()
                status_str = t(
                    'cli.status_line',
                    state=state_str,
                    mode=self.mode.upper(),
                    target_mode=target_mode,
                    active_count=active_count,
                    queue_count=queue_count,
                )
                sys.stdout.write(f"\r{status_str}")
                sys.stdout.flush()
                last_display_time = now

            # 2. Lắng nghe phím bấm từ bàn phím (không block)
            if sys.stdin in select.select([sys.stdin], [], [], 0.02)[0]:
                key = sys.stdin.read(1)
                if key == " ":
                    if self.pending_proposals:
                        p_to_apply = self.pending_proposals.pop(0)
                        self.execute_proposal(p_to_apply)
                    else:
                        print(f"\n{C_CYAN}{t('cli.no_feedback')}{C_RESET}")
                elif key in ("p", "P"):
                    print(f"\n{C_YELLOW}{t('cli.panic')}{C_RESET}")
                    self.drain_cmd_queue()
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
    parser.add_argument("--ip", default=None, help="Địa chỉ IP của mixer X-Air (hoặc 'auto' để tự động quét tìm)")
    parser.add_argument("--discover", action="store_true", help="Quét tìm kiếm các mixer Behringer/Midas X-Air trong mạng LAN")
    parser.add_argument("--web", action="store_true", help="Khởi động Companion Web UI (Nuxt 4 / Vue 3) qua FastAPI")
    parser.add_argument("--host", default="127.0.0.1", help="Địa chỉ host bind Web server (mặc định 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Cổng chạy Web server (mặc định 8000)")
    parser.add_argument("--listen-lan", action="store_true", help="Cho phép các thiết bị iPad/điện thoại trong mạng LAN truy cập (kèm mã PIN ghép nối)")
    parser.add_argument("--lang", choices=["vi", "en"], default="vi", help="Ngôn ngữ hiển thị terminal (vi / en, mặc định: vi)")
    args = parser.parse_args()

    set_language(args.lang)

    if args.discover:
        print(f"\n{C_CYAN}🔍 Đang quét mạng LAN tìm kiếm mixer Behringer/Midas X-Air...{C_RESET}")
        mixers = discover_mixers(timeout_s=1.0)
        if mixers:
            print(f"{C_GREEN}✅ Đã tìm thấy {len(mixers)} mixer X-Air:{C_RESET}")
            for idx, m in enumerate(mixers, start=1):
                print(f"  {idx}. Model: {m['model']:<8} | Tên: {m['name']:<18} | IP: {m['ip']:<15} | Firmware: {m['firmware']}")
        else:
            print(f"{C_YELLOW}⚠️ Không tìm thấy mixer nào phản hồi trên cổng 10024.{C_RESET}")
        return

    cfg_path = Path(args.profile)
    if not cfg_path.exists():
        cfg_path = Path(__file__).resolve().parent.parent.parent.parent / "device_profiles" / "xr18.toml"

    config = AppConfig.load(cfg_path)
    if args.ip:
        config.network.default_mixer_ip = args.ip
    mapper = ParameterMapper.from_profile(cfg_path)

    app = AutoSoundApp(config=config, mapper=mapper, mock_mode=args.mock, mode=args.mode)

    if args.web:
        import uvicorn
        import webbrowser
        from auto_sound.app.server import create_app
        host = "0.0.0.0" if args.listen_lan else args.host
        web_app = create_app(engine=app, listen_lan=args.listen_lan, mock_mode=args.mock)
        url = f"http://{args.host}:{args.port}"
        print(f"\n============================================================")
        print(t('cli.web_running', url=url))
        print(f"============================================================\n")
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
        uvicorn.run(web_app, host=host, port=args.port, log_level="warning")
        return

    try:
        print(t('cli.web_tip'))
        app.start()
        app.run_loop()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()


if __name__ == "__main__":
    main()
