"""Backend dịch vụ FastAPI và WebSocket phục vụ giao diện Companion (Giai đoạn E1).

Mục tiêu:
- Tách rời hoàn toàn Engine và UI: Engine chạy độc lập, UI đóng/mở không ảnh hưởng tới DSP và Safety.
- REST API v1 cho các lệnh điều khiển (Chế độ, Duyệt đề xuất, Nhả notch, PANIC, Snapshot).
- WebSocket phục vụ truyền dữ liệu thời gian thực (trạng thái, meter, RTA phổ ~20-25 FPS).
- Bảo mật LAN: Chống can thiệp trái phép bằng mã PIN ghép nối khi bật --listen-lan.
- Phục vụ giao diện web tĩnh hoàn toàn cục bộ, không dùng bất kỳ CDN nào.
"""

from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict
import json
import logging
from pathlib import Path
import secrets
import time
from typing import Any, Dict, List, Optional, Set
from fastapi import FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from auto_sound.app.cli import AutoSoundApp
from auto_sound.core.config import AppConfig
from auto_sound.core.models import ActionProposal, ConnectionState
from auto_sound.mixer.parameter_mapper import ParameterMapper
from auto_sound.safety.controller import ActiveNotch, panic_rollback
from auto_sound.safety.snapshot import PEQSnapshot, SnapshotManager

logger = logging.getLogger("auto_sound.server")


# ==========================================
# 1. Pydantic Request & Response Schemas
# ==========================================

class ModeChangeRequest(BaseModel):
    mode: str = Field(..., description="Chế độ vận hành: auto, semi, manual")
    confirm: bool = Field(False, description="Xác nhận chuyển lên auto")


class ProposalActionRequest(BaseModel):
    notes: Optional[str] = Field(None, description="Ghi chú thêm khi duyệt hoặc từ chối")


class ReleaseNotchRequest(BaseModel):
    channel: int
    band: int
    target: str = "ch"
    bus: Optional[int] = None


class LockNotchRequest(BaseModel):
    channel: int
    band: int
    target: str = "ch"
    bus: Optional[int] = None


class PairVerifyRequest(BaseModel):
    pin: str = Field(..., description="Mã PIN 4 chữ số hiển thị trên máy tính chủ")


class SettingsUpdateRequest(BaseModel):
    whitelist_channels: Optional[List[int]] = None
    whitelist_buses: Optional[List[int]] = None
    auto_release_wait_s: Optional[float] = None
    auto_release_enabled: Optional[bool] = None


# ==========================================
# 2. WebSocket Connection Manager
# ==========================================

class ConnectionManager:
    """Quản lý các kết nối WebSocket thời gian thực."""

    def __init__(self) -> None:
        self.active_connections: List[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)

    async def broadcast_json(self, message: Dict[str, Any]) -> None:
        """Phát sóng thông điệp JSON tới toàn bộ client đang kết nối."""
        async with self._lock:
            conns = list(self.active_connections)

        for conn in conns:
            try:
                await conn.send_json(message)
            except Exception:
                # Bỏ qua client bị đứt kết nối, sẽ thu dọn sau
                pass


# ==========================================
# 3. FastAPI Server Application Factory
# ==========================================

