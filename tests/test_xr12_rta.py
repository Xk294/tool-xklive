"""Kiểm thử chuyên sâu cho giải pháp chống hú qua mạng LAN dựa trên RTA 100-band trên XR12, XR16, MR12."""

import time
from pathlib import Path
import numpy as np
import pytest

from auto_sound.core.config import AppConfig
from auto_sound.core.models import ConnectionState
from auto_sound.dsp.rta_detector import RTADetector
from auto_sound.mixer.fake import FakeXR18
from auto_sound.mixer.parameter_mapper import ParameterMapper
from auto_sound.mixer.xair import XAirClient
from auto_sound.app.cli import AutoSoundApp


def test_xr12_xr16_mr12_profiles_load() -> None:
    """Kiểm tra việc nạp cấu hình hợp lệ của các profile XR12, XR16, MR12."""
    base_dir = Path(__file__).resolve().parent.parent / "device_profiles"

    # 1. XR12
    cfg12 = AppConfig.load(base_dir / "xr12.toml")
    assert cfg12.device.name == "Behringer XR12"
    assert cfg12.device.has_multichannel_usb is False
    assert cfg12.device.supports_rta_network is True
    assert cfg12.channels.mic_channels == [1, 2, 3, 4]
    assert cfg12.eq.main_auto_notch_bands == [3, 4, 5, 6]

    # 2. XR16
    cfg16 = AppConfig.load(base_dir / "xr16.toml")
    assert cfg16.device.name == "Behringer XR16"
    assert cfg16.device.has_multichannel_usb is False
    assert cfg16.channels.mic_channels == [1, 2, 3, 4, 5, 6, 7, 8]

    # 3. MR12
    cfg_mr12 = AppConfig.load(base_dir / "mr12.toml")
    assert cfg_mr12.device.name == "Midas MR12"
    assert cfg_mr12.device.has_multichannel_usb is False


def test_rta_detector_math_and_peak_detection() -> None:
    """Kiểm tra toán học chuyển đổi bin-frequency và khả năng phát hiện đỉnh hú của RTADetector."""
    detector = RTADetector(num_bins=100, f_min_hz=20.0, f_max_hz=20000.0)

    # 1. Kiểm tra biên tần số
    assert abs(detector.bin_to_freq(0) - 20.0) < 0.1
    assert abs(detector.bin_to_freq(99) - 20000.0) < 1.0

    # 2. Round-trip giữa Hz và bin
    for test_f in [100.0, 500.0, 1000.0, 2500.0, 8000.0]:
        b = detector.freq_to_bin(test_f)
        reconstructed_f = detector.bin_to_freq(b)
        assert abs(reconstructed_f - test_f) / test_f < 0.1  # Sai số trong phạm vi 10% (1 nấc bin)

    # 3. Khung tín hiệu phẳng không có hú -> 0 đề xuất
    flat_frame = np.full(100, -30.0, dtype=np.float32)
    for _ in range(5):
        props = detector.process_rta_frame(flat_frame)
        assert len(props) == 0

    # 4. Xuất hiện đỉnh hú bùng phát tại bin 70 (~2500 Hz) qua 3 khung liên tiếp
    bin_target = detector.freq_to_bin(2500.0)
    proposals = []
    for step in range(3):
        frame = np.full(100, -35.0, dtype=np.float32)
        # Năng lượng tăng dần: -20dBFS -> -15dBFS -> -10dBFS
        frame[bin_target] = -20.0 + step * 5.0
        props = detector.process_rta_frame(frame, target_name="main")
        if props:
            proposals.extend(props)

    assert len(proposals) == 1
    p = proposals[0]
    assert p.target == "main"
    assert p.channel == 0
    assert abs(p.freq_hz - 2500.0) < 200.0
    assert p.gain_db == -3.0
    assert p.q == 10.0


