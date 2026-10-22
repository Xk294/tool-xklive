"""Kiểm thử tính năng V2: Ring-Out, Auto Preamp Gain Staging, và Smart FX Talkover."""

import time
import pytest
from auto_sound.core.ringout import RingOutConfig, RingOutController
from auto_sound.dsp.gain_staging import GainStagingManager
from auto_sound.dsp.talkover import TalkoverConfig, TalkoverController


def test_ringout_lifecycle_and_fader_restoration() -> None:
    """Xác nhận quy trình Ring-Out luôn khôi phục fader ban đầu khi dừng hoặc hoàn tất."""
    controller = RingOutController(RingOutConfig(max_notches=2, step_interval_s=0.1))
    now = 1000.0

    # Khởi động với fader ban đầu = 0.70
    started = controller.start(target_type="bus", target_id=1, initial_fader_val=0.70, now=now)
    assert started is True
    assert controller.is_active is True

    # 1. Khung đo bình thường -> Fader tăng từng nấc
    new_fader, prop, report = controller.process_frame([-50.0] * 100, now + 0.15)
    assert new_fader is not None
    assert new_fader > 0.70
    assert prop is None
    assert report is None

    # 2. Khung đo có đỉnh cộng hưởng tại bin 50 (-10 dBFS nhô cao hơn sàn -50 dBFS)
    rta_peak = [-50.0] * 100
    rta_peak[50] = -10.0
    fader_retreated, prop_notch, _ = controller.process_frame(rta_peak, now + 0.3)
    assert prop_notch is not None
    assert prop_notch.target == "bus"
    assert prop_notch.bus == 1
    assert prop_notch.gain_db == -4.5
    assert prop_notch.q == 10.0

    # 3. Dừng khẩn cấp (Emergency Stop) -> Báo cáo trả về và fader quay về 0.70
    rep = controller.stop(reason="aborted")
    assert rep.status == "ABORTED"
    assert rep.final_fader_db == controller.initial_fader_db
    assert controller.is_active is False


def test_gain_staging_10s_calculation_and_clip_guardian() -> None:
    """Xác nhận thuật toán tính Gain chuẩn RMS -18dBFS, Peak -6dBFS và cảnh báo Clip."""
    manager = GainStagingManager(target_rms_dbfs=-18.0, max_peak_dbfs=-6.0)
    now = 100.0

    # Khởi động phiên đo kênh 1 với Gain hiện tại = 20.0 dB
    manager.start_calibration(channel=1, current_headamp_gain_db=20.0)

    # Giả lập 10 giây thu mẫu: RMS trung bình = -24.0 dBFS (nhỏ hơn target 6dB), Peak = -12.0 dBFS
    # Cần tăng +6 dB để đạt -18 dBFS
    session = manager.sessions[1]
    session.start_time = now - 10.1  # Đã đủ 10 giây

    proposed, _ = manager.process_meter_sample(channel=1, peak_level_dbfs=-12.0, rms_level_dbfs=-24.0, now=now)
    assert proposed is not None
    assert proposed == 26.0  # 20.0 + 6.0 = 26.0 dB

    # Kiểm tra Clip Guardian: Đỏ vạch liên tục > 300 ms
    _, alert1 = manager.process_meter_sample(channel=2, peak_level_dbfs=-0.2, rms_level_dbfs=-10.0, now=now)
    assert alert1 is None  # Mới chớm đỏ, chưa đủ 300 ms

    # Sau 350 ms vẫn đỏ vạch -> Phải phát cảnh báo đề xuất hạ 3 dB
    _, alert2 = manager.process_meter_sample(channel=2, peak_level_dbfs=-0.1, rms_level_dbfs=-9.5, now=now + 0.35)
    assert alert2 is not None
    assert alert2.channel == 2
    assert alert2.suggested_reduction_db == -3.0


def test_smart_fx_talkover_ducking_and_hold_time() -> None:
    """Xác nhận Smart FX dập reverb khi nhạc tắt + mic nói, và khôi phục khi nhạc lên."""
    cfg = TalkoverConfig(enabled=True, hold_time_s=1.5, fade_duration_ms=100.0)
    ctrl = TalkoverController(cfg)
    ctrl.set_original_fader(0.75)
    now = 50.0

    # 1. Trạng thái bình thường: Nhạc to (-20 dBFS), mic hát (-25 dBFS) -> Không kích hoạt
    fader, _, _ = ctrl.process_frame(mic_energy_dbfs=-25.0, music_energy_dbfs=-20.0, now=now)
    assert ctrl.is_ducked is False

    # 2. Nhạc dừng (-60 dBFS) và MC bắt đầu nói (-35 dBFS) -> Kích hoạt Talkover!
    fader, _, msg = ctrl.process_frame(mic_energy_dbfs=-35.0, music_energy_dbfs=-60.0, now=now + 0.1)
    assert ctrl.is_ducked is True
    assert "Kích hoạt Talkover" in msg

    # Cập nhật fade (sau 150 ms > 100 ms duration) -> Fader đã hạ xuống mức ducked
    fader_ducked, _, _ = ctrl.process_frame(mic_energy_dbfs=-35.0, music_energy_dbfs=-60.0, now=now + 0.25)
    assert fader_ducked is not None
    assert fader_ducked == ctrl.ducked_fader_val

    # 3. Nhạc nền nổi lên (-25 dBFS) -> Tự động nhả Talkover và fade-in về ban đầu
    _, _, msg_restore = ctrl.process_frame(mic_energy_dbfs=-40.0, music_energy_dbfs=-25.0, now=now + 0.5)
    assert ctrl.is_ducked is False
    assert "Nhả Talkover" in msg_restore

    # Sau thời gian fade 100ms -> Fader quay về đúng 0.75
    fader_restored, _, _ = ctrl.process_frame(mic_energy_dbfs=-40.0, music_energy_dbfs=-25.0, now=now + 0.7)
    assert fader_restored == 0.75
