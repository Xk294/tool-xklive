"""Kiểm thử tính năng tương tác trực tiếp với mixer X-Air:
1. Tự động dò tìm (Auto-Discovery qua OSC UDP).
2. Nhận diện thiết bị (Model, Tên, Firmware qua /xinfo).
3. Đồng bộ cấu hình kênh (Tên, Màu sắc, Trạng thái MUTE từ X-Air).
4. Thiết lập chuẩn PEQ (Bật Master EQ và đặt Band Type = PEQ).
5. Các REST API v1 cho kênh và dò tìm mixer.
"""

import socket
import time
import pytest
from fastapi.testclient import TestClient

from auto_sound.core.models import ConnectionState
from auto_sound.mixer.fake import FakeXR18
from auto_sound.mixer.osc import encode_message
from auto_sound.mixer.xair import XAirClient, discover_mixers
from auto_sound.app.server import create_app
from auto_sound.app.cli import AutoSoundApp
from auto_sound.core.config import AppConfig
from auto_sound.mixer.parameter_mapper import ParameterMapper
from pathlib import Path


@pytest.fixture
def fake_xr18_server():
    server = FakeXR18(host="127.0.0.1", port=0)
    server.start()
    yield server
    server.stop()


def test_discover_mixers_local(fake_xr18_server: FakeXR18) -> None:
    """Kiểm tra chức năng quét tìm mixer X-Air qua UDP."""
    found = discover_mixers(timeout_s=0.5, port=fake_xr18_server.port, targets=["127.0.0.1"])
    assert len(found) >= 1
    m = found[0]
    assert m["model"] == "XR18"
    assert m["name"] == "XR18-FakeSim"
    assert m["firmware"] == "1.18"


def test_mixer_device_info_handshake(fake_xr18_server: FakeXR18) -> None:
    """Kiểm tra XAirClient lưu trữ thông tin Model, Firmware, Name sau khi bắt tay /xinfo."""
    client = XAirClient(ip=fake_xr18_server.host, port=fake_xr18_server.port, timeout_s=1.0)
    ok = client.connect()
    assert ok is True
    assert client.mixer_model == "XR18"
    assert client.mixer_name == "XR18-FakeSim"
    assert client.mixer_firmware == "1.18"

    info = client.get_device_info()
    assert info["model"] == "XR18"
    assert info["name"] == "XR18-FakeSim"
    assert info["firmware"] == "1.18"
    assert info["state"] == "CONNECTED"
    client.disconnect()


def test_channel_metadata_sync_and_mute_tracking(fake_xr18_server: FakeXR18) -> None:
    """Kiểm tra đồng bộ tên, màu sắc và tự động cập nhật khi soundman Mute trên iPad."""
    client = XAirClient(ip=fake_xr18_server.host, port=fake_xr18_server.port, timeout_s=1.0)
    client.connect()

    # Chờ đồng bộ metadata từ FakeXR18
    time.sleep(0.1)

    # Mặc định kênh 1 unmuted, tên "Mic 1"
    ch1_info = client.get_channel_info(1)
    assert ch1_info["name"] == "Mic 1"
    assert ch1_info["is_muted"] is False
    assert client.is_channel_muted(1) is False

    # Giả lập iPad của soundman gửi lệnh MUTE Kênh 1 (/ch/01/mix/on 0)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(encode_message("/ch/01/mix/on", 0), (fake_xr18_server.host, fake_xr18_server.port))
    sock.close()

    time.sleep(0.1)
    # Client nhận broadcast echo và cập nhật trạng thái mute
    assert client.is_channel_muted(1) is True

    # Giả lập iPad đổi tên Kênh 1 thành "Lead Vox"
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(encode_message("/ch/01/config/name", "Lead Vox"), (fake_xr18_server.host, fake_xr18_server.port))
    sock.close()

    time.sleep(0.1)
    assert client.get_channel_name(1) == "Lead Vox"

    client.disconnect()


def test_peq_ensures_master_eq_and_type_peq(fake_xr18_server: FakeXR18) -> None:
    """Kiểm tra set_peq tự động bật Master EQ và đặt Band Type = PEQ (type 2)."""
    # Ban đầu giả sử soundman đang tắt Master EQ (/ch/02/eq/on = 0) và Band 4 là High Cut (type = 5)
    fake_xr18_server.params["/ch/02/eq/on"] = 0
    fake_xr18_server.params["/ch/02/eq/4/type"] = 5

    client = XAirClient(ip=fake_xr18_server.host, port=fake_xr18_server.port, timeout_s=1.0)
    client.connect()

    # Ghi notch hạ hú trên Kênh 2 Band 4
    ok = client.set_peq(channel=2, band=4, freq_hz=3150.0, gain_db=-4.0, q=8.0)
    assert ok is True

    # Kiểm tra Master EQ đã được bật lại để notch có tác dụng
    assert fake_xr18_server.params["/ch/02/eq/on"] == 1
    # Kiểm tra Band Type đã được chuyển sang PEQ (type 2)
    assert fake_xr18_server.params["/ch/02/eq/4/type"] == 2

    # Đọc lại PEQ kiểm tra filter_type
    band = client.get_peq(channel=2, band=4)
    assert band is not None
    assert band.filter_type == 2

    client.disconnect()


def test_server_channels_and_discovery_api(fake_xr18_server: FakeXR18) -> None:
    """Kiểm tra API /api/v1/channels và /api/v1/mixer/discover của Web Companion."""
    cfg_path = Path(__file__).resolve().parent.parent / "device_profiles" / "xr18.toml"
    config = AppConfig.load(cfg_path)
    config.network.default_mixer_ip = fake_xr18_server.host
    config.device.port = fake_xr18_server.port
    mapper = ParameterMapper.from_profile(cfg_path)

    engine = AutoSoundApp(config=config, mapper=mapper, mock_mode=True, mode="auto")
    engine.start()

    time.sleep(0.2)
    api = create_app(engine=engine, mock_mode=True)
    client = TestClient(api)

    # Kiểm tra endpoint status trả về model và firmware thật
    status_resp = client.get("/api/v1/status")
    assert status_resp.status_code == 200
    st_data = status_resp.json()
    assert "XR18" in st_data["model"]
    assert st_data["hardware_model"] == "XR18"
    assert st_data["firmware"] == "1.18"
    assert st_data["mixer_name"] == "XR18-FakeSim"

    # Kiểm tra endpoint channels trả về danh sách kênh đầy đủ
    ch_resp = client.get("/api/v1/channels")
    assert ch_resp.status_code == 200
    ch_data = ch_resp.json()
    assert "channels" in ch_data
    assert len(ch_data["channels"]) == 16
    assert ch_data["channels"][0]["name"] == "Mic 1"
    assert ch_data["channels"][0]["is_muted"] is False

    # Kiểm tra endpoint discover
    disc_resp = client.get("/api/v1/mixer/discover")
    assert disc_resp.status_code == 200
    assert "mixers" in disc_resp.json()

    engine.stop()