def test_fake_xr18_main_peq_and_rta() -> None:
    """Kiểm tra FakeXR18 xử lý PEQ Main Stereo và trả về luồng RTA 100-band."""
    fake = FakeXR18(host="127.0.0.1", port=0)
    fake._fake_feedback_bin = 70  # Giả lập có peak hú tại bin 70
    fake.start()

    mapper = ParameterMapper.from_profile({
        "eq": {
            "freq_min_hz": 20.0, "freq_max_hz": 20000.0, "freq_steps": 201,
            "gain_min_db": -15.0, "gain_max_db": 15.0, "gain_steps": 121,
            "q_min": 0.3, "q_max": 10.0, "q_steps": 72,
        }
    })
    client = XAirClient(ip=fake.host, port=fake.port, mapper=mapper, timeout_s=1.0)

    try:
        assert client.connect() is True

        # Đọc và ghi PEQ trên Main Stereo (target="main")
        ok = client.set_peq(channel=0, band=3, freq_hz=2500.0, gain_db=-6.0, q=10.0, target="main")
        assert ok is True

        peq = client.get_peq(channel=0, band=3, target="main")
        assert peq is not None
        assert abs(peq.freq_hz - 2500.0) < 50.0
        assert abs(peq.gain_db - (-6.0)) < 0.5
        assert abs(peq.q - 10.0) < 0.5

        # Đăng ký nhận RTA
        client.subscribe_rta(enable=True)
        time.sleep(0.3)
        rta_levels = client.get_rta_levels()
        assert len(rta_levels) == 100
        # Peak tại bin 70 phải cao hơn sàn (-10dBFS vs -47dBFS)
        assert rta_levels[70] > rta_levels[0] + 30.0
    finally:
        client.disconnect()
        fake.stop()


def test_end_to_end_xr12_rta_feedback_loop() -> None:
    """Kiểm thử khép kín toàn trình: XR12 gửi RTA qua mạng -> Phát hiện hú -> Hạ notch Main LR."""
    fake_mixer = FakeXR18(host="127.0.0.1", port=0)
    fake_mixer._fake_feedback_bin = 70  # Bin 70 tương ứng khoảng 2500 Hz
    fake_mixer.start()

    cfg_path = Path(__file__).resolve().parent.parent / "device_profiles" / "xr12.toml"
    config = AppConfig.load(cfg_path)
    config.network.default_mixer_ip = fake_mixer.host
    config.device.port = fake_mixer.port

    mapper = ParameterMapper.from_profile(cfg_path)
    app = AutoSoundApp(config=config, mapper=mapper, mock_mode=False, mode="auto")

    try:
        app.start()
        time.sleep(0.3)
        assert app.mixer_client is not None
        assert app.mixer_client.get_state() == ConnectionState.CONNECTED
        assert app.audio_capture is None  # XR12 không cần mở soundcard!

        # Giả lập FakeXR18 phát sóng 3 khung RTA có tiếng hú tăng trưởng tại bin 70
        rta_frame1 = [-40.0] * 100
        rta_frame1[70] = -20.0
        rta_frame2 = [-40.0] * 100
        rta_frame2[70] = -15.0
        rta_frame3 = [-40.0] * 100
        rta_frame3[70] = -10.0

        app._on_rta_levels_received(rta_frame1)
        app._on_rta_levels_received(rta_frame2)
        app._on_rta_levels_received(rta_frame3)

        # Chờ worker thread lấy lệnh từ hàng đợi và gửi verified write xuống Main LR PEQ
        time.sleep(0.4)

        # Đọc lại từ FakeXR18 để xác minh Band 3 trên Main Stereo đã được hạ notch an toàn
        peq_main = app.mixer_client.get_peq(channel=0, band=3, target="main")
        assert peq_main is not None
        # Bin 70 có tần số trung tâm ~2643 Hz, sau khi snap vào nấc PEQ là ~2606 Hz
        assert abs(peq_main.freq_hz - 2500.0) < 200.0
        assert abs(peq_main.gain_db - (-3.0)) < 0.1  # Đã cắt thăm dò an toàn -3dB
        assert peq_main.q == 10.0
    finally:
        app.stop()
        fake_mixer.stop()
