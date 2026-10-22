"""Kiểm thử tự động cho toàn bộ các tính năng mới và bản sửa lỗi Phần A, B, C:
- RTT ping và gia hạn RTA định kỳ (A2, A8)
- Demo Mode: Nút tạo hú giả và bộ sinh tín hiệu ảo (B1, B2)
- Diagnostics endpoint (C1)
- Shadow / Dry-run mode (C2)
- Ring-out Wizard (C3)
- Lịch sử notch, hoàn tác từng notch, xuất báo cáo CSV/JSON (C5)
- Kiểm tra USB Routing & Audio devices (C7)
- Gợi ý Dynamics / Compressor / Gate (C8)
- Thu mẫu âm thanh thật (C11)
- Driver trừu tượng Behringer X32 / Midas M32 (C12)
"""

from pathlib import Path
import time
import pytest
from fastapi.testclient import TestClient

from auto_sound.app.cli import AutoSoundApp
from auto_sound.app.server import create_app
from auto_sound.core.config import AppConfig
from auto_sound.core.models import ActionProposal
from auto_sound.mixer.fake import FakeXR18
from auto_sound.mixer.parameter_mapper import ParameterMapper
from auto_sound.mixer.x32 import X32Client
from auto_sound.mixer.xair import XAirClient


@pytest.fixture
def mock_system():
    fake = FakeXR18(host="127.0.0.1", port=0)
    fake.start()

    cfg_path = Path(__file__).resolve().parent.parent / "device_profiles" / "xr18.toml"
    config = AppConfig.load(cfg_path)
    config.network.default_mixer_ip = fake.host
    config.device.port = fake.port
    mapper = ParameterMapper.from_profile(cfg_path)

    engine = AutoSoundApp(config=config, mapper=mapper, mock_mode=True, mode="semi")
    engine.start()

    app = create_app(engine=engine, mock_mode=True)
    client = TestClient(app)

    yield fake, engine, client

    engine.stop()
    fake.stop()


def test_rtt_and_rta_renewal_mechanism(mock_system):
    """Kiểm tra đo RTT thật và cơ chế renew RTA / meters định kỳ."""
    fake, engine, _ = mock_system
    mixer = engine.mixer_client
    assert mixer is not None

    # Đo RTT qua ping()
    rtt = mixer.ping(timeout_s=0.5)
    assert rtt is not None
    assert rtt >= 0.0
    assert mixer.last_rtt_ms == rtt

    # Đăng ký meters và RTA
    mixer.subscribe_rta(enable=True)
    mixer.subscribe_meters(enable=True)
    assert mixer._rta_subscribed is True
    assert mixer._meters_subscribed is True
    assert mixer._last_rta_renew_time > 0
    assert mixer._last_meters_renew_time > 0


def test_diagnostics_endpoint(mock_system):
    """Kiểm tra API chẩn đoán kết nối chi tiết (Phần C1)."""
    _, _, client = mock_system
    resp = client.get("/api/v1/diagnostics")
    assert resp.status_code == 200
    data = resp.json()

    assert "mock_mode" in data
    assert "dry_run" in data
    assert "mixer_state" in data
    assert "rtt_ms" in data
    assert "rta_subscribed" in data
    assert "meters_subscribed" in data
    assert "audio_device" in data
    assert "sample_rate" in data
    assert "xruns" in data
    assert "osc_tx_count" in data
    assert "osc_rx_count" in data
    assert "uptime_s" in data


def test_dry_run_shadow_mode(mock_system):
    """Kiểm tra chế độ Shadow / Dry-run không gửi lệnh ghi xuống mixer (Phần C2)."""
    fake, engine, client = mock_system

    # Bật dry-run qua API
    resp_enable = client.post("/api/v1/dry_run", json={"dry_run": True})
    assert resp_enable.status_code == 200
    assert resp_enable.json()["dry_run"] is True
    assert engine.dry_run is True

    # Trạng thái ban đầu trên FakeXR18
    fake.params["/ch/01/eq/3/g"] = 0.5  # 0.0 dB

    # Thực thi proposal hạ notch
    prop = ActionProposal(channel=1, band=3, freq_hz=2500.0, gain_db=-6.0, q=8.0, target="ch")
    engine.execute_proposal(prop, async_send=False)

    # Trong dry-run: tham số trên fake mixer KHÔNG bị thay đổi
    assert fake.params["/ch/01/eq/3/g"] == 0.5

    # Tắt dry-run
    resp_disable = client.post("/api/v1/dry_run", json={"dry_run": False})
    assert resp_disable.status_code == 200
    assert engine.dry_run is False


