"""Kiểm thử tính năng Snapshot và Rollback toàn diện (Giai đoạn D5)."""

import time
import pytest
from auto_sound.mixer.fake import FakeXR18
from auto_sound.mixer.parameter_mapper import ParameterMapper
from auto_sound.mixer.xair import XAirClient
from auto_sound.safety.snapshot import PEQSnapshot, SnapshotManager


@pytest.fixture
def fake_mixer_and_client():
    fake = FakeXR18(host="127.0.0.1", port=0)
    fake.start()

    from pathlib import Path
    cfg_path = Path(__file__).resolve().parent.parent / "device_profiles" / "xr18.toml"
    mapper = ParameterMapper.from_profile(cfg_path)

    client = XAirClient(ip=fake.host, port=fake.port, mapper=mapper, timeout_s=0.5)
    connected = client.connect()
    assert connected is True

    yield fake, client

    client.disconnect()
    fake.stop()


def test_snapshot_capture_and_rollback_timing(fake_mixer_and_client) -> None:
    """Kiểm tra chụp snapshot và hoàn tác hoàn tất dưới 1.0 giây."""
    fake, client = fake_mixer_and_client
    manager = SnapshotManager(client)

    # 1. Chụp snapshot trạng thái ban đầu
    snap = manager.take_snapshot(channels=[1, 2], buses=[1, 2], include_main=True)
    assert len(snap.bands) > 0
    assert "/ch/01/eq/1" in snap.bands
    assert "/bus/1/eq/5" in snap.bands

    # 2. Can thiệp thay đổi giá trị một số band
    client.set_peq(channel=1, band=3, freq_hz=2500.0, gain_db=-10.0, q=8.0, target="ch")
    client.set_peq(channel=1, band=5, freq_hz=4000.0, gain_db=-12.0, q=6.0, target="bus")

    # Xác minh cache đã bị thay đổi
    assert client._params_cache.get("/ch/01/eq/3/g") != snap.bands["/ch/01/eq/3"].g

    # 3. Rollback khôi phục về snapshot ban đầu
    report = manager.rollback(snap)

    assert report.success is True
    assert report.partial_failure is False
    assert report.duration_s < 1.0  # Yêu cầu hoàn tất dưới 1.0 giây
    assert report.restored_count == len(snap.bands)

    # Xác minh giá trị trong cache đã được khôi phục chính xác
    assert client._params_cache.get("/ch/01/eq/3/g") == snap.bands["/ch/01/eq/3"].g


def test_snapshot_serialization_roundtrip(tmp_path) -> None:
    """Kiểm tra xuất và nạp file snapshot JSON."""
    client = XAirClient(ip="127.0.0.1", port=10024)
    manager = SnapshotManager(client)

    # Đưa một số giá trị giả vào cache
    client._params_cache["/ch/01/eq/3/f"] = 0.65
    client._params_cache["/ch/01/eq/3/g"] = 0.40
    client._params_cache["/ch/01/eq/3/q"] = 0.80
    client._params_cache["/ch/01/eq/3/on"] = 1

    snap = manager.take_snapshot(channels=[1], buses=[], include_main=False)
    json_file = tmp_path / "test_snapshot.json"
    snap.save_file(json_file)

    loaded_snap = PEQSnapshot.load_file(json_file)
    assert loaded_snap.timestamp == snap.timestamp
    assert loaded_snap.bands["/ch/01/eq/3"].f == 0.65
    assert loaded_snap.bands["/ch/01/eq/3"].g == 0.40