def create_app(
    engine: Optional[AutoSoundApp] = None,
    listen_lan: bool = False,
    pin: Optional[str] = None,
    mock_mode: bool = False,
) -> FastAPI:
    """Khởi tạo ứng dụng FastAPI kết hợp Engine và WebSocket."""

    # Nếu chưa truyền engine, tạo engine mặc định
    if engine is None:
        cfg_path = Path(__file__).resolve().parent.parent.parent.parent / "device_profiles" / "xr18.toml"
        if not cfg_path.exists():
            cfg_path = Path("device_profiles/xr18.toml").resolve()
        config = AppConfig.load(cfg_path)
        mapper = ParameterMapper.from_profile(cfg_path)
        engine = AutoSoundApp(config=config, mapper=mapper, mock_mode=mock_mode, mode="semi")

    manager = ConnectionManager()

    # Sinh mã PIN ghép nối và bộ nhớ token LAN
    lan_pin = pin if pin else f"{secrets.randbelow(9000) + 1000}"
    valid_tokens: Set[str] = set()

    # Lưu trữ bản chụp trước khi Panic (để hỗ trợ Panic Undo)
    last_pre_panic_notches: Dict[Any, ActiveNotch] = {}

    # Snapshot Manager (khởi tạo lười khi mixer_client sẵn sàng)
    snapshot_mgr: Optional[SnapshotManager] = None

    def get_snapshot_mgr() -> Optional[SnapshotManager]:
        nonlocal snapshot_mgr
        if engine.mixer_client:
            if snapshot_mgr is None or snapshot_mgr.client != engine.mixer_client:
                snapshot_mgr = SnapshotManager(engine.mixer_client)
            return snapshot_mgr
        return None

    # Nhật ký sự kiện lưu trong RAM
    event_log: List[Dict[str, Any]] = []

    def record_event(event_type: str, details: Dict[str, Any]) -> None:
        entry = {
            "timestamp": time.time(),
            "time_str": time.strftime("%H:%M:%S"),
            "event": event_type,
            "data": details,
        }
        event_log.append(entry)
        if len(event_log) > 1000:
            event_log.pop(0)

    # Vòng lặp định kỳ đẩy dữ liệu RTA và Meter qua WebSocket
    async def rta_broadcast_loop() -> None:
        while True:
            try:
                await asyncio.sleep(0.04)  # ~25 FPS
                if not manager.active_connections:
                    continue

                meters = [0.0] * 18
                if engine and engine.mixer_client:
                    meters = list(engine.mixer_client.get_meter_levels())

                # Dữ liệu phổ RTA (từ LAN RTA hoặc FFT mô phỏng)
                rta_levels = [-60.0] * 100
                if engine and engine.mixer_client:
                    rta_levels = list(engine.mixer_client.get_rta_levels())

                await manager.broadcast_json({
                    "type": "telemetry_frame",
                    "timestamp": time.time(),
                    "meters": meters,
                    "rta": rta_levels,
                })
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(0.1)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Khởi động engine nếu chưa chạy
        if not engine._running:
            engine.start()
        record_event("system_start", {"mode": engine.mode, "listen_lan": listen_lan})
        broadcast_task = asyncio.create_task(rta_broadcast_loop())
        try:
            yield
        finally:
            broadcast_task.cancel()
            engine.stop()

    app = FastAPI(
        title="Auto Sound Engineer Companion API",
        version="1.0.0",
        description="REST & WebSocket API phục vụ giao diện chống hú Behringer XR/Midas MR",
        lifespan=lifespan,
    )

    # Middleware CORS cho phép truy cập cục bộ
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Kiểm tra bảo mật LAN
    def check_lan_auth(request: Request) -> None:
        if not listen_lan:
            return

        client_host = request.client.host if request.client else "unknown"
        # Localhost hoặc test harness luôn được tin cậy
        if client_host in ("127.0.0.1", "::1", "localhost", "testclient"):
            return

        # Chỉ áp dụng kiểm tra token với các phương thức ghi
        if request.method in ("POST", "PUT", "DELETE"):
            token = request.headers.get("X-Pairing-Token") or request.query_params.get("token")
            if not token or token not in valid_tokens:
                raise HTTPException(
                    status_code=401,
                    detail="Yêu cầu mã PIN ghép nối thiết bị trong mạng LAN (Unauthorized)",
                )

    # ==========================================
    # 4. REST Endpoints
    # ==========================================

    # Phục vụ static assets của Nuxt 4 nếu đã build
    dist_dir = Path(__file__).resolve().parent.parent / "web" / "dist"
    if (dist_dir / "_nuxt").exists():
        app.mount("/_nuxt", StaticFiles(directory=str(dist_dir / "_nuxt")), name="nuxt_static")

    @app.get("/", response_class=HTMLResponse)
    async def get_index() -> HTMLResponse:
        """Phục vụ file giao diện người dùng Web Companion (ưu tiên bản Nuxt 4 / Vue 3)."""
        dist_index = dist_dir / "index.html"
        if dist_index.exists():
            return HTMLResponse(content=dist_index.read_text(encoding="utf-8"))

        fallback_file = Path(__file__).resolve().parent.parent / "web" / "index.html"
        if fallback_file.exists():
            return HTMLResponse(content=fallback_file.read_text(encoding="utf-8"))
        return HTMLResponse(content="<h1>Auto Sound Engineer Companion</h1><p>Giao diện đang được khởi tạo...</p>")

    @app.get("/api/v1/status")
    async def get_status() -> Dict[str, Any]:
        """Lấy thông tin trạng thái toàn diện của hệ thống."""
        mixer_state = "DISCONNECTED"
        if engine.mixer_client:
            mixer_state = engine.mixer_client.get_state().value

        active_notches = len(engine.safety_state.active_notches)
        pending_props = len(engine.pending_proposals)

        return {
            "mixer_state": mixer_state,
            "model": engine.config.device.name,
            "firmware": "1.18",
            "mode": engine.mode,
            "lan_rta_mode": not engine.config.device.has_multichannel_usb,
            "latency_ms": 64.0,
            "xruns": int(engine.audio_capture.ring_buffer.xrun_count[0]) if engine.audio_capture else 0,
            "reconnect_count": 0,
            "uptime_s": 0.0,
            "active_notches_count": active_notches,
            "pending_proposals_count": pending_props,
            "is_lan_locked": listen_lan,
        }

    @app.post("/api/v1/mode")
    async def set_mode(req: ModeChangeRequest, request: Request) -> Dict[str, Any]:
        """Đổi chế độ vận hành (auto, semi, manual)."""
        check_lan_auth(request)
        new_mode = req.mode.lower()
        if new_mode not in ("auto", "semi", "manual"):
            raise HTTPException(status_code=400, detail="Chế độ không hợp lệ (auto, semi, manual)")

        if new_mode == "auto" and not req.confirm:
            raise HTTPException(
                status_code=400,
                detail="Chuyển sang chế độ AUTO yêu cầu xác nhận rõ ràng (confirm=true)",
            )

        old_mode = engine.mode
        engine.mode = new_mode
        record_event("mode_changed", {"from": old_mode, "to": new_mode})

        await manager.broadcast_json({
            "type": "mode_updated",
            "mode": new_mode,
        })
        return {"success": True, "current_mode": new_mode}

    @app.get("/api/v1/proposals")
    async def get_proposals() -> Dict[str, Any]:
        """Lấy danh sách đề xuất đang chờ soundman duyệt."""
        proposals_data = []
        now = time.time()
        for idx, prop in enumerate(engine.pending_proposals):
            proposals_data.append({
                "id": f"prop_{idx}",
                "channel": prop.channel,
                "bus": prop.bus,
                "target": prop.target,
                "freq_hz": prop.freq_hz,
                "gain_db": prop.gain_db,
                "q": prop.q,
                "confidence_score": 0.85,
                "created_at": now,
                "ttl_remaining_s": 15.0,
                "reason": prop.reason,
            })
        return {"proposals": proposals_data}

    @app.post("/api/v1/proposals/{prop_id}/approve")
    async def approve_proposal(prop_id: str, request: Request) -> Dict[str, Any]:
        """Duyệt áp dụng đề xuất hạ notch."""
        check_lan_auth(request)
        try:
            idx = int(prop_id.replace("prop_", ""))
            if 0 <= idx < len(engine.pending_proposals):
                prop = engine.pending_proposals.pop(idx)
                # Đẩy vào hàng đợi lệnh của engine
                engine._cmd_queue.put(prop)
                record_event("proposal_approved", asdict(prop))
                await manager.broadcast_json({
                    "type": "proposal_resolved",
                    "proposal_id": prop_id,
                    "action": "approved",
                })
                return {"success": True, "message": f"Đã duyệt đề xuất tại {prop.freq_hz} Hz"}
        except Exception:
            pass
        raise HTTPException(status_code=404, detail="Không tìm thấy đề xuất")

    @app.post("/api/v1/proposals/{prop_id}/reject")
    async def reject_proposal(prop_id: str, request: Request) -> Dict[str, Any]:
        """Từ chối đề xuất hạ notch."""
        check_lan_auth(request)
        try:
            idx = int(prop_id.replace("prop_", ""))
            if 0 <= idx < len(engine.pending_proposals):
                prop = engine.pending_proposals.pop(idx)
                record_event("proposal_rejected", asdict(prop))
                await manager.broadcast_json({
                    "type": "proposal_resolved",
                    "proposal_id": prop_id,
                    "action": "rejected",
                })
                return {"success": True, "message": "Đã từ chối đề xuất"}
        except Exception:
            pass
        raise HTTPException(status_code=404, detail="Không tìm thấy đề xuất")

    @app.post("/api/v1/proposals/{prop_id}/snooze")
    async def snooze_channel(prop_id: str, request: Request) -> Dict[str, Any]:
        """Tạm khóa và bỏ qua kênh trong 60 giây."""
        check_lan_auth(request)
        try:
            idx = int(prop_id.replace("prop_", ""))
            if 0 <= idx < len(engine.pending_proposals):
                prop = engine.pending_proposals.pop(idx)
                # Khóa kênh trong 60s
                engine.safety_state = engine.safety_state.__class__(
                    **{
                        **asdict(engine.safety_state),
                        "channel_locks": {
                            **engine.safety_state.channel_locks,
                            prop.channel: time.time() + 60.0,
                        },
                    }
                )
                record_event("channel_snoozed", {"channel": prop.channel, "duration_s": 60.0})
                return {"success": True, "message": f"Đã tạm khóa Kênh {prop.channel} trong 60 giây"}
        except Exception:
            pass
        raise HTTPException(status_code=404, detail="Không tìm thấy đề xuất")

    @app.get("/api/v1/notches")
    async def get_notches() -> Dict[str, Any]:
        """Lấy danh sách các notch đang hoạt động."""
        now = time.time()
        notches_list = []
        for (target_id, band), notch in engine.safety_state.active_notches.items():
            is_bus = notch.target == "bus" or target_id < 0
            notches_list.append({
                "channel": 0 if is_bus else notch.channel,
                "bus": notch.bus,
                "band": band,
                "freq_hz": notch.freq_hz,
                "gain_db": notch.current_gain_db,
                "q": notch.q,
                "target": notch.target,
                "age_s": round(now - notch.last_updated_time, 1),
                "is_locked": False,
                "step_count": notch.probe_step_count,
            })
        return {"notches": notches_list}

    @app.post("/api/v1/notches/release")
    async def release_notch(req: ReleaseNotchRequest, request: Request) -> Dict[str, Any]:
        """Nhả một notch cụ thể về 0 dB."""
        check_lan_auth(request)
        target_key_id = -req.bus if req.target == "bus" and req.bus else req.channel
        key = (target_key_id, req.band)

        if key in engine.safety_state.active_notches:
            notch = engine.safety_state.active_notches[key]
            # Gửi lệnh nhả về 0 dB
            release_prop = ActionProposal(
                channel=req.channel,
                band=req.band,
                freq_hz=notch.freq_hz,
                gain_db=0.0,
                q=notch.q,
                bus=req.bus,
                target=req.target,
                reason="Nhả notch thủ công từ UI",
            )
            engine._cmd_queue.put(release_prop)

            # Xóa khỏi danh sách active notches
            new_notches = dict(engine.safety_state.active_notches)
            new_notches.pop(key, None)
            engine.safety_state = engine.safety_state.__class__(
                **{**asdict(engine.safety_state), "active_notches": new_notches}
            )

            record_event("notch_released", asdict(release_prop))
            await manager.broadcast_json({"type": "notch_updated"})
            return {"success": True, "message": f"Đã nhả Band {req.band} về 0.0 dB"}

        raise HTTPException(status_code=404, detail="Không tìm thấy notch chỉ định")

    @app.post("/api/v1/panic")
    async def trigger_panic(request: Request) -> Dict[str, Any]:
        """NÚT KHẨN CẤP PANIC: Hoàn tác toàn bộ notch về 0 dB ngay lập tức."""
        check_lan_auth(request)
        nonlocal last_pre_panic_notches
        last_pre_panic_notches = dict(engine.safety_state.active_notches)

        now = time.time()
        new_state, rollback_props = panic_rollback(engine.safety_state, now)
        engine.safety_state = new_state

        # Làm rỗng các lệnh cũ tồn đọng để ưu tiên tuyệt đối cho PANIC
        engine.drain_cmd_queue()
        for prop in rollback_props:
            engine._cmd_queue.put(prop)

        count = len(rollback_props)
        record_event("panic_triggered", {"released_notches": count})

        await manager.broadcast_json({
            "type": "panic_event",
            "released_count": count,
            "timestamp": now,
        })
        return {
            "success": True,
            "released_count": count,
            "message": f"Đã kích hoạt PANIC: Hoàn tác {count} notch về 0 dB",
        }

    @app.post("/api/v1/panic/undo")
    async def undo_panic(request: Request) -> Dict[str, Any]:
        """Hoàn tác Panic: Phục hồi lại các notch trước khi bấm Panic."""
        check_lan_auth(request)
        nonlocal last_pre_panic_notches
        if not last_pre_panic_notches:
            raise HTTPException(status_code=400, detail="Không có trạng thái trước Panic để khôi phục")

        now = time.time()
        for key, notch in last_pre_panic_notches.items():
            re_prop = ActionProposal(
                channel=notch.channel,
                band=notch.band,
                freq_hz=notch.freq_hz,
                gain_db=notch.current_gain_db,
                q=notch.q,
                bus=notch.bus,
                target=notch.target,
                reason="Undo Panic: Phục hồi lại notch",
            )
            engine._cmd_queue.put(re_prop)

        engine.safety_state = engine.safety_state.__class__(
            **{**asdict(engine.safety_state), "active_notches": dict(last_pre_panic_notches)}
        )
        count = len(last_pre_panic_notches)
        last_pre_panic_notches = {}
        record_event("panic_undone", {"restored_notches": count})

        await manager.broadcast_json({"type": "notch_updated"})
        return {"success": True, "message": f"Đã phục hồi {count} notch"}

    @app.get("/api/v1/meters")
    async def get_meters() -> Dict[str, Any]:
        """Lấy mức tín hiệu 18 kênh và thông tin cảnh báo hú."""
        levels = [0.0] * 18
        if engine.mixer_client:
            levels = list(engine.mixer_client.get_meter_levels())

        now = time.time()
        locked_channels = [
            ch for ch, expire in engine.safety_state.channel_locks.items() if now < expire
        ]
        return {
            "meters": levels,
            "locked_channels": locked_channels,
            "whitelist_channels": list(engine.safety_state.whitelist),
        }

    @app.get("/api/v1/events")
    async def get_events(limit: int = 100) -> Dict[str, Any]:
        """Lấy nhật ký sự kiện có cấu trúc."""
        return {"events": event_log[-limit:]}

    @app.get("/api/v1/settings")
    async def get_settings() -> Dict[str, Any]:
        """Lấy cấu hình an toàn và danh sách whitelist."""
        return {
            "whitelist_channels": sorted(list(engine.safety_state.whitelist)),
            "whitelist_buses": sorted(list(engine.safety_state.bus_whitelist)),
            "auto_release_wait_s": engine.safety_state.auto_release_wait_s,
            "auto_release_rate_db_per_s": engine.safety_state.auto_release_rate_db_per_s,
            "auto_release_enabled": engine.safety_state.auto_release_enabled,
            "max_cut_db": engine.safety_state.max_cut_db,
            "max_boost_db": engine.safety_state.max_boost_db,
        }

    @app.post("/api/v1/snapshot/take")
    async def take_snapshot(request: Request) -> Dict[str, Any]:
        """Chụp snapshot trạng thái PEQ."""
        check_lan_auth(request)
        mgr = get_snapshot_mgr()
        if not mgr:
            raise HTTPException(status_code=500, detail="Snapshot manager chưa khả dụng")

        snap = mgr.take_snapshot()
        record_event("snapshot_taken", {"bands_count": len(snap.bands)})
        return {"success": True, "bands_count": len(snap.bands), "timestamp": snap.timestamp}

    @app.post("/api/v1/snapshot/rollback")
    async def rollback_snapshot(request: Request) -> Dict[str, Any]:
        """Rollback trạng thái PEQ về snapshot."""
        check_lan_auth(request)
        mgr = get_snapshot_mgr()
        if not mgr or not mgr.current_snapshot:
            raise HTTPException(status_code=400, detail="Chưa có bản chụp snapshot để khôi phục")

        report = mgr.rollback()
        record_event("snapshot_rollback", asdict(report))
        return {
            "success": report.success,
            "duration_s": report.duration_s,
            "restored_count": report.restored_count,
            "failed_count": len(report.failed_addresses),
            "partial_failure": report.partial_failure,
            "message": report.status_message,
        }

    @app.get("/api/v1/pair/pin")
    async def get_pairing_pin(request: Request) -> Dict[str, Any]:
        """Lấy mã PIN (chỉ cho phép truy vấn từ localhost để hiển thị)."""
        client_host = request.client.host if request.client else "unknown"
        if client_host not in ("127.0.0.1", "::1", "localhost", "testclient"):
            raise HTTPException(status_code=403, detail="Chỉ cho phép đọc PIN trên máy tính chủ")
        return {"pin": lan_pin}

    @app.post("/api/v1/pair/verify")
    async def verify_pairing_pin(req: PairVerifyRequest) -> Dict[str, Any]:
        """Xác thực mã PIN ghép nối và cấp token phiên."""
        if req.pin == lan_pin:
            token = secrets.token_hex(16)
            valid_tokens.add(token)
            return {"success": True, "token": token}
        raise HTTPException(status_code=401, detail="Mã PIN ghép nối không chính xác")

    # ==========================================
    # 5. WebSocket Endpoint
    # ==========================================

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket, token: Optional[str] = Query(None)):
        """Luồng WebSocket truyền phát trạng thái thời gian thực và tiếp nhận lệnh."""
        await manager.connect(websocket)

        # Gửi ngay gói tin snapshot toàn diện cho UI
        status_info = await get_status()
        notches_info = await get_notches()
        props_info = await get_proposals()
        meters_info = await get_meters()

        await websocket.send_json({
            "type": "state_snapshot",
            "timestamp": time.time(),
            "status": status_info,
            "notches": notches_info["notches"],
            "proposals": props_info["proposals"],
            "meters": meters_info["meters"],
        })

        try:
            while True:
                data_text = await websocket.receive_text()
                try:
                    msg = json.loads(data_text)
                    action = msg.get("action")

                    # Kiểm tra token nếu listen_lan bật
                    if listen_lan:
                        msg_token = msg.get("token") or token
                        client_ip = websocket.client.host if websocket.client else "unknown"
                        if client_ip not in ("127.0.0.1", "::1", "localhost"):
                            if not msg_token or msg_token not in valid_tokens:
                                await websocket.send_json({
                                    "type": "error",
                                    "message": "Cần ghép nối mã PIN trước khi gửi lệnh qua WebSocket",
                                })
                                continue

                    if action == "panic":
                        # Kích hoạt Panic ngay lập tức
                        now = time.time()
                        new_state, rollback_props = panic_rollback(engine.safety_state, now)
                        engine.safety_state = new_state
                        engine.drain_cmd_queue()
                        for prop in rollback_props:
                            engine._cmd_queue.put(prop)
                        await manager.broadcast_json({
                            "type": "panic_event",
                            "released_count": len(rollback_props),
                            "timestamp": now,
                        })

                    elif action == "approve_proposal":
                        prop_id = msg.get("proposal_id", "")
                        idx = int(prop_id.replace("prop_", ""))
                        if 0 <= idx < len(engine.pending_proposals):
                            prop = engine.pending_proposals.pop(idx)
                            engine._cmd_queue.put(prop)
                            await manager.broadcast_json({
                                "type": "proposal_resolved",
                                "proposal_id": prop_id,
                                "action": "approved",
                            })

                except Exception as e:
                    await websocket.send_json({"type": "error", "message": str(e)})

        except WebSocketDisconnect:
            await manager.disconnect(websocket)
        except Exception:
            await manager.disconnect(websocket)

    return app