def test_demo_fake_feedback_trigger(mock_system):
    """Kiểm tra nút bấm tạo tiếng hú giả trong chế độ Demo (Phần B2)."""
    fake, engine, client = mock_system

    resp = client.post(
        "/api/v1/demo/feedback",
        json={"channel": 2, "freq_hz": 3150.0, "duration_s": 2.0},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["channel"] == 2
    assert data["freq_hz"] == 3150.0

    # Kiểm tra fake mixer đã nhận bin hú giả
    target_mixer = engine.fake_mixer or fake
    assert target_mixer._fake_feedback_bin is not None or len(engine._active_fake_feedbacks) > 0


def test_ringout_wizard_start_and_stop(mock_system):
    """Kiểm tra chu trình Ring-out Wizard trước show (Phần C3)."""
    _, _, client = mock_system

    # Trạng thái ban đầu
    status_resp = client.get("/api/v1/wizard/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["running"] is False

    # Bắt đầu Wizard
    start_resp = client.post(
        "/api/v1/wizard/start",
        json={
            "target": "main",
            "channel": 1,
            "max_boost_db": 3.0,
            "step_db": 1.0,
            "step_interval_s": 0.2,
            "venue_name": "Phòng Trà XK",
        },
    )
    assert start_resp.status_code == 200
    assert start_resp.json()["state"]["running"] is True

    # Dừng khẩn cấp Wizard
    stop_resp = client.post("/api/v1/wizard/stop")
    assert stop_resp.status_code == 200
    assert stop_resp.json()["success"] is True

    # Kiểm tra trạng thái đã dừng và gain khôi phục
    status_after = client.get("/api/v1/wizard/status")
    assert status_after.json()["running"] is False
    assert status_after.json()["current_boost_db"] == 0.0


def test_notch_history_and_report_export(mock_system):
    """Kiểm tra lịch sử can thiệp, hoàn tác từng notch và xuất báo cáo (Phần C5)."""
    _, engine, client = mock_system

    # Ghi nhận một sự kiện notch vào history
    engine.log_event("notch_applied", {
        "channel": 2,
        "band": 3,
        "freq_hz": 2500.0,
        "gain_db": -6.0,
        "q": 8.0,
        "target": "ch",
        "reason": "Dò hú tự động",
    })

    # Lấy lịch sử notch
    hist_resp = client.get("/api/v1/notches/history")
    assert hist_resp.status_code == 200
    hist = hist_resp.json()["history"]
    assert len(hist) >= 1
    assert hist[-1]["action"] == "notch_applied"
    assert hist[-1]["freq_hz"] == 2500.0

    # Xuất báo cáo JSON
    json_rep = client.get("/api/v1/report/export?format=json")
    assert json_rep.status_code == 200
    assert "notch_history" in json_rep.json()

    # Xuất báo cáo CSV
    csv_rep = client.get("/api/v1/report/export?format=csv")
    assert csv_rep.status_code == 200
    assert "text/csv" in csv_rep.headers["content-type"]
    assert "Tần số (Hz)" in csv_rep.text


def test_audio_devices_and_routing_check(mock_system):
    """Kiểm tra API danh sách soundcard và kiểm tra routing USB (Phần C7)."""
    _, _, client = mock_system

    # Danh sách thiết bị âm thanh
    dev_resp = client.get("/api/v1/audio/devices")
    assert dev_resp.status_code == 200
    assert "devices" in dev_resp.json()

    # Kiểm tra USB routing
    route_resp = client.get("/api/v1/audio/routing-check")
    assert route_resp.status_code == 200
    assert route_resp.json()["ok"] is True
    assert route_resp.json()["sample_rate"] == 48000


def test_dynamics_suggestions(mock_system):
    """Kiểm tra phân tích mức tín hiệu và đưa ra gợi ý dynamics (Phần C8)."""
    _, _, client = mock_system
    resp = client.get("/api/v1/dynamics/suggestions")
    assert resp.status_code == 200
    data = resp.json()
    assert "suggestions" in data
    assert "count" in data


def test_audio_record_sample(mock_system, tmp_path):
    """Kiểm tra API thu mẫu âm thanh có nhãn (Phần C11)."""
    _, _, client = mock_system
    resp = client.post(
        "/api/v1/audio/record",
        json={"channel": 1, "duration_s": 0.5, "label": "feedback"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["label"] == "feedback"
    assert Path(data["path"]).exists()


def test_x32_driver_interface():
    """Kiểm tra lớp trừu tượng driver Behringer X32 / Midas M32 (Phần C12)."""
    client = X32Client(ip="127.0.0.1", port=10023)
    assert client.connect() is True
    assert client.total_channels == 32
    assert client.channel_bands_count == 6

    info = client.get_device_info()
    assert info["model"] == "X32"
    assert info["total_channels"] == 32

    # Ghi PEQ trên kênh 5 band 6
    ok = client.set_peq(channel=5, band=6, freq_hz=3500.0, gain_db=-4.5, q=5.0)
    assert ok is True

    band = client.get_peq(channel=5, band=6)
    assert band is not None
    assert band.freq_hz == 3500.0
    assert band.gain_db == -4.5
    client.disconnect()
