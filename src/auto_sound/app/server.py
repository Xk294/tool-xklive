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
from dataclasses import asdict, replace
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
from auto_sound.dsp.gain_staging import GainStagingManager
from auto_sound.dsp.talkover import TalkoverController, TalkoverConfig
from auto_sound.core.ringout import RingOutController, RingOutConfig

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


class FeedbackTriggerRequest(BaseModel):
    channel: int = Field(2, description="Kênh micro (1-16)")
    freq_hz: float = Field(2500.0, description="Tần số tiếng hú (Hz)")
    duration_s: float = Field(5.0, description="Thời lượng tiếng hú (giây)")


class DryRunChangeRequest(BaseModel):
    dry_run: Optional[bool] = Field(None, description="Bật/tắt chế độ Shadow / Dry-run")
    enabled: Optional[bool] = Field(None, description="Tương thích ngược alias")

    def get_dry_run(self) -> bool:
        if self.dry_run is not None:
            return self.dry_run
        if self.enabled is not None:
            return self.enabled
        return False


class WizardStartRequest(BaseModel):
    target: str = Field("main", description="Đích ring-out: 'main' hoặc 'ch'")
    channel: int = Field(1, description="Kênh nếu target là 'ch'")
    max_boost_db: float = Field(4.0, description="Giới hạn tăng gain an toàn (dB)")
    step_db: float = Field(1.0, description="Bước tăng gain mỗi nấc (dB)")
    step_interval_s: float = Field(1.5, description="Khoảng thời gian mỗi bước (giây)")
    dwell_time_s: Optional[float] = Field(None, description="Alias thời gian mỗi bước (giây)")
    venue_name: Optional[str] = Field("DefaultVenue", description="Tên phòng / địa điểm lưu profile")

    def get_interval(self) -> float:
        if self.dwell_time_s is not None:
            return self.dwell_time_s
        return self.step_interval_s


class AudioDeviceSelectRequest(BaseModel):
    device: Any = Field(..., description="Chỉ số hoặc tên thiết bị soundcard USB")


