"""Kiểm thử State Machine và Verified Write của XAirClient."""

import time
import pytest
from auto_sound.core.models import ConnectionState
from auto_sound.mixer.fake import FakeXR18
from auto_sound.mixer.xair import XAirClient


@pytest.fixture
def fake_xr18():
    server = FakeXR18(host="127.0.0.1", port=0)
    server.start()
    yield server
    server.stop()


def test_xair_connect_success(fake_xr18: FakeXR18) -> None:
    client = XAirClient(ip=fake_xr18.host, port=fake_xr18.port, timeout_s=1.0)
    ok = client.connect()
    assert ok is True
    assert client.get_state() == ConnectionState.CONNECTED
    client.disconnect()
    assert client.get_state() == ConnectionState.DISCONNECTED


def test_verified_write_peq(fake_xr18: FakeXR18) -> None:
    client = XAirClient(ip=fake_xr18.host, port=fake_xr18.port, timeout_s=1.0)
    client.connect()

    # Ghi PEQ dải tần 2500Hz, -3.0dB, Q=5.0
    success = client.set_peq(channel=1, band=3, freq_hz=2500.0, gain_db=-3.0, q=5.0, is_on=True)
    assert success is True

    # Đọc lại kiểm tra
    band_info = client.get_peq(channel=1, band=3)
    assert band_info is not None
    assert band_info.channel == 1
    assert band_info.band == 3
    assert pytest.approx(band_info.freq_hz, rel=0.05) == 2500.0
    assert pytest.approx(band_info.gain_db, abs=0.5) == -3.0
    assert band_info.is_on is True

    client.disconnect()


def test_state_reconnecting_and_recovery(fake_xr18: FakeXR18) -> None:
    """Kiểm tra state machine tự hồi phục lại khi mixer tạm thời ngắt kết nối."""
    saved_port = fake_xr18.port
    client = XAirClient(ip="127.0.0.1", port=saved_port, timeout_s=0.5, reconnect_interval_s=0.2)
    assert client.connect() is True
    assert client.get_state() == ConnectionState.CONNECTED

    # Tắt fake server để mô phỏng mất kết nối
    fake_xr18.stop()
    time.sleep(0.1)

    # Chuyển thủ công hoặc kích hoạt kiểm tra
    client._set_state(ConnectionState.RECONNECTING)
    assert client.get_state() == ConnectionState.RECONNECTING

    # Khởi động lại fake server trên cùng cổng
    new_server = FakeXR18(host="127.0.0.1", port=saved_port)
    new_server.start()

    # Chờ tối đa 3 giây để client tự động kết nối lại
    recovered = False
    for _ in range(30):
        if client.get_state() == ConnectionState.CONNECTED:
            recovered = True
            break
        time.sleep(0.1)

    assert recovered is True
    client.disconnect()
    new_server.stop()
