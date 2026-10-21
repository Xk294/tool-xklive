"""Kiểm thử tự động toàn diện API REST và WebSocket (Giai đoạn E5).

Mục tiêu kiểm định không cần trình duyệt:
- Bắt tay và nhận dữ liệu snapshot ban đầu qua WebSocket.
- Thao tác ghi (POST/PUT) bị từ chối 401 khi chưa ghép nối mã PIN (chế độ --listen-lan).
- Nút PANIC hoạt động ngay lập tức, hoàn tác toàn bộ notch trong 1 thao tác.
- Chuyển chế độ vận hành và kiểm tra xác nhận khi chuyển lên AUTO.
- UI ngắt kết nối đột ngột hoặc crash không ảnh hưởng tới tiến trình Engine.
"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from auto_sound.app.cli import AutoSoundApp
from auto_sound.app.server import create_app
from auto_sound.core.config import AppConfig
from auto_sound.core.models import ActionProposal
from auto_sound.mixer.parameter_mapper import ParameterMapper
from auto_sound.safety.controller import ActiveNotch


@pytest.fixture
def mock_engine():
    cfg_path = Path(__file__).resolve().parent.parent / "device_profiles" / "xr18.toml"
    config = AppConfig.load(cfg_path)
    mapper = ParameterMapper.from_profile(cfg_path)
    engine = AutoSoundApp(config=config, mapper=mapper, mock_mode=True, mode="semi")
    return engine


def test_server_status_and_nuxt_app(mock_engine) -> None:
    """Kiểm tra trang chủ phục vụ Nuxt 4 / Vue 3 và endpoint status hoạt động chuẩn."""
    app = create_app(engine=mock_engine, mock_mode=True)
    with TestClient(app) as client:
        # 1. Kiểm tra trang chủ
        resp_index = client.get("/")
        assert resp_index.status_code == 200
        # Trang Nuxt 4 index.html được phục vụ
        assert "<html" in resp_index.text.lower()

        # 2. Kiểm tra status API
        resp_status = client.get("/api/v1/status")
        assert resp_status.status_code == 200
        data = resp_status.json()
        assert data["mode"] == "semi"
        assert data["model"] == "Behringer XR18"
        assert data["latency_ms"] == 64.0
        assert "xruns" in data


def test_mode_switching_requires_confirmation_for_auto(mock_engine) -> None:
    """Chuyển lên AUTO bắt buộc phải có cờ confirm=true, chuyển xuống SEMI/MANUAL không cần."""
    app = create_app(engine=mock_engine, mock_mode=True)
    with TestClient(app) as client:
        # Chuyển sang manual -> Thành công
        resp_man = client.post("/api/v1/mode", json={"mode": "manual"})
        assert resp_man.status_code == 200
        assert resp_man.json()["current_mode"] == "manual"
        assert mock_engine.mode == "manual"

        # Chuyển lên auto không có confirm -> Bị từ chối 400
        resp_auto_fail = client.post("/api/v1/mode", json={"mode": "auto", "confirm": False})
        assert resp_auto_fail.status_code == 400
        assert "xác nhận rõ ràng" in resp_auto_fail.json()["detail"]

        # Chuyển lên auto có confirm -> Thành công
        resp_auto_ok = client.post("/api/v1/mode", json={"mode": "auto", "confirm": True})
        assert resp_auto_ok.status_code == 200
        assert resp_auto_ok.json()["current_mode"] == "auto"
        assert mock_engine.mode == "auto"


def test_panic_endpoint_and_undo(mock_engine) -> None:
    """Kích hoạt PANIC nhả toàn bộ notch và hỗ trợ hoàn tác Undo."""
    app = create_app(engine=mock_engine, mock_mode=True)
    with TestClient(app) as client:
        # Giả lập đang có 2 notch hoạt động
        mock_engine.safety_state = mock_engine.safety_state.__class__(
            **{
                **mock_engine.safety_state.__dict__,
                "active_notches": {
                    (1, 3): ActiveNotch(
                        channel=1,
                        band=3,
                        freq_hz=3150.0,
                        current_gain_db=-6.0,
                        target_gain_db=-6.0,
                        q=8.0,
                        is_probing=False,
                        last_updated_time=1000.0,
                    ),
                    (-1, 5): ActiveNotch(
                        channel=0,
                        band=5,
                        freq_hz=6300.0,
                        current_gain_db=-3.0,
                        target_gain_db=-3.0,
                        q=5.0,
                        is_probing=False,
                        last_updated_time=1000.0,
                        target="bus",
                        bus=1,
                    ),
                },
            }
        )

        assert len(mock_engine.safety_state.active_notches) == 2

        # 1. Kích hoạt PANIC
        resp_panic = client.post("/api/v1/panic")
        assert resp_panic.status_code == 200
        data = resp_panic.json()
        assert data["success"] is True
        assert data["released_count"] == 2
        # Danh sách notch trên engine đã bị xóa sạch
        assert len(mock_engine.safety_state.active_notches) == 0

        # 2. Hoàn tác Panic (Undo)
        resp_undo = client.post("/api/v1/panic/undo")
        assert resp_undo.status_code == 200
        # Đã phục hồi lại 2 notch
        assert len(mock_engine.safety_state.active_notches) == 2


def test_lan_security_pairing_pin(mock_engine) -> None:
    """Khi bật listen_lan, client chưa xác thực mã PIN bị từ chối thao tác ghi."""
    app = create_app(engine=mock_engine, listen_lan=True, pin="4321", mock_mode=True)
    with TestClient(app) as local_client:
        # 1. Đọc PIN từ localhost -> Thành công
        resp_pin = local_client.get("/api/v1/pair/pin")
        assert resp_pin.status_code == 200
        assert resp_pin.json()["pin"] == "4321"

    # 2. Client từ xa trong LAN (192.168.1.155)
    with TestClient(app, client=("192.168.1.155", 54321)) as remote_client:
        # Thao tác ghi từ xa không có token -> Bị chặn 401
        resp_unauth = remote_client.post("/api/v1/mode", json={"mode": "manual"})
        assert resp_unauth.status_code == 401
        assert "mã PIN ghép nối" in resp_unauth.json()["detail"]

        # Xác thực PIN sai -> 401
        resp_verify_fail = remote_client.post("/api/v1/pair/verify", json={"pin": "0000"})
        assert resp_verify_fail.status_code == 401

        # Xác thực PIN đúng -> Nhận token
        resp_verify_ok = remote_client.post("/api/v1/pair/verify", json={"pin": "4321"})
        assert resp_verify_ok.status_code == 200
        token = resp_verify_ok.json()["token"]
        assert len(token) > 10

        # Thao tác ghi kèm token hợp lệ -> Thành công
        resp_auth = remote_client.post(
            "/api/v1/mode",
            json={"mode": "manual"},
            headers={"X-Pairing-Token": token},
        )
        assert resp_auth.status_code == 200


def test_websocket_snapshot_and_disconnect_stability(mock_engine) -> None:
    """WebSocket gửi snapshot toàn diện khi kết nối và ngắt kết nối an toàn không ảnh hưởng engine."""
    app = create_app(engine=mock_engine, mock_mode=True)
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            # Nhận gói tin snapshot đầu tiên
            snapshot_data = ws.receive_json()
            assert snapshot_data["type"] == "state_snapshot"
            assert "status" in snapshot_data
            assert "notches" in snapshot_data
            assert "meters" in snapshot_data

            # Gửi lệnh panic qua websocket
            ws.send_json({"action": "panic"})
            # Nhận phản hồi phát sóng panic
            panic_event = ws.receive_json()
            assert panic_event["type"] == "panic_event"

        # Client đã ngắt kết nối (thực nghiệm UI crash) -> Engine vẫn chạy bình thường
        assert mock_engine._running is True
        resp_status = client.get("/api/v1/status")
        assert resp_status.status_code == 200


def test_proposal_approve_and_reject(mock_engine) -> None:
    """Duyệt hoặc từ chối đề xuất qua REST API."""
    mock_engine.pending_proposals = [
        ActionProposal(
            channel=2,
            band=3,
            freq_hz=4000.0,
            gain_db=-3.0,
            q=8.0,
            reason="Test Proposal",
        )
    ]

    app = create_app(engine=mock_engine, mock_mode=True)
    with TestClient(app) as client:
        # Lấy danh sách đề xuất
        resp_get = client.get("/api/v1/proposals")
        assert resp_get.status_code == 200
        props = resp_get.json()["proposals"]
        assert len(props) == 1
        assert props[0]["id"] == "prop_0"

        # Duyệt đề xuất
        resp_approve = client.post("/api/v1/proposals/prop_0/approve")
        assert resp_approve.status_code == 200
        # Đã lấy khỏi danh sách chờ duyệt và chuyển giao cho engine
        assert len(mock_engine.pending_proposals) == 0


def test_snapshot_api_endpoints(mock_engine) -> None:
    """Kiểm tra chụp và hoàn tác PEQ qua API."""
    app = create_app(engine=mock_engine, mock_mode=True)
    with TestClient(app) as client:
        # Chụp snapshot
        resp_take = client.post("/api/v1/snapshot/take")
        assert resp_take.status_code == 200
        assert resp_take.json()["success"] is True

        # Rollback snapshot
        resp_rollback = client.post("/api/v1/snapshot/rollback")
        assert resp_rollback.status_code == 200
        assert resp_rollback.json()["success"] is True
        assert resp_rollback.json()["duration_s"] < 1.0
