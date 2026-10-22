"""Kiểm thử tính năng Phase 0: Capability Probe và phát hiện dialect OSC thực tế."""

import socket
import time
import pytest
from auto_sound.mixer.fake import FakeXR18
from auto_sound.mixer.xair import XAirClient
from auto_sound.core.models import ConnectionState, CapabilityMap


@pytest.fixture
def fake_mixer():
    server = FakeXR18(host="127.0.0.1", port=0)
    server.start()
    yield server
    server.stop()


def test_capability_probe_detects_real_paths(fake_mixer: FakeXR18) -> None:
    """Xác nhận capability probe thăm dò đúng dialect /lr, /rtn, /headamp và không ghi bất kỳ dữ liệu nào."""
    # Lưu trạng thái ban đầu của fake mixer để kiểm tra tính thuần ĐỌC (Zero Writes)
    initial_params = dict(fake_mixer.params)

    client = XAirClient(ip=fake_mixer.host, port=fake_mixer.port, timeout_s=0.3)
    connected = client.connect()
    assert connected is True
    assert client.get_state() == ConnectionState.CONNECTED

    # Kiểm tra CapabilityMap sau khi connect
    cap = client.get_capability_map()
    assert cap.probe_completed is True
    assert cap.lr_prefix == "/lr"
    assert cap.num_channels in (16, 18)
    assert cap.num_busses == 6
    assert cap.channel_peq_bands == 4
    assert cap.bus_peq_bands == 6
    assert cap.supports_headamp is True
    assert cap.supports_fx_return is True
    assert cap.supports_automix is False  # FakeXR18 không có automix

    # Đảm bảo Probe hoàn toàn READ-ONLY: Không có bất kỳ tham số nào trên mixer bị thay đổi giá trị
    for addr, val in initial_params.items():
        assert fake_mixer.params[addr] == val

    client.disconnect()


def test_peq_uses_detected_lr_prefix(fake_mixer: FakeXR18) -> None:
    """Xác nhận khi ghi PEQ lên Main Stereo, client dùng đúng đường dẫn /lr thay vì /main/st."""
    client = XAirClient(ip=fake_mixer.host, port=fake_mixer.port, timeout_s=0.3)
    connected = client.connect()
    assert connected is True

    # Ghi PEQ lên Main LR (target="lr" hoặc target="main")
    ok = client.set_peq(channel=0, band=1, freq_hz=1000.0, gain_db=-4.5, q=8.0, target="lr")
    assert ok is True

    # Kiểm tra trong FakeXR18: tham số /lr/eq/1/g đã được ghi nhận
    assert "/lr/eq/1/g" in fake_mixer.params
    assert fake_mixer.params["/lr/eq/on"] == 1
    assert fake_mixer.params["/lr/eq/1/type"] == 2

    # Đọc lại bằng get_peq
    peq = client.get_peq(channel=0, band=1, target="lr")
    assert peq is not None
    assert abs(peq.gain_db - (-4.5)) < 0.2

    client.disconnect()


def test_probe_handles_unsupported_paths_gracefully(fake_mixer: FakeXR18) -> None:
    """Xác nhận probe xử lý timeout sạch sẽ khi gặp mixer không phản hồi đường dẫn."""
    client = XAirClient(ip=fake_mixer.host, port=fake_mixer.port, timeout_s=0.1)
    connected = client.connect()
    assert connected is True

    # Thử probe một đường dẫn không tồn tại
    res = client._query_param_sync("/non/existent/path/xyz", timeout=0.08)
    assert res is None

    client.disconnect()