class AudioRecordRequest(BaseModel):
    channel: int = Field(1, description="Kênh micro cần thu")
    duration_s: float = Field(3.0, description="Thời lượng thu (giây)")
    label: str = Field("feedback", description="Nhãn: 'feedback' hoặc 'no_feedback'")


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
    dry_run: bool = False,
) -> FastAPI:
    """Khởi tạo ứng dụng FastAPI kết hợp Engine và WebSocket."""
    from auto_sound.core.logging_config import setup_file_logging
    setup_file_logging()

    # Nếu chưa truyền engine, tạo engine mặc định
    if engine is None:
        cfg_path = Path(__file__).resolve().parent.parent.parent.parent / "device_profiles" / "xr18.toml"
        if not cfg_path.exists():
            cfg_path = Path("device_profiles/xr18.toml").resolve()
        config = AppConfig.load(cfg_path)
        mapper = ParameterMapper.from_profile(cfg_path)
        engine = AutoSoundApp(config=config, mapper=mapper, mock_mode=mock_mode, mode="semi")

    if dry_run:
        engine.dry_run = True

    start_time = time.time()
    manager = ConnectionManager()

    # Sinh mã PIN ghép nối và bộ nhớ token LAN
    lan_pin = pin if pin else f"{secrets.randbelow(9000) + 1000}"
    valid_tokens: Set[str] = set()

    # Lưu trữ bản chụp trước khi Panic (để hỗ trợ Panic Undo)
    last_pre_panic_notches: Dict[Any, ActiveNotch] = {}

    # Lịch sử toàn bộ các notch đã từng can thiệp trong show
    notch_history: List[Dict[str, Any]] = []

    # Trạng thái Ring-out Wizard
    wizard_state: Dict[str, Any] = {
        "running": False,
        "target": "main",
        "channel": 1,
        "max_boost_db": 4.0,
        "step_db": 1.0,
        "current_boost_db": 0.0,
        "detected_notches": [],
        "venue_name": "DefaultVenue",
        "message": "Sẵn sàng",
    }
    wizard_task: Optional[asyncio.Task] = None

    # Gain Staging, Ring-Out & Talkover Manager V2
    gain_manager = GainStagingManager()
    talkover_controller = getattr(engine, "talkover_controller", None) or TalkoverController()
    ringout_controller = RingOutController()

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

        logger.info("EVENT [%s]: %s", event_type, details)

        # Lưu vào notch_history nếu là thao tác notch
        if event_type in ("notch_applied", "proposal_approved", "notch_released", "shadow_notch_simulated"):
            notch_history.append({
                "timestamp": entry["timestamp"],
                "time_str": entry["time_str"],
                "action": event_type,
                **details,
            })
            if len(notch_history) > 1000:
                notch_history.pop(0)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(manager.broadcast_json({
                "type": "log_event",
                "entry": entry,
            }))
        except RuntimeError:
            pass

    engine.on_log_event = record_event

    # Vòng lặp định kỳ đẩy dữ liệu RTA và Meter qua WebSocket
    async def rta_broadcast_loop() -> None:
        while True:
            try:
                await asyncio.sleep(0.04)  # ~25 FPS
                if not manager.active_connections:
                    continue

                meters: List[float]
                rta_levels: List[float]

                if engine and engine.mixer_client:
                    meters = list(engine.mixer_client.get_meter_levels())
                    rta_levels = list(engine.mixer_client.get_rta_levels())
                else:
                    # Không có mixer client → trả về silence, UI tự biết ở trạng thái Demo/Disconnected
                    meters = [0.0] * 18
                    rta_levels = [-80.0] * 100

                await manager.broadcast_json({
                    "type": "telemetry_frame",
                    "timestamp": time.time(),
                    "meters": meters,
                    "rta": rta_levels,
                    "mock_mode": mock_mode,
                })
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("rta_broadcast_loop error: %s", exc, exc_info=True)
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
        """Phục vụ giao diện Nuxt 4 / Vue 3 đã build (dist/index.html)."""
        dist_index = dist_dir / "index.html"
        if dist_index.exists():
            return HTMLResponse(content=dist_index.read_text(encoding="utf-8"))
        return HTMLResponse(content="<h1>Auto Sound Engineer Companion</h1><p>Chạy <code>cd frontend && npm run build</code> để build giao diện Nuxt.</p>")

    @app.get("/api/v1/status")
    async def get_status() -> Dict[str, Any]:
        """Lấy thông tin trạng thái toàn diện của hệ thống cùng thông tin nhận diện mixer thực tế."""
        client = engine.mixer_client
        dev_info = client.get_device_info() if client else {}

        if client:
            mixer_state = client.get_state().value
        elif mock_mode:
            mixer_state = "DEMO"
        else:
            mixer_state = "DISCONNECTED"

        # Firmware: chỉ hiển thị nếu có thật từ /xinfo; tránh hardcode gây nhầm lẫn
        firmware_raw = dev_info.get("firmware") if dev_info else None
        if firmware_raw and firmware_raw not in ("Unknown", ""):
            firmware_display = firmware_raw
        elif mock_mode:
            firmware_display = "SIM"
        else:
            firmware_display = None  # UI hiển thị "—"

        # RTT OSC: chỉ có khi mixer thật kết nối và đã đo; None → UI hiển thị "—"
        rtt_ms: Optional[float] = None
        if client and hasattr(client, "last_rtt_ms"):
            rtt_ms = client.last_rtt_ms

        # Độ trễ DSP lý thuyết (frame_size / sample_rate): cố định theo cấu hình DSP
        dsp_latency_ms: Optional[float] = None
        if engine.detector:
            dsp_latency_ms = round(engine.detector.frame_size / 48000 * 1000, 1)

        with engine._safety_lock:
            active_notches = len(engine.safety_state.active_notches)
        with engine._proposals_lock:
            pending_props = len(engine.pending_proposals)

        return {
            "mixer_state": mixer_state,
            "mock_mode": mock_mode,
            "model": engine.config.device.name,
            "hardware_model": dev_info.get("model") or engine.config.device.name,
            "mixer_name": dev_info.get("name") or ("Demo Mixer" if mock_mode else "—"),
            "firmware": firmware_display,
            "mixer_ip": dev_info.get("ip") or (None if not mock_mode else "127.0.0.1"),
            "mode": engine.mode,
            "lan_rta_mode": not engine.config.device.has_multichannel_usb,
            "rtt_ms": rtt_ms,
            "dsp_latency_ms": dsp_latency_ms,
            "latency_ms": dsp_latency_ms if dsp_latency_ms is not None else 64.0,
            "dry_run": getattr(engine, "dry_run", False),
            "xruns": int(engine.audio_capture.ring_buffer.xrun_count[0]) if engine.audio_capture else 0,
            "reconnect_count": 0,
            "uptime_s": round(time.time() - start_time, 1),
            "active_notches_count": active_notches,
            "pending_proposals_count": pending_props,
            "is_lan_locked": listen_lan,
            "firmware_reason": dev_info.get("firmware_reason"),
            "capabilities": asdict(client.get_capability_map()) if client and hasattr(client, "get_capability_map") else None,
        }

    @app.get("/api/v1/capabilities")
    async def get_capabilities() -> Dict[str, Any]:
        """Lấy CapabilityMap thực tế sau khi probe mixer."""
        client = engine.mixer_client
        if client and hasattr(client, "get_capability_map"):
            return asdict(client.get_capability_map())
        from auto_sound.core.models import CapabilityMap
        return asdict(CapabilityMap())

    @app.get("/api/v1/channels")
    async def get_channels() -> Dict[str, Any]:
        """Lấy danh sách kênh cùng tên hiển thị, màu sắc và trạng thái Mute trực tiếp từ X-Air."""
        channels_data = []
        client = engine.mixer_client
        meters = client.get_meter_levels() if client else [0.0] * 18
        now = time.time()
        with engine._safety_lock:
            channel_locks = dict(engine.safety_state.channel_locks)
            whitelist = set(engine.safety_state.whitelist)
        for ch in engine.config.channels.mic_channels:
            info = client.get_channel_info(ch) if client else {"name": f"CH {ch:02d}", "color": 0, "is_muted": False}
            is_locked = channel_locks.get(ch, 0.0) > now
            level = meters[ch - 1] if ch - 1 < len(meters) else 0.0
            channels_data.append({
                "channel": ch,
                "name": info["name"],
                "color": info["color"],
                "is_muted": info["is_muted"],
                "level": level,
                "is_locked": is_locked,
                "whitelisted": ch in whitelist,
            })
        return {"channels": channels_data}

    @app.get("/api/v1/mixer/discover")
    async def discover_mixers_api() -> Dict[str, Any]:
        """Quét mạng LAN tìm kiếm các mixer Behringer/Midas X-Air phản hồi trên UDP port 10024."""
        from auto_sound.mixer.xair import discover_mixers
        found = discover_mixers(timeout_s=0.8)
        return {"mixers": found, "count": len(found)}

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

    def _pop_proposal_by_id(prop_id: str) -> Optional[ActionProposal]:
        """Thread-safe lookup and removal of pending proposal by index or id."""
        with engine._proposals_lock:
            if prop_id.startswith("prop_"):
                raw_idx = prop_id[5:]
                if raw_idx.isdigit():
                    idx = int(raw_idx)
                    if 0 <= idx < len(engine.pending_proposals):
                        return engine.pending_proposals.pop(idx)
            return None

    def execute_panic() -> tuple[int, float]:
        """Atomically trigger panic rollback across safety state and queue."""
        nonlocal last_pre_panic_notches
        now = time.time()
        with engine._safety_lock:
            last_pre_panic_notches = dict(engine.safety_state.active_notches)
            new_state, rollback_props = panic_rollback(engine.safety_state, now)
            engine.safety_state = new_state
        engine.drain_cmd_queue()
        for prop in rollback_props:
            engine._cmd_queue.put(prop)
        return len(rollback_props), now

    @app.get("/api/v1/proposals")
    async def get_proposals() -> Dict[str, Any]:
        """Lấy danh sách đề xuất đang chờ soundman duyệt."""
        proposals_data = []
        now = time.time()
        with engine._proposals_lock:
            current_props = list(engine.pending_proposals)
        for idx, prop in enumerate(current_props):
            ch_name = engine.mixer_client.get_channel_name(prop.channel) if engine.mixer_client else f"CH {prop.channel:02d}"
            proposals_data.append({
                "id": f"prop_{idx}",
                "channel": prop.channel,
                "channel_name": ch_name,
                "bus": prop.bus,
                "target": prop.target,
                "freq_hz": prop.freq_hz,
                "gain_db": prop.gain_db,
                "q": prop.q,
                "confidence_score": 0.85,
                "created_at": now,
                "ttl_remaining_s": 15.0,
                "reason": prop.reason,
                "reason_code": "feedback_detected",
                "reason_params": {"freq_hz": round(prop.freq_hz, 1)},
            })
        return {"proposals": proposals_data}

    @app.post("/api/v1/proposals/{prop_id}/approve")
    async def approve_proposal(prop_id: str, request: Request) -> Dict[str, Any]:
        """Duyệt áp dụng đề xuất hạ notch."""
        check_lan_auth(request)
        prop = _pop_proposal_by_id(prop_id)
        if prop:
            engine._cmd_queue.put(prop)
            record_event("proposal_approved", asdict(prop))
            await manager.broadcast_json({
                "type": "proposal_resolved",
                "proposal_id": prop_id,
                "action": "approved",
            })
            return {
                "success": True,
                "message": f"Đã duyệt đề xuất tại {prop.freq_hz} Hz",
                "message_code": "proposal_approved",
                "params": {"freq_hz": prop.freq_hz},
            }
        raise HTTPException(status_code=404, detail="Không tìm thấy đề xuất")

    @app.post("/api/v1/proposals/{prop_id}/reject")
    async def reject_proposal(prop_id: str, request: Request) -> Dict[str, Any]:
        """Từ chối đề xuất hạ notch."""
        check_lan_auth(request)
        prop = _pop_proposal_by_id(prop_id)
        if prop:
            record_event("proposal_rejected", asdict(prop))
            await manager.broadcast_json({
                "type": "proposal_resolved",
                "proposal_id": prop_id,
                "action": "rejected",
            })
            return {
                "success": True,
                "message": "Đã từ chối đề xuất",
                "message_code": "proposal_rejected",
                "params": {},
            }
        raise HTTPException(status_code=404, detail="Không tìm thấy đề xuất")

    @app.post("/api/v1/proposals/{prop_id}/snooze")
    async def snooze_channel(prop_id: str, request: Request) -> Dict[str, Any]:
        """Tạm khóa và bỏ qua kênh trong 60 giây."""
        check_lan_auth(request)
        prop = _pop_proposal_by_id(prop_id)
        if prop:
            with engine._safety_lock:
                new_locks = dict(engine.safety_state.channel_locks)
                new_locks[prop.channel] = time.time() + 60.0
                engine.safety_state = replace(engine.safety_state, channel_locks=new_locks)
            record_event("channel_snoozed", {"channel": prop.channel, "duration_s": 60.0})
            return {
                "success": True,
                "message": f"Đã tạm khóa Kênh {prop.channel} trong 60 giây",
                "message_code": "channel_snoozed",
                "params": {"channel": prop.channel, "duration_s": 60},
            }
        raise HTTPException(status_code=404, detail="Không tìm thấy đề xuất")

    @app.get("/api/v1/notches")
    async def get_notches() -> Dict[str, Any]:
        """Lấy danh sách các notch đang hoạt động."""
        now = time.time()
        notches_list = []
        with engine._safety_lock:
            active_items = list(engine.safety_state.active_notches.items())
        for (target_id, band), notch in active_items:
            is_bus = notch.target == "bus" or target_id < 0
            ch_name = engine.mixer_client.get_channel_name(notch.channel) if (engine.mixer_client and not is_bus) else f"CH {notch.channel:02d}"
            notches_list.append({
                "channel": 0 if is_bus else notch.channel,
                "channel_name": ch_name,
                "bus": notch.bus,
                "band": band,
                "freq_hz": notch.freq_hz,
                "gain_db": notch.current_gain_db,
                "q": notch.q,
                "target": notch.target,
                "age_s": round(now - notch.last_updated_time, 1),
                "is_locked": False,
                "step_count": notch.probe_step_count,
                "status_code": "stepping" if notch.probe_step_count > 1 else "stable",
                "status_params": {"step": notch.probe_step_count},
            })
        return {"notches": notches_list}

    @app.post("/api/v1/notches/release")
    async def release_notch(req: ReleaseNotchRequest, request: Request) -> Dict[str, Any]:
        """Nhả một notch cụ thể về 0 dB."""
        check_lan_auth(request)
        target_key_id = -req.bus if req.target == "bus" and req.bus else req.channel
        key = (target_key_id, req.band)

        release_prop = None
        with engine._safety_lock:
            if key in engine.safety_state.active_notches:
                notch = engine.safety_state.active_notches[key]
                release_prop = ActionProposal(
                    channel=req.channel,
                    band=req.band,
                    freq_hz=notch.freq_hz,
                    gain_db=notch.original_gain_db,
                    q=notch.q,
                    bus=req.bus,
                    target=req.target,
                    reason=f"Nhả notch thủ công từ UI (khôi phục gốc {notch.original_gain_db:+.1f}dB)",
                    original_gain_db=notch.original_gain_db,
                )
                engine._cmd_queue.put(release_prop)

                new_notches = dict(engine.safety_state.active_notches)
                new_notches.pop(key, None)
                engine.safety_state = replace(engine.safety_state, active_notches=new_notches)

        if release_prop:
            record_event("notch_released", asdict(release_prop))
            await manager.broadcast_json({"type": "notch_updated"})
            return {
                "success": True,
                "message": f"Đã nhả Band {req.band} về 0.0 dB",
                "message_code": "notch_released",
                "params": {"band": req.band},
            }

        raise HTTPException(status_code=404, detail="Không tìm thấy notch chỉ định")

    @app.post("/api/v1/panic")
    async def trigger_panic(request: Request) -> Dict[str, Any]:
        """NÚT KHẨN CẤP PANIC: Hoàn tác toàn bộ notch về 0 dB ngay lập tức."""
        check_lan_auth(request)
        count, now = execute_panic()
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
            "message_code": "panic_triggered",
            "params": {"count": count},
        }

    @app.post("/api/v1/panic/undo")
    async def undo_panic(request: Request) -> Dict[str, Any]:
        """Hoàn tác Panic: Phục hồi lại các notch trước khi bấm Panic."""
        check_lan_auth(request)
        nonlocal last_pre_panic_notches
        if not last_pre_panic_notches:
            raise HTTPException(status_code=400, detail="Không có trạng thái trước Panic để khôi phục")

        with engine._safety_lock:
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

            engine.safety_state = replace(engine.safety_state, active_notches=dict(last_pre_panic_notches))
            count = len(last_pre_panic_notches)
            last_pre_panic_notches = {}

        record_event("panic_undone", {"restored_notches": count})
        await manager.broadcast_json({"type": "notch_updated"})
        return {
            "success": True,
            "restored_count": count,
            "message": f"Đã phục hồi {count} notch",
            "message_code": "panic_undone",
            "params": {"count": count},
        }


    @app.get("/api/v1/meters")
    async def get_meters() -> Dict[str, Any]:
        """Lấy mức tín hiệu 18 kênh và thông tin cảnh báo hú."""
        levels = [0.0] * 18
        if engine.mixer_client:
            levels = list(engine.mixer_client.get_meter_levels())

        now = time.time()
        with engine._safety_lock:
            locked_channels = [
                ch for ch, expire in engine.safety_state.channel_locks.items() if now < expire
            ]
            whitelist_channels = list(engine.safety_state.whitelist)
        return {
            "meters": levels,
            "locked_channels": locked_channels,
            "whitelist_channels": whitelist_channels,
        }

    @app.get("/api/v1/events")
    async def get_events(limit: int = 100) -> Dict[str, Any]:
        """Lấy nhật ký sự kiện có cấu trúc."""
        return {"events": event_log[-limit:]}

    @app.get("/api/v1/settings")
    async def get_settings() -> Dict[str, Any]:
        """Lấy cấu hình an toàn và danh sách whitelist."""
        with engine._safety_lock:
            st = engine.safety_state
            return {
                "whitelist_channels": sorted(list(st.whitelist)),
                "whitelist_buses": sorted(list(st.bus_whitelist)),
                "auto_release_wait_s": st.auto_release_wait_s,
                "auto_release_rate_db_per_s": st.auto_release_rate_db_per_s,
                "auto_release_enabled": st.auto_release_enabled,
                "max_cut_db": st.max_cut_db,
                "max_boost_db": st.max_boost_db,
            }

    @app.post("/api/v1/snapshot/take")
    async def take_snapshot(request: Request) -> Dict[str, Any]:
        """Chụp snapshot trạng thái PEQ."""
        check_lan_auth(request)
        mgr = get_snapshot_mgr()
        if not mgr:
            raise HTTPException(status_code=500, detail="Snapshot manager chưa khả dụng")

        snap = mgr.take_snapshot(
            channel_bands_count=engine.config.eq.channel_bands_count,
            bus_bands_count=engine.config.eq.bus_bands_count,
            main_bands_count=engine.config.eq.main_bands_count,
        )
        record_event("snapshot_taken", {"bands_count": len(snap.bands)})
        return {
            "success": True,
            "bands_count": len(snap.bands),
            "timestamp": snap.timestamp,
            "message": f"Đã chụp snapshot PEQ ({len(snap.bands)} bands)",
            "message_code": "snapshot_taken",
            "params": {"count": len(snap.bands)},
        }

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
            "message_code": "snapshot_rollback",
            "params": {
                "restored_count": report.restored_count,
                "failed_count": len(report.failed_addresses),
            },
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
    # C1. Trang Chẩn đoán kết nối
    # ==========================================

    @app.get("/api/v1/diagnostics")
    async def get_diagnostics() -> Dict[str, Any]:
        """Thông tin chẩn đoán kết nối chi tiết (Phần C1)."""
        client = engine.mixer_client
        dev_info = client.get_device_info() if client else {}

        audio_dev = "Mô phỏng (Virtual 18x18)" if mock_mode else ("USB 18x18" if engine.audio_capture else "Chế độ LAN RTA")
        sr = 48000
        xruns = int(engine.audio_capture.ring_buffer.xrun_count[0]) if engine.audio_capture else 0

        return {
            "mock_mode": mock_mode,
            "dry_run": getattr(engine, "dry_run", False),
            "mixer_state": client.get_state().value if client else ("DEMO" if mock_mode else "DISCONNECTED"),
            "mixer_ip": dev_info.get("ip") or ("127.0.0.1" if mock_mode else "—"),
            "mixer_port": dev_info.get("port") or engine.config.device.port,
            "hardware_model": dev_info.get("model") or ("Simulated XR18" if mock_mode else "—"),
            "mixer_name": dev_info.get("name") or ("FakeXR18 Sim" if mock_mode else "—"),
            "firmware": dev_info.get("firmware") or ("SIM" if mock_mode else "—"),
            "firmware_reason": dev_info.get("firmware_reason"),
            "rtt_ms": getattr(client, "last_rtt_ms", None),
            "rta_subscribed": getattr(client, "_rta_subscribed", False),
            "meters_subscribed": getattr(client, "_meters_subscribed", False),
            "audio_device": audio_dev,
            "sample_rate": sr,
            "channel_count": 18,
            "xruns": xruns,
            "osc_tx_count": getattr(client, "osc_tx_count", 0),
            "osc_rx_count": getattr(client, "osc_rx_count", 0),
            "last_error": getattr(client, "last_error", None),
            "uptime_s": round(time.time() - start_time, 1),
            "active_notches_count": len(engine.safety_state.active_notches),
            "pending_proposals_count": len(engine.pending_proposals),
            "mode": engine.mode,
            "lan_rta_mode": not engine.config.device.has_multichannel_usb,
        }

    # ==========================================
    # C2. Shadow / Dry-run Mode
    # ==========================================

    @app.post("/api/v1/dry_run")
    async def set_dry_run(req: DryRunChangeRequest, request: Request) -> Dict[str, Any]:
        """Bật/tắt chế độ Shadow / Dry-run."""
        check_lan_auth(request)
        new_val = req.get_dry_run()
        engine.dry_run = new_val
        record_event("dry_run_changed", {"dry_run": new_val})
        await manager.broadcast_json({"type": "dry_run_updated", "dry_run": new_val})
        return {"success": True, "dry_run": new_val}

    # ==========================================
    # B2. Nút Tạo hú giả (Demo Mode)
    # ==========================================

    @app.post("/api/v1/demo/feedback")
    async def trigger_demo_feedback(req: FeedbackTriggerRequest, request: Request) -> Dict[str, Any]:
        """Tạo tiếng hú giả lập phục vụ kiểm thử chế độ Demo."""
        check_lan_auth(request)
        if not mock_mode:
            raise HTTPException(status_code=400, detail="Chức năng tạo hú giả chỉ khả dụng ở chế độ Demo/Mock")

        if hasattr(engine, "trigger_fake_feedback"):
            engine.trigger_fake_feedback(channel=req.channel, freq_hz=req.freq_hz, duration_s=req.duration_s)

        record_event("demo_feedback_triggered", {"channel": req.channel, "freq_hz": req.freq_hz, "duration_s": req.duration_s})
        return {
            "success": True,
            "message": f"Đã tạo tiếng hú giả lập tại Kênh {req.channel} ({req.freq_hz:.0f} Hz) trong {req.duration_s:.1f}s",
            "channel": req.channel,
            "freq_hz": req.freq_hz,
            "duration_s": req.duration_s,
        }

    # ==========================================
    # C3. Ring-out Wizard Trước Show
    # ==========================================

    @app.get("/api/v1/wizard/status")
    async def get_wizard_status() -> Dict[str, Any]:
        """Lấy trạng thái hiện tại của Ring-out Wizard."""
        return wizard_state

    @app.post("/api/v1/wizard/start")
    async def start_wizard(req: WizardStartRequest, request: Request) -> Dict[str, Any]:
        """Bắt đầu chu trình Ring-out Wizard trước show."""
        check_lan_auth(request)
        nonlocal wizard_state, wizard_task
        if wizard_state["running"]:
            raise HTTPException(status_code=400, detail="Ring-out Wizard đang chạy")

        wizard_state = {
            "running": True,
            "target": req.target,
            "channel": req.channel,
            "max_boost_db": req.max_boost_db,
            "step_db": req.step_db,
            "current_boost_db": 0.0,
            "detected_notches": [],
            "venue_name": req.venue_name,
            "message": "Đang tiến hành dò hú từng bước...",
        }
        step_interval = req.get_interval()
        ringout_controller.config.step_db = req.step_db
        ringout_controller.config.max_boost_above_start_db = req.max_boost_db
        ringout_controller.config.step_interval_s = step_interval
        ringout_controller.start(
            target_type=req.target,
            target_id=req.channel,
            initial_fader_val=0.75,
            initial_fader_db=0.0,
        )
        record_event("wizard_started", dict(wizard_state))

        # Đọc fader ban đầu từ cache nếu có, mặc định 0.75 (~0 dB)
        init_fader_val = 0.75
        target_type = req.target
        target_ch = req.channel
        if engine.mixer_client and hasattr(engine.mixer_client, "_params_cache"):
            if target_type in ("main", "lr") or target_ch == 0:
                lr_p = getattr(getattr(engine.mixer_client, "capability_map", None), "lr_prefix", "/lr")
                f_addr = f"{lr_p}/mix/fader"
            elif target_type == "bus":
                f_addr = f"/bus/{target_ch}/mix/fader"
            else:
                f_addr = f"/ch/{target_ch:02d}/mix/fader"
            cached_f = engine.mixer_client._params_cache.get(f_addr)
            if cached_f is not None:
                init_fader_val = float(cached_f)

        async def _wizard_loop():
            nonlocal wizard_state
            try:
                curr_boost = 0.0
                while wizard_state["running"] and curr_boost < req.max_boost_db:
                    await asyncio.sleep(step_interval)
                    if not wizard_state["running"]:
                        break
                    curr_boost += req.step_db
                    wizard_state["current_boost_db"] = round(curr_boost, 1)
                    ringout_controller.current_fader_db = wizard_state["current_boost_db"]

                    # Tăng fader từng nấc nhỏ trên mixer thật (+1 dB ~ 0.02 chuẩn hóa)
                    if engine.mixer_client and engine.mixer_client.get_state() == ConnectionState.CONNECTED:
                        boosted_fader = min(1.0, max(0.0, init_fader_val + (curr_boost * 0.02)))
                        if hasattr(engine.mixer_client, "set_fader"):
                            engine.mixer_client.set_fader(target=target_type, index=target_ch, val=boosted_fader)

                    record_event("wizard_step", {"boost_db": wizard_state["current_boost_db"]})
                    await manager.broadcast_json({"type": "wizard_step", "state": wizard_state})

                    # Kiểm tra các điểm hú vừa được gọt (hỗ trợ cả Auto và Semi mode qua active_notches)
                    with engine._safety_lock:
                        for (t_id, b), notch in engine.safety_state.active_notches.items():
                            is_match = False
                            if target_type == "bus" and (notch.target == "bus" or t_id < 0):
                                notch_bus = notch.bus if notch.bus is not None else abs(t_id)
                                if notch_bus == target_ch:
                                    is_match = True
                            elif target_type in ("main", "lr") and (notch.channel == 0 or notch.target in ("main", "lr")):
                                is_match = True
                            elif target_type == "ch" and notch.channel == target_ch:
                                is_match = True

                            if is_match:
                                notch_info = {
                                    "freq_hz": round(notch.freq_hz, 1),
                                    "gain_db": round(notch.current_gain_db, 1),
                                    "channel": notch.channel,
                                    "target": notch.target,
                                    "band": b,
                                }
                                if not any(n["freq_hz"] == notch_info["freq_hz"] and n.get("band") == b for n in wizard_state["detected_notches"]):
                                    wizard_state["detected_notches"].append(notch_info)
                                    ringout_controller.notches_found.append(notch_info)

                    # Đồng thời đọc thêm từ pending_proposals (khi ở semi mode)
                    with engine._proposals_lock:
                        curr_props = list(engine.pending_proposals)
                    for p in curr_props:
                        p_info = {
                            "freq_hz": round(p.freq_hz, 1),
                            "gain_db": round(p.gain_db, 1),
                            "channel": p.channel,
                            "target": p.target,
                            "band": p.band or 0,
                        }
                        if not any(n["freq_hz"] == p_info["freq_hz"] for n in wizard_state["detected_notches"]):
                            wizard_state["detected_notches"].append(p_info)
                            ringout_controller.notches_found.append(p_info)

                # Khi hoàn tất: trả fader về đúng mức ban đầu
                if engine.mixer_client and engine.mixer_client.get_state() == ConnectionState.CONNECTED:
                    if hasattr(engine.mixer_client, "set_fader"):
                        engine.mixer_client.set_fader(target=target_type, index=target_ch, val=init_fader_val)

                wizard_state["running"] = False
                wizard_state["current_boost_db"] = 0.0
                wizard_state["message"] = f"Hoàn tất dò hú! Đã phát hiện và gọt {len(wizard_state['detected_notches'])} tần số cộng hưởng."
                record_event("wizard_completed", dict(wizard_state))
                await manager.broadcast_json({"type": "wizard_completed", "state": wizard_state})
            except asyncio.CancelledError:
                # Trả fader về an toàn khi bị hủy
                if engine.mixer_client and engine.mixer_client.get_state() == ConnectionState.CONNECTED:
                    if hasattr(engine.mixer_client, "set_fader"):
                        engine.mixer_client.set_fader(target=target_type, index=target_ch, val=init_fader_val)
            except Exception as e:
                if engine.mixer_client and engine.mixer_client.get_state() == ConnectionState.CONNECTED:
                    if hasattr(engine.mixer_client, "set_fader"):
                        engine.mixer_client.set_fader(target=target_type, index=target_ch, val=init_fader_val)
                wizard_state["running"] = False
                wizard_state["current_boost_db"] = 0.0
                wizard_state["message"] = f"Lỗi Wizard: {e}"
                await manager.broadcast_json({"type": "wizard_stopped", "state": wizard_state})

        wizard_task = asyncio.create_task(_wizard_loop())
        return {"success": True, "message": "Đã bắt đầu Ring-out Wizard", "state": wizard_state}

    @app.post("/api/v1/wizard/stop")
    async def stop_wizard(request: Request) -> Dict[str, Any]:
        """Dừng khẩn cấp Ring-out Wizard và hạ gain về ban đầu."""
        check_lan_auth(request)
        nonlocal wizard_state, wizard_task
        if wizard_task and not wizard_task.done():
            wizard_task.cancel()

        target_type = wizard_state.get("target", "bus")
        target_ch = wizard_state.get("channel", 1)
        if engine.mixer_client and engine.mixer_client.get_state() == ConnectionState.CONNECTED:
            if hasattr(engine.mixer_client, "set_fader"):
                engine.mixer_client.set_fader(target=target_type, index=target_ch, val=0.75)

        report = ringout_controller.stop(reason="user_stopped")
        wizard_state["running"] = False
        wizard_state["current_boost_db"] = 0.0
        wizard_state["message"] = report.message or "Đã dừng Wizard và khôi phục gain an toàn."
        record_event("wizard_stopped", {})
        await manager.broadcast_json({"type": "wizard_stopped", "state": wizard_state})
        return {"success": True, "message": "Đã dừng Ring-out Wizard và hạ gain về mức an toàn ban đầu"}

    # ==========================================
    # C4.1. Auto Preamp Gain & Smart FX Talkover (V2)
    # ==========================================

    @app.get("/api/v1/gain/status")
    async def get_gain_status() -> Dict[str, Any]:
        """Lấy trạng thái cân Gain của các kênh micro."""
        sessions_data = {}
        for ch, s in gain_manager.sessions.items():
            sessions_data[ch] = {
                "channel": ch,
                "status": s.status,
                "is_active": s.is_active,
                "current_gain_db": s.current_headamp_gain_db,
                "proposed_gain_db": s.proposed_gain_db,
            }
        return {
            "sessions": sessions_data,
            "target_rms_dbfs": gain_manager.target_rms_dbfs,
            "max_peak_dbfs": gain_manager.max_peak_dbfs,
            "auto_tame_enabled": gain_manager.auto_tame_enabled,
        }

    @app.post("/api/v1/gain/calibrate/{channel}")
    async def start_gain_calibration(channel: int, request: Request) -> Dict[str, Any]:
        """Bắt đầu phiên đo cân Gain 10 giây cho kênh micro."""
        check_lan_auth(request)
        if channel < 1 or channel > 16:
            raise HTTPException(status_code=400, detail="Kênh không hợp lệ (1-16)")
        client = engine.mixer_client
        cur_gain = 20.0
        if client and hasattr(client, "_params_cache"):
            addr = f"/headamp/{channel:02d}/gain"
            val = client._params_cache.get(addr)
            if val is not None:
                cur_gain = float(val) * 72.0 - 12.0
        gain_manager.start_calibration(channel=channel, current_headamp_gain_db=cur_gain)
        record_event("gain_calibration_started", {"channel": channel, "current_gain_db": cur_gain})
        return {"success": True, "message": f"Bắt đầu cân Gain 10s cho Kênh {channel}", "channel": channel}

    @app.post("/api/v1/gain/apply/{channel}")
    async def apply_gain(channel: int, request: Request) -> Dict[str, Any]:
        """Áp dụng Gain đề xuất xuống mixer qua /headamp/{ch}/gain."""
        check_lan_auth(request)
        session = gain_manager.sessions.get(channel)
        if not session or session.proposed_gain_db is None:
            raise HTTPException(status_code=400, detail="Chưa có kết quả Gain đề xuất")
        client = engine.mixer_client
        target_db = session.proposed_gain_db
        norm_val = max(0.0, min(1.0, (target_db + 12.0) / 72.0))
        if client and hasattr(client, "_send_raw"):
            from auto_sound.mixer.osc import encode_message
            client._send_raw(encode_message(f"/headamp/{channel:02d}/gain", norm_val))
        session.status = "APPLIED"
        session.current_headamp_gain_db = target_db
        record_event("gain_applied", {"channel": channel, "applied_gain_db": target_db})
        return {"success": True, "message": f"Đã gán Gain {target_db:+.1f}dB cho Kênh {channel}", "gain_db": target_db}

    @app.get("/api/v1/talkover/status")
    async def get_talkover_status() -> Dict[str, Any]:
        """Lấy trạng thái Smart FX Auto-Talkover."""
        return {
            "enabled": talkover_controller.config.enabled,
            "is_ducked": talkover_controller.is_ducked,
            "mic_channel": talkover_controller.config.mic_channel,
            "music_channels": talkover_controller.config.music_channels,
            "hold_time_s": talkover_controller.config.hold_time_s,
            "ducking_depth_db": talkover_controller.config.ducking_depth_db,
            "clip_guardian_enabled": gain_manager.auto_tame_enabled,
        }

    @app.post("/api/v1/talkover/toggle")
    async def toggle_talkover(request: Request) -> Dict[str, Any]:
        """Bật / tắt Smart FX Auto-Talkover."""
        check_lan_auth(request)
        talkover_controller.config.enabled = not talkover_controller.config.enabled
        state_str = "BẬT" if talkover_controller.config.enabled else "TẮT"
        record_event("talkover_toggled", {"enabled": talkover_controller.config.enabled})
        return {"success": True, "enabled": talkover_controller.config.enabled, "message": f"Đã {state_str} Smart FX Talkover"}

    @app.post("/api/v1/clip-guardian/toggle")
    async def toggle_clip_guardian(request: Request) -> Dict[str, Any]:
        """Bật / tắt Clip Guardian Auto-Tame."""
        check_lan_auth(request)
        gain_manager.auto_tame_enabled = not gain_manager.auto_tame_enabled
        state_str = "BẬT" if gain_manager.auto_tame_enabled else "TẮT"
        record_event("clip_guardian_toggled", {"enabled": gain_manager.auto_tame_enabled})
        return {"success": True, "enabled": gain_manager.auto_tame_enabled, "message": f"Đã {state_str} Clip Guardian"}

    # ==========================================
    # C5. Lịch sử Notch, Hoàn tác từng notch & Báo cáo Show
    # ==========================================

    @app.get("/api/v1/notches/history")
    async def get_notch_history() -> Dict[str, Any]:
        """Lấy lịch sử toàn bộ các notch đã từng can thiệp trong show."""
        return {"history": notch_history}

    @app.post("/api/v1/notches/undo")
    async def undo_single_notch(req: ReleaseNotchRequest, request: Request) -> Dict[str, Any]:
        """Hoàn tác một notch cụ thể về 0 dB mà không cần PANIC toàn bộ."""
        return await release_notch(req, request)

    @app.get("/api/v1/report/export")
    async def export_show_report(format: str = Query("json", pattern="^(json|csv)$")) -> Any:
        """Xuất báo cáo show ra file CSV hoặc JSON."""
        now = time.time()
        report_data = {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "uptime_s": round(now - start_time, 1),
            "model": engine.config.device.name,
            "active_notches": (await get_notches())["notches"],
            "notch_history": notch_history,
            "total_interventions": len(notch_history),
        }
        if format == "json":
            return JSONResponse(content=report_data)

        import csv
        import io
        from fastapi.responses import Response

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Thời gian", "Hành động", "Kênh/Bus", "Band", "Tần số (Hz)", "Gain (dB)", "Q", "Lý do"])
        for n in notch_history:
            writer.writerow([
                n.get("time_str", ""),
                n.get("action", ""),
                n.get("channel", ""),
                n.get("band", ""),
                n.get("freq_hz", ""),
                n.get("gain_db", ""),
                n.get("q", ""),
                n.get("reason", ""),
            ])
        output.seek(0)
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=show_notch_report.csv"},
        )

    # ==========================================
    # C7. Thiết bị USB Audio & Kiểm tra Routing
    # ==========================================

    @app.get("/api/v1/audio/devices")
    async def get_audio_devices() -> Dict[str, Any]:
        """Liệt kê các thiết bị âm thanh khả dụng trong hệ thống."""
        import sounddevice as sd
        try:
            devs = sd.query_devices()
            device_list = []
            for idx, d in enumerate(devs):
                if d.get("max_input_channels", 0) > 0:
                    is_xr = "XR" in d["name"] or "X-Air" in d["name"] or "X18" in d["name"]
                    device_list.append({
                        "index": idx,
                        "name": d["name"],
                        "max_input_channels": d["max_input_channels"],
                        "default_samplerate": d["default_samplerate"],
                        "is_recommended": is_xr,
                    })
            return {"devices": device_list, "count": len(device_list)}
        except Exception as e:
            return {"devices": [], "count": 0, "error": str(e)}

    @app.get("/api/v1/audio/routing-check")
    async def check_audio_routing() -> Dict[str, Any]:
        """Kiểm tra cấu hình USB Sends, sample rate 48 kHz và số kênh."""
        issues = []
        is_ok = True

        if mock_mode:
            return {
                "ok": True,
                "message": "Chế độ mô phỏng (Demo / Virtual 18x18) — Định tuyến ảo hợp lệ",
                "sample_rate": 48000,
                "channels": 18,
                "issues": [],
            }

        if not engine.config.device.has_multichannel_usb:
            return {
                "ok": True,
                "message": "Chế độ LAN RTA (XR12 / XR16) không yêu cầu cổng USB đa kênh",
                "sample_rate": 48000,
                "channels": 2,
                "issues": [],
            }

        if engine.audio_capture:
            if engine.audio_capture.sample_rate != 48000:
                is_ok = False
                issues.append(f"Sample rate hiện tại là {engine.audio_capture.sample_rate} Hz (Chuẩn yêu cầu: 48000 Hz)")
            if engine.audio_capture.channels < 18:
                is_ok = False
                issues.append(f"Số kênh thu là {engine.audio_capture.channels} (Yêu cầu đủ 18 kênh USB Sends từ XR18)")
            xruns = int(engine.audio_capture.ring_buffer.xrun_count[0])
            if xruns > 10:
                issues.append(f"Phát hiện {xruns} lần nghẽn đệm âm thanh (xruns) - hãy kiểm tra cáp USB hoặc tăng buffer")
        else:
            is_ok = False
            issues.append("Chưa kích hoạt luồng thu âm thanh USB Audio")

        return {
            "ok": is_ok,
            "message": "Cấu hình USB Routing chuẩn 48 kHz / 18 kênh" if is_ok else "Phát hiện sai sót trong cấu hình USB Audio",
            "sample_rate": 48000,
            "channels": 18,
            "issues": issues,
        }

    # ==========================================
    # C8. Gợi ý Dynamics (Compressor / Gate / Gain)
    # ==========================================

    @app.get("/api/v1/dynamics/suggestions")
    async def get_dynamics_suggestions() -> Dict[str, Any]:
        """Gợi ý thiết lập gain staging, compressor, gate (giai đoạn đầu chỉ gợi ý cho soundman duyệt)."""
        suggestions = []
        client = engine.mixer_client
        meters = client.get_meter_levels() if client else [0.0] * 18

        for ch in engine.config.channels.mic_channels:
            level = meters[ch - 1] if ch - 1 < len(meters) else 0.0
            ch_name = client.get_channel_name(ch) if client else f"CH {ch:02d}"

            if level > 0.85:
                suggestions.append({
                    "channel": ch,
                    "channel_name": ch_name,
                    "type": "clip_risk",
                    "severity": "high",
                    "suggestion": f"{ch_name}: Tín hiệu quá lớn ({level:.2f}), nguy cơ clip! Đề xuất giảm gain staging -3 dB hoặc bật compressor threshold -12 dB.",
                })
            elif level < 0.02 and not (client and client.is_channel_muted(ch)):
                suggestions.append({
                    "channel": ch,
                    "channel_name": ch_name,
                    "type": "low_signal",
                    "severity": "info",
                    "suggestion": f"{ch_name}: Tín hiệu rất thấp, đề xuất kiểm tra kết nối micro hoặc tăng nhẹ preamp gain.",
                })
        return {"suggestions": suggestions, "count": len(suggestions)}

    # ==========================================
    # C11. Thu mẫu âm thanh thật (Dataset Benchmark)
    # ==========================================

    @app.post("/api/v1/audio/record")
    async def record_audio_sample(req: AudioRecordRequest, request: Request) -> Dict[str, Any]:
        """Thu mẫu tín hiệu âm thanh kèm nhãn hú/không hú để xây dựng benchmark."""
        check_lan_auth(request)
        is_real = not mock_mode and engine.audio_capture and hasattr(engine.audio_capture, "ring_buffer")
        folder_name = "real_recordings" if is_real else "synthetic_recordings"
        out_dir = Path("data") / folder_name
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{req.label}_ch{req.channel}_{int(time.time())}.wav"
        filepath = out_dir / filename

        import wave
        import numpy as np

        if is_real:
            sr = engine.audio_capture.sample_rate
            total_frames = int(sr * req.duration_s)
            tmp_buf = np.zeros((total_frames, engine.audio_capture.channels), dtype=np.float32)
            n_read = engine.audio_capture.ring_buffer.read(tmp_buf)
            ch_idx = min(req.channel - 1, engine.audio_capture.channels - 1)
            sig = tmp_buf[:n_read, ch_idx] if n_read > 0 else np.zeros(total_frames, dtype=np.float32)
        else:
            from auto_sound.sim.room import RoomSimulator
            sim = RoomSimulator(sample_rate=48000)
            if req.label == "feedback":
                sig = sim.generate_feedback_loop(duration_s=req.duration_s, target_freq_hz=2500.0)
            else:
                sig = sim.generate_vocal_sustain(duration_s=req.duration_s, freq_hz=440.0)

        clamped = np.clip(sig, -1.0, 1.0)
        raw = (clamped * 32767).astype(np.int16).tobytes()

        with wave.open(str(filepath), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(48000)
            wf.writeframes(raw)

        record_event("sample_recorded", {
            "filename": filename,
            "label": req.label,
            "duration_s": req.duration_s,
            "is_real_hardware": is_real,
            "folder": folder_name,
        })
        return {
            "success": True,
            "filename": filename,
            "path": str(filepath),
            "label": req.label,
            "duration_s": req.duration_s,
            "is_real_hardware": is_real,
            "message": f"Đã lưu mẫu âm thanh '{filename}' vào data/{folder_name}/",
        }

    @app.post("/api/v1/demo/trigger_feedback")
    async def trigger_demo_feedback(
        channel: int = 2,
        freq_hz: float = 2500.0,
        duration_s: float = 5.0,
    ) -> Dict[str, Any]:
        """Kích hoạt tiếng hú giả lập trong chế độ Mock/Demo để kiểm thử."""
        if not mock_mode:
            raise HTTPException(status_code=400, detail="Chỉ hỗ trợ trong chế độ Mock (--mock)")
        if hasattr(engine, "trigger_fake_feedback"):
            engine.trigger_fake_feedback(channel=channel, freq_hz=freq_hz, duration_s=duration_s)
        return {"success": True, "channel": channel, "freq_hz": freq_hz, "duration_s": duration_s}

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
                        count, now = execute_panic()
                        await manager.broadcast_json({
                            "type": "panic_event",
                            "released_count": count,
                            "timestamp": now,
                            "message_code": "panic_triggered",
                            "params": {"count": count},
                        })

                    elif action == "approve_proposal":
                        prop_id = msg.get("proposal_id", "")
                        prop = _pop_proposal_by_id(prop_id)
                        if prop:
                            engine._cmd_queue.put(prop)
                            record_event("proposal_approved", asdict(prop))
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
