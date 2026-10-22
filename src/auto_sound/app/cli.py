"""Giao diện dòng lệnh (CLI) tiếng Việt đơn giản, hiệu quả cho kỹ sư âm thanh."""

from __future__ import annotations
import argparse
import json
import logging
import math
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
from auto_sound.dsp.talkover import TalkoverController
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
        use_real_mic: bool = False,
        input_device: Optional[str | int] = None,
        audible: bool = False,
    ) -> None:
        self.config = config
        self.mapper = mapper
        self.mock_mode = mock_mode
        self.mode = mode  # "auto", "semi", "manual"
        self.use_real_mic = use_real_mic
        self.input_device = input_device
        self.audible = audible
        self.dry_run: bool = False
        self.on_log_event: Optional[Callable[[str, dict], None]] = None
        self._active_fake_feedbacks: List[Dict[str, Any]] = []
        self._proposals_lock: threading.Lock = threading.Lock()
        self._safety_lock: threading.Lock = threading.Lock()

        self.fake_mixer: Optional[FakeXR18] = None
        self.mixer_client: Optional[XAirClient] = None
        self.audio_capture: Optional[AudioCapture] = None
        self.detector: Optional[FeedbackDetector] = None
        self.rta_detector: Optional[RTADetector] = None
        self._audio_output: Optional[sd.OutputStream] = None

        self._cmd_queue: queue.Queue[ActionProposal] = queue.Queue()
        self._network_thread: Optional[threading.Thread] = None
        self._dsp_thread: Optional[threading.Thread] = None

        whitelist = set(self.config.channels.mic_channels)
        allowed_bands = {ch: tuple(self.config.eq.auto_notch_bands) for ch in self.config.channels.mic_channels}
        # Kênh 0 (Main Stereo LR) luôn được cấu hình an toàn cho phép can thiệp
        whitelist.add(0)
        allowed_bands[0] = tuple(self.config.eq.main_auto_notch_bands)
        bus_whitelist = set(range(1, 7))
        bus_allowed_bands = {b: tuple(self.config.eq.bus_auto_notch_bands) for b in range(1, 7)}

        self.safety_state = SafetyState(
            whitelist=whitelist,
            allowed_bands=allowed_bands,
            bus_whitelist=bus_whitelist,
            bus_allowed_bands=bus_allowed_bands,
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
        self.talkover_controller = TalkoverController()
        self._running = False

    def log_event(self, event_type: str, details: dict) -> None:
        """Log structured JSON event shared across audio and control planes."""
        entry = {
            "timestamp": time.time(),
            "event": event_type,
            "data": details,
        }
        sys.stderr.write(json.dumps(entry, ensure_ascii=False) + "\n")
        sys.stderr.flush()
        if self.on_log_event:
            try:
                self.on_log_event(event_type, details)
            except Exception:
                pass

    def trigger_fake_feedback(self, channel: int = 2, freq_hz: float = 2500.0, duration_s: float = 5.0) -> None:
        """Trigger synthetic feedback burst for simulation / testing."""
        expire = time.time() + duration_s
        self._active_fake_feedbacks.append({
            "channel": channel,
            "freq_hz": freq_hz,
            "expire_time": expire,
        })
        if self.fake_mixer and hasattr(self.fake_mixer, "set_fake_feedback_bin"):
            ratio = max(20.0, min(20000.0, freq_hz)) / 20.0
            bin_idx = int(np.clip(np.round((np.log(ratio) / np.log(1000.0)) * 99.0), 0, 99))
            self.fake_mixer.set_fake_feedback_bin(bin_idx)
            threading.Timer(
                duration_s,
                lambda: self.fake_mixer.set_fake_feedback_bin(None) if self.fake_mixer else None,
            ).start()
        self.log_event("fake_feedback_triggered", {"channel": channel, "freq_hz": freq_hz, "duration_s": duration_s})

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

        # Tự kiểm tra số band kênh PEQ thực tế trên phần cứng
        if hasattr(self.mixer_client, "probe_channel_bands") and not self.mock_mode:
            detected_bands = self.mixer_client.probe_channel_bands(channel=1, max_bands=6)
            if detected_bands != self.config.eq.channel_bands_count:
                print(
                    f"{C_CYAN}[TỰ ĐỘNG THÍCH ỨNG] Kênh micro có {detected_bands} band PEQ "
                    f"(cấu hình profile: {self.config.eq.channel_bands_count} bands). Tự động cập nhật!{C_RESET}"
                )
                self.config.eq.channel_bands_count = detected_bands

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
            if self.mock_mode and not self.use_real_mic:
                sim = RoomSimulator(sample_rate=48000, seed=42)
                # Bộ sinh tín hiệu 16 kênh ảo sinh động (vocal, guitar, bass, keys, ambient)
                def mock_audio_generator(frames: int, counter: int) -> np.ndarray:
                    block = np.zeros((frames, 18), dtype=np.float32)
                    t = (counter + np.arange(frames)) / 48000.0
                    now = time.time()

                    # Kênh 1: Ca sĩ hát (vocal nốt 440 Hz + vibrato)
                    block[:, 0] = 0.20 * np.sin(2 * np.pi * (440.0 + 5.0 * np.sin(2 * np.pi * 5.0 * t)) * t)
                    # Kênh 2: Guitar điện (330 Hz + 660 Hz)
                    block[:, 1] = 0.15 * np.sin(2 * np.pi * 330.0 * t) + 0.08 * np.sin(2 * np.pi * 660.0 * t)
                    # Kênh 3: Bass guitar (110 Hz)
                    block[:, 2] = 0.22 * np.sin(2 * np.pi * 110.0 * t)
                    # Kênh 4: Keyboard / Synth (523 Hz)
                    block[:, 3] = 0.12 * np.sin(2 * np.pi * 523.25 * t)
                    # Các kênh 5-16: Tín hiệu nhạc cụ và tiếng ồn phòng nhẹ (~-45 dB)
                    for ch_i in range(4, 16):
                        f_base = 150.0 + (ch_i * 85.0)
                        block[:, ch_i] = 0.06 * np.sin(2 * np.pi * f_base * t)

                    # Kiểm tra mức đè Notch PEQ trên bàn mixer ảo
                    def get_channel_attenuation(channel_num: int) -> float:
                        if not self.fake_mixer:
                            return 1.0
                        min_gain = 0.0
                        for band in (1, 2, 3, 4, 5, 6):
                            addr = f"/ch/{channel_num:02d}/eq/{band}/g"
                            if addr in self.fake_mixer.params:
                                val = self.fake_mixer.params[addr]
                                g_db = (val - 0.5) * 30.0  # Mapper: 0.5 = 0dB, 0.0 = -15dB
                                if g_db < min_gain:
                                    min_gain = g_db
                        return float(10.0 ** (min_gain / 20.0))

                    # Kích hoạt tiếng hú định kỳ hoặc từ lệnh UI "Tạo hú giả"
                    # Mặc định tự động hú thử nghiệm ở giây thứ 3 nếu chưa có lệnh can thiệp
                    auto_howl = (counter > 48000 * 2 and counter < 48000 * 7 and not self._active_fake_feedbacks)
                    if auto_howl:
                        att_ch2 = get_channel_attenuation(2)
                        block[:, 1] += (0.45 * att_ch2) * np.sin(2 * np.pi * 2500.0 * t)

                    # Áp dụng các tiếng hú được kích hoạt từ nút bấm UI
                    remaining_feedbacks = []
                    for fb in self._active_fake_feedbacks:
                        if now < fb["expire_time"]:
                            ch_idx = max(0, min(15, fb["channel"] - 1))
                            att = get_channel_attenuation(fb["channel"])
                            block[:, ch_idx] += (0.50 * att) * np.sin(2 * np.pi * fb["freq_hz"] * t)
                            remaining_feedbacks.append(fb)
                    self._active_fake_feedbacks = remaining_feedbacks

                    # Nếu bật --audible, phát trực tiếp âm thanh ra loa ngoài máy tính
                    if self._audio_output:
                        stereo = np.empty((frames, 2), dtype=np.float32)
                        stereo[:, 0] = block[:, 0] + block[:, 1] * 0.7
                        stereo[:, 1] = block[:, 0] * 0.5 + block[:, 1] * 0.7
                        np.clip(stereo, -0.85, 0.85, out=stereo)
                        try:
                            self._audio_output.write(stereo)
                        except Exception:
                            pass

                    return block

                self.audio_capture = AudioCapture(
                    channels=18,
                    sample_rate=48000,
                    is_virtual=True,
                    virtual_generator=mock_audio_generator,
                )
            else:
                input_dev = self.input_device
                dev_desc = f"'{input_dev}'" if input_dev else "Micro mặc định của hệ thống"
                print(f"{C_GREEN}[MICRO THẬT]{C_RESET} Đang mở {dev_desc} đưa vào Kênh 1 của mixer...")
                self.audio_capture = AudioCapture(
                    channels=18,
                    sample_rate=48000,
                    is_virtual=False,
                    device=input_dev,
                )

            self.audio_capture.start()

        if self.mock_mode and self.audible:
            try:
                self._audio_output = sd.OutputStream(samplerate=48000, channels=2, dtype="float32")
                self._audio_output.start()
                print(f"{C_GREEN}[LOA NGOÀI] Đã bật phát âm thanh mô phỏng trực tiếp ra loa máy tính.{C_RESET}")
            except Exception as e:
                print(f"{C_YELLOW}[LOA NGOÀI] Không thể mở cổng phát âm thanh: {e}{C_RESET}")
                self._audio_output = None

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
        if self._audio_output:
            try:
                self._audio_output.stop()
                self._audio_output.close()
            except Exception:
                pass
            self._audio_output = None
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
            self.safety_state, decision = decide(
                self.safety_state, prop, now=now, get_current_gain=self._get_mixer_peq_gain
            )
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
        """Lock channel, bus, or Main LR for 10s upon detecting external manual override by sound engineer."""
        try:
            parts = address.strip("/").split("/")
            now = time.time()
            lock_dur = None
            target_desc = ""
            band_desc = ""

            # 1. Channel EQ manual override
            if address.startswith("/ch/") and "/eq/" in address and len(parts) >= 5 and parts[3].isdigit():
                ch = int(parts[1])
                with self._safety_lock:
                    if ch in self.safety_state.whitelist:
                        self.safety_state = handle_manual_override(self.safety_state, channel=ch, now=now, target="ch")
                        lock_dur = self.safety_state.lock_duration_s
                        ch_name = self.mixer_client.get_channel_name(ch) if self.mixer_client else f"CH {ch:02d}"
                        target_desc = ch_name
                        band_desc = parts[3]

            # 2. Bus (Aux Monitor) EQ manual override
            elif address.startswith("/bus/") and "/eq/" in address and len(parts) >= 5 and parts[3].isdigit():
                bus = int(parts[1])
                with self._safety_lock:
                    if bus in self.safety_state.bus_whitelist:
                        self.safety_state = handle_manual_override(self.safety_state, channel=0, now=now, target="bus", bus=bus)
                        lock_dur = self.safety_state.lock_duration_s
                        target_desc = f"Bus {bus}"
                        band_desc = parts[3]

            # 3. Main L/R EQ manual override
            elif address.startswith("/lr/eq/") and len(parts) >= 3 and parts[2].isdigit():
                with self._safety_lock:
                    self.safety_state = handle_manual_override(self.safety_state, channel=0, now=now, target="ch")
                    lock_dur = self.safety_state.lock_duration_s
                    target_desc = "Main LR"
                    band_desc = parts[2]

            elif address.startswith("/main/st/eq/") and len(parts) >= 4 and parts[3].isdigit():
                with self._safety_lock:
                    self.safety_state = handle_manual_override(self.safety_state, channel=0, now=now, target="ch")
                    lock_dur = self.safety_state.lock_duration_s
                    target_desc = "Main LR"
                    band_desc = parts[3]

            if lock_dur is not None:
                print(f"\n{C_YELLOW}{t('cli.manual_lock', target=target_desc, band=band_desc)}{C_RESET}")
                self.log_event("manual_override_lock", {"target": f"{target_desc} Band {band_desc}", "address": address, "lock_until": now + lock_dur})
        except Exception:
            pass

    def _get_mixer_peq_gain(self, channel: int, band: int, target: str) -> float:
        """Query current PEQ gain from mixer cache (O(1) non-blocking) before overriding it."""
        if not self.mixer_client or self.mixer_client.get_state() != ConnectionState.CONNECTED:
            return 0.0
        try:
            if hasattr(self.mixer_client, "get_peq_gain_cached"):
                cached_g = self.mixer_client.get_peq_gain_cached(channel, band, target=target)
                if cached_g is not None:
                    return cached_g
            if hasattr(self.mixer_client, "_params_cache"):
                if target in ("main", "lr") or channel == 0:
                    lr_p = getattr(getattr(self.mixer_client, "capability_map", None), "lr_prefix", "/lr")
                    addr = f"{lr_p}/eq/{band}/g"
                elif target == "bus":
                    addr = f"/bus/{channel}/eq/{band}/g"
                else:
                    addr = f"/ch/{channel:02d}/eq/{band}/g"
                with getattr(self.mixer_client, "_lock", threading.Lock()):
                    g_norm = self.mixer_client._params_cache.get(addr)
                if g_norm is not None:
                    return self.mapper.gain.from_float(float(g_norm))
        except Exception:
            pass
        return 0.0

    def _send_proposal_to_mixer(self, prop: ActionProposal) -> bool:
        """Send approved PEQ notch command to mixer and verify."""
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

        if self.dry_run:
            print(
                f"\n{C_CYAN}[DRY-RUN / SHADOW] {target_name} | Band {prop.band} | "
                f"{prop.freq_hz:.1f}Hz | {prop.gain_db:+.1f}dB | Q={prop.q:.1f} (Không gửi mixer){C_RESET}"
            )
            self.log_event("shadow_notch_simulated", {
                "target": prop.target,
                "channel": prop.channel,
                "band": prop.band,
                "freq_hz": prop.freq_hz,
                "gain_db": prop.gain_db,
                "q": prop.q,
                "dry_run": True,
            })
            return True

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
        """Send PEQ notch proposal to mixer queue or execute synchronously."""
        if async_send:
            self._cmd_queue.put(prop)
            return True
        return self._send_proposal_to_mixer(prop)

    def _dsp_worker_loop(self) -> None:
        """Background DSP worker analyzing audio frames and managing auto-release."""
        read_buffer = np.zeros((512, 18), dtype=np.float32)
        channel_rolling_frames = {ch: np.zeros(2048, dtype=np.float32) for ch in self.config.channels.mic_channels}
        last_auto_release_check = time.time()

        while self._running:
            now = time.time()

            # 1. Read audio data from Ring Buffer
            if self.audio_capture and self.audio_capture.ring_buffer.available_read() >= 512:
                n = self.audio_capture.ring_buffer.read(read_buffer)
                if n == 512 and self.detector:
                    for ch in self.config.channels.mic_channels:
                        if self.mixer_client and self.mixer_client.is_channel_muted(ch):
                            continue

                        ch_idx = ch - 1
                        rolling = channel_rolling_frames[ch]
                        rolling[: 2048 - 512] = rolling[512:]
                        rolling[2048 - 512 :] = read_buffer[:, ch_idx]

                        proposals = self.detector.process_channel_frame(ch, rolling)
                        for prop in proposals:
                            with self._safety_lock:
                                self.safety_state, decision = decide(
                                    self.safety_state, prop, now=now, get_current_gain=self._get_mixer_peq_gain
                                )
                            if decision.approved and decision.proposal:
                                approved_p = decision.proposal
                                if self.mode == "auto":
                                    self.execute_proposal(approved_p)
                                else:
                                    with self._proposals_lock:
                                        self.pending_proposals.append(approved_p)
                                    ch_name = self.mixer_client.get_channel_name(approved_p.channel) if self.mixer_client else f"CH {approved_p.channel:02d}"
                                    print(
                                        f"\n{C_RED}{t('cli.feedback_alert', target=ch_name, freq=approved_p.freq_hz)}{C_RESET}"
                                    )

                        # 1b. Smart FX Auto-Talkover Ducking (MC nói chuyện + Nhạc dừng)
                        if self.talkover_controller and self.talkover_controller.config.enabled:
                            cfg = self.talkover_controller.config
                            mic_ch = cfg.mic_channel
                            mic_rms = float(np.sqrt(np.mean(read_buffer[:, mic_ch - 1] ** 2) + 1e-12)) if 1 <= mic_ch <= read_buffer.shape[1] else 1e-6
                            mic_dbfs = 20.0 * math.log10(max(1e-6, mic_rms))

                            music_rms_max = 1e-6
                            for m_ch in cfg.music_channels:
                                if 1 <= m_ch <= read_buffer.shape[1]:
                                    m_rms = float(np.sqrt(np.mean(read_buffer[:, m_ch - 1] ** 2) + 1e-12))
                                    if m_rms > music_rms_max:
                                        music_rms_max = m_rms
                            music_dbfs = 20.0 * math.log10(max(1e-6, music_rms_max))

                            fader_val, _, msg = self.talkover_controller.process_frame(mic_dbfs, music_dbfs, now)
                            if fader_val is not None and self.mixer_client and self.mixer_client.get_state() == ConnectionState.CONNECTED:
                                fx_rtn = getattr(cfg, "fx_return_channel", 1)
                                if hasattr(self.mixer_client, "set_fader"):
                                    self.mixer_client.set_fader(target="rtn", index=fx_rtn, val=fader_val)
                                elif hasattr(self.mixer_client, "_send_raw"):
                                    self.mixer_client._send_raw(encode_message(f"/rtn/{fx_rtn}/mix/fader", fader_val))
                            if msg:
                                self.log_event("talkover_event", {"message": msg, "ducked": self.talkover_controller.is_ducked, "fader_val": fader_val})
            else:
                time.sleep(0.002)

            # 2. Check auto-release periodically every 1.0 second
            release_props = []
            with self._safety_lock:
                if self.safety_state.auto_release_enabled and (now - last_auto_release_check >= 1.0):
                    self.safety_state, release_props = check_auto_release(
                        self.safety_state, now=now, step_db=self.config.safety.auto_release_rate_db_per_s
                    )
                    last_auto_release_check = now
            for r_prop in release_props:
                self.execute_proposal(r_prop)

    def run_loop(self, max_seconds: Optional[float] = None) -> None:
        """CLI terminal user interaction loop."""
        start_time = time.time()
        last_display_time = 0.0

        while self._running:
            now = time.time()
            if max_seconds and (now - start_time >= max_seconds):
                break

            # 1. Periodic status display every 1.5 seconds
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
                with self._safety_lock:
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

            # 2. Non-blocking keyboard input listener
            if sys.stdin in select.select([sys.stdin], [], [], 0.02)[0]:
                key = sys.stdin.read(1)
                if key == " ":
                    with self._proposals_lock:
                        p_to_apply = self.pending_proposals.pop(0) if self.pending_proposals else None
                    if p_to_apply:
                        self.execute_proposal(p_to_apply)
                    else:
                        print(f"\n{C_CYAN}{t('cli.no_feedback')}{C_RESET}")
                elif key in ("p", "P"):
                    print(f"\n{C_YELLOW}{t('cli.panic')}{C_RESET}")
                    self.drain_cmd_queue()
                    with self._safety_lock:
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
    parser.add_argument("--dry-run", action="store_true", help="Chế độ shadow/dry-run: phân tích dò hú nhưng không gửi lệnh ghi xuống mixer")
    parser.add_argument("--mic", action="store_true", help="Mở micro thật của máy tính để thu âm (hữu ích khi kết hợp --mock)")
    parser.add_argument("--audible", action="store_true", help="Phát trực tiếp âm thanh mô phỏng (nhạc + tiếng hú) ra loa máy tính")
    parser.add_argument("--input-device", default=None, help="Tên hoặc index thiết bị thu âm đầu vào (mặc định: micro hệ thống)")
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

    app = AutoSoundApp(
        config=config,
        mapper=mapper,
        mock_mode=args.mock,
        mode=args.mode,
        use_real_mic=args.mic,
        input_device=args.input_device,
        audible=args.audible,
    )
    app.dry_run = args.dry_run

    if args.web:
        import uvicorn
        import webbrowser
        from auto_sound.app.server import create_app
        host = "0.0.0.0" if args.listen_lan else args.host
        web_app = create_app(engine=app, listen_lan=args.listen_lan, mock_mode=args.mock, dry_run=args.dry_run)
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
