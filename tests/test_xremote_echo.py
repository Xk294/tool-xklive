"""Kiểm thử cơ chế Expected-Echo và ngăn ngừa khóa oan kênh khi nhận echo /xremote."""

import socket
import time
from pathlib import Path
from auto_sound.core.config import AppConfig
from auto_sound.core.models import ActionProposal, ConnectionState
from auto_sound.mixer.fake import FakeXR18
from auto_sound.mixer.osc import encode_message
from auto_sound.mixer.parameter_mapper import ParameterMapper
from auto_sound.mixer.xair import XAirClient
from auto_sound.app.cli import AutoSoundApp


def test_expected_echo_ttl_expiry() -> None:
    """Kiểm tra expected-echo hoạt động chuẩn và tự hết hạn sau TTL."""
    client = XAirClient(ip="127.0.0.1", port=10024)
    # Đăng ký expected echo với TTL ngắn 0.15s
    client.register_expected_echo("/ch/01/eq/3/f", 0.525, is_int=False, ttl_s=0.15)

    # Trong hạn: Khớp giá trị -> True
    assert client._is_expected_echo("/ch/01/eq/3/f", 0.525) is True
    # Khác giá trị -> False
    assert client._is_expected_echo("/ch/01/eq/3/f", 0.700) is False

    # Chờ quá hạn TTL
    time.sleep(0.2)
    # Đã hết hạn -> False
    assert client._is_expected_echo("/ch/01/eq/3/f", 0.525) is False


def test_system_peq_write_does_not_trigger_manual_override_lock() -> None:
    """Chứng minh lệnh ghi PEQ của app (và echo /xremote từ FakeXR18) KHÔNG khóa oan kênh."""
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
        assert app.mixer_client is not None
        assert app.mixer_client.get_state() == ConnectionState.CONNECTED

        # Gửi hạ notch trên Kênh 2 Band 3
        prop = ActionProposal(
            channel=2,
            band=3,
            freq_hz=2500.0,
            gain_db=-3.0,
            q=8.0,
            reason="Test no lock on echo",
        )
        app.execute_proposal(prop, async_send=False)

        # Chờ mạng LAN xử lý và FakeXR18 broadcast echo
        time.sleep(0.2)

        # Khẳng định Kênh 2 KHÔNG bị khóa
        lock_until = app.safety_state.channel_locks.get(2, 0.0)
        assert lock_until <= time.time(), f"Kênh 2 bị khóa oan đến {lock_until} (now={time.time()})"
    finally:
        app.stop()


def test_external_soundman_adjust_different_band_locks_channel() -> None:
    """Chứng minh thay đổi từ soundman (client khác) trên Band 1 làm khóa kênh 10s."""
    cfg_path = Path(__file__).resolve().parent.parent / "device_profiles" / "xr18.toml"
    config = AppConfig.load(cfg_path)
    mapper = ParameterMapper.from_profile(cfg_path)
    app = AutoSoundApp(config=config, mapper=mapper, mock_mode=True, mode="auto")

    try:
        app.start()
        time.sleep(0.3)
        fake_mixer = app.fake_mixer
        assert fake_mixer is not None

        # Giả lập iPad của soundman gửi lệnh vặn EQ Band 1 lên mixer FakeXR18
        ext_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Gửi lệnh đổi gain Band 1 lên +4dB (float ~0.63)
        now_change = time.time()
        ext_sock.sendto(encode_message("/ch/02/eq/1/g", 0.63), (fake_mixer.host, fake_mixer.port))

        # Chờ echo broadcast từ FakeXR18 đến app
        time.sleep(0.2)

        # Kênh 2 PHẢI bị khóa an toàn 10s
        lock_until = app.safety_state.channel_locks.get(2, 0.0)
        assert lock_until >= now_change + 9.0, f"Kênh 2 không bị khóa đúng hạn: {lock_until} vs now={now_change}"
    finally:
        ext_sock.close()
        app.stop()


def test_soundman_adjusts_same_band_system_wrote_locks_channel() -> None:
    """Chứng minh nếu soundman vặn đúng Band 3 mà hệ thống vừa ghi (nhưng giá trị khác), kênh VẪN bị khóa."""
    cfg_path = Path(__file__).resolve().parent.parent / "device_profiles" / "xr18.toml"
    config = AppConfig.load(cfg_path)
    mapper = ParameterMapper.from_profile(cfg_path)
    app = AutoSoundApp(config=config, mapper=mapper, mock_mode=True, mode="auto")

    try:
        app.start()
        time.sleep(0.3)
        fake_mixer = app.fake_mixer
        assert fake_mixer is not None

        # Hệ thống vừa ghi Band 3 gain = -3.0 dB (float = 0.4)
        prop = ActionProposal(channel=2, band=3, freq_hz=2500.0, gain_db=-3.0, q=8.0)
        app.execute_proposal(prop, async_send=False)
        time.sleep(0.1)

        # Kênh 2 chưa bị khóa
        assert app.safety_state.channel_locks.get(2, 0.0) <= time.time()

        # Soundman trên iPad can thiệp vào chính Band 3, đặt gain = +6.0 dB (float = 0.7)
        ext_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        now_override = time.time()
        ext_sock.sendto(encode_message("/ch/02/eq/3/g", 0.70), (fake_mixer.host, fake_mixer.port))

        time.sleep(0.2)

        # Kênh 2 PHẢI bị khóa vì giá trị 0.70 khác biệt hoàn toàn với echo kỳ vọng 0.40
        lock_until = app.safety_state.channel_locks.get(2, 0.0)
        assert lock_until >= now_override + 9.0, "Soundman can thiệp cùng band nhưng không bị khóa!"
    finally:
        ext_sock.close()
        app.stop()
