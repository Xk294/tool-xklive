"""Kiểm thử hàng đợi mạng phi đồng bộ (Async Queue) và phát hiện can thiệp chỉnh tay (Manual Override)."""

import time
from pathlib import Path
from auto_sound.core.config import AppConfig
from auto_sound.core.models import ActionProposal, ConnectionState
from auto_sound.mixer.fake import FakeXR18
from auto_sound.mixer.parameter_mapper import ParameterMapper
from auto_sound.mixer.xair import XAirClient
from auto_sound.app.cli import AutoSoundApp
from auto_sound.safety.controller import decide


def test_async_network_queue_execution() -> None:
    """Kiểm tra hàng đợi lệnh không block và thực thi gửi sang mixer thành công."""
    fake_mixer = FakeXR18(host="127.0.0.1", port=0)
    fake_mixer.start()

    cfg_path = Path(__file__).resolve().parent.parent / "device_profiles" / "xr18.toml"
    config = AppConfig.load(cfg_path)
    config.network.default_mixer_ip = fake_mixer.host
    config.device.port = fake_mixer.port

    mapper = ParameterMapper.from_profile(cfg_path)
    app = AutoSoundApp(config=config, mapper=mapper, mock_mode=True, mode="auto")

    try:
        app.start()
        # Chờ kết nối mixer thành công
        time.sleep(0.3)
        assert app.mixer_client is not None
        assert app.mixer_client.get_state() == ConnectionState.CONNECTED

        # Đẩy 1 proposal vào hàng đợi bất đồng bộ
        prop = ActionProposal(
            channel=2,
            band=3,
            freq_hz=2500.0,
            gain_db=-3.0,
            q=8.0,
            reason="Test async queue",
        )
        # Gửi phi đồng bộ (mặc định async_send=True)
        ret = app.execute_proposal(prop, async_send=True)
        assert ret is True

        # Chờ worker thread lấy từ queue và gửi verified write tới FakeXR18
        time.sleep(0.4)

        # Đọc lại từ FakeXR18 để xác minh tham số đã thực sự được áp dụng
        peq = app.mixer_client.get_peq(channel=2, band=3)
        assert peq is not None
        assert abs(peq.freq_hz - 2500.0) < 50.0
        assert abs(peq.gain_db - (-3.0)) < 0.5
        assert abs(peq.q - 8.0) < 0.5
    finally:
        app.stop()


def test_manual_override_detection_callback() -> None:
    """Kiểm tra khi nhận gói tin OSC từ bên ngoài, hệ thống tự động khóa kênh 10s."""
    fake_mixer = FakeXR18(host="127.0.0.1", port=0)
    fake_mixer.start()

    cfg_path = Path(__file__).resolve().parent.parent / "device_profiles" / "xr18.toml"
    config = AppConfig.load(cfg_path)
    config.network.default_mixer_ip = fake_mixer.host
    config.device.port = fake_mixer.port

    mapper = ParameterMapper.from_profile(cfg_path)
    app = AutoSoundApp(config=config, mapper=mapper, mock_mode=True, mode="auto")

    try:
        app.start()
        time.sleep(0.3)

        # Giả lập soundman vặn EQ kênh 2 trên iPad (gửi gói tin OSC từ bên ngoài vào client)
        now_before = time.time()
        app._on_mixer_param_change("/ch/02/eq/1/g", 0.7)

        # Kiểm tra kênh 2 đã bị khóa
        lock_until = app.safety_state.channel_locks.get(2, 0.0)
        assert lock_until >= now_before + 9.5

        # Đề xuất can thiệp vào kênh 2 ngay lập tức phải bị từ chối do soundman vừa chỉnh tay
        test_prop = ActionProposal(channel=2, freq_hz=1000.0, gain_db=-3.0, q=8.0)
        new_state, dec = decide(app.safety_state, test_prop, now=time.time())
        assert dec.approved is False
        assert "chỉnh tay" in dec.reason
    finally:
        app.stop()


def test_manual_override_detection_main_lr_both_dialects() -> None:
    """Xác nhận phát hiện can thiệp tay trên Main L/R đối với cả 2 dialect /lr/eq và /main/st/eq."""
    cfg_path = Path(__file__).resolve().parent.parent / "device_profiles" / "xr18.toml"
    config = AppConfig.load(cfg_path)
    mapper = ParameterMapper.from_profile(cfg_path)
    app = AutoSoundApp(config=config, mapper=mapper, mock_mode=True, mode="auto")
    try:
        now_before = time.time()
        # 1. Dialect X-Air: /lr/eq/3/g
        app._on_mixer_param_change("/lr/eq/3/g", 0.6)
        lock_until = app.safety_state.channel_locks.get(0, 0.0)
        assert lock_until >= now_before + 9.5

        # 2. Dialect X32: /main/st/eq/4/g
        now_before2 = time.time()
        app._on_mixer_param_change("/main/st/eq/4/g", 0.4)
        lock_until2 = app.safety_state.channel_locks.get(0, 0.0)
        assert lock_until2 >= now_before2 + 9.5
    finally:
        app.stop()
