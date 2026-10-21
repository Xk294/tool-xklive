"""Bộ điều khiển an toàn (Safety Controller) - Hàm thuần túy kiểm soát mọi can thiệp vào mixer."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from auto_sound.core.models import ActionProposal, Decision, PEQBand


@dataclass(frozen=True)
class ActiveNotch:
    """Thông tin về một bộ lọc notch đang hoạt động trên hệ thống."""
    channel: int
    band: int
    freq_hz: float
    current_gain_db: float
    target_gain_db: float
    q: float
    is_probing: bool
    last_updated_time: float
    probe_step_count: int = 1
    target: str = "ch"                # "ch" hoặc "bus"
    bus: Optional[int] = None         # Bus 1-6 nếu target == "bus"


@dataclass(frozen=True)
class SafetyState:
    """Trạng thái an toàn hoàn toàn bất biến (immutable) phục vụ hàm thuần túy."""
    # Các notch đang hoạt động: (channel, band) -> ActiveNotch (với bus: channel = -bus)
    active_notches: Dict[Tuple[int, int], ActiveNotch] = field(default_factory=dict)
    # Thời điểm hết hạn tạm khóa khi soundman chỉnh tay: channel -> timestamp
    channel_locks: Dict[int, float] = field(default_factory=dict)
    # Danh sách thời điểm các giao dịch đã thực hiện trong 1.0 giây gần nhất
    transaction_history: Tuple[float, ...] = field(default_factory=tuple)
    # Danh sách kênh được phép can thiệp (Channel Whitelist)
    whitelist: Set[int] = field(default_factory=lambda: set(range(1, 17)))
    # Các band PEQ dành riêng cho hệ thống trên từng kênh: channel -> list[band] (mặc định [3, 4])
    allowed_bands: Dict[int, Tuple[int, ...]] = field(
        default_factory=lambda: {ch: (3, 4) for ch in range(1, 17)}
    )
    # Hỗ trợ can thiệp trên Bus (Aux/Monitor - Giai đoạn D2)
    bus_whitelist: Set[int] = field(default_factory=lambda: set(range(1, 7)))
    bus_locks: Dict[int, float] = field(default_factory=dict)
    bus_allowed_bands: Dict[int, Tuple[int, ...]] = field(
        default_factory=lambda: {b: (5, 6) for b in range(1, 7)}
    )
    # Cấu hình giới hạn an toàn
    max_boost_db: float = 4.0
    max_cut_db: float = -12.0
    probe_step_db: float = -3.0
    probe_wait_ms: float = 80.0
    max_transactions_per_sec: float = 2.0
    lock_duration_s: float = 10.0
    # Cấu hình xử lý khi cạn band và tự động nhả notch (Phương án 1 & 3)
    reclaim_on_exhaustion: bool = False
    auto_release_wait_s: float = 20.0
    auto_release_rate_db_per_s: float = 1.0
    auto_release_enabled: bool = True


def decide(state: SafetyState, proposal: ActionProposal, now: float) -> Tuple[SafetyState, Decision]:
    """Hàm thuần túy: Nhận trạng thái + đề xuất + thời gian thực tế -> Trả về (Trạng thái mới, Quyết định).
    
    Tuyệt đối không thực hiện bất kỳ lệnh I/O, mạng hoặc gọi đồng hồ ngầm bên trong hàm.
    Hỗ trợ cả can thiệp trên Channel (Mic) và Bus (Aux Monitor).
    """
    is_bus = (proposal.target == "bus" or (proposal.bus is not None and proposal.target != "ch"))
    target_bus = proposal.bus if proposal.bus is not None else proposal.channel
    ch = proposal.channel

    # 1. Kiểm tra Whitelist
    if is_bus:
        if target_bus not in state.bus_whitelist:
            return state, Decision(
                approved=False,
                proposal=proposal,
                reason=f"Bus {target_bus} không nằm trong danh sách cho phép (Bus Whitelist)",
            )
    else:
        if ch not in state.whitelist:
            return state, Decision(
                approved=False,
                proposal=proposal,
                reason=f"Kênh {ch} không nằm trong danh sách cho phép (Whitelist)",
            )

    # 2. Kiểm tra khóa kênh/bus khi Soundman vừa chỉnh tay
    if is_bus:
        lock_until = state.bus_locks.get(target_bus, 0.0)
        if now < lock_until:
            remaining = lock_until - now
            return state, Decision(
                approved=False,
                proposal=proposal,
                reason=f"Bus {target_bus} đang bị tạm khóa ({remaining:.1f}s còn lại) do kỹ sư chỉnh tay",
            )
    else:
        lock_until = state.channel_locks.get(ch, 0.0)
        if now < lock_until:
            remaining = lock_until - now
            return state, Decision(
                approved=False,
                proposal=proposal,
                reason=f"Kênh {ch} đang bị tạm khóa ({remaining:.1f}s còn lại) do kỹ sư chỉnh tay",
            )

    # 3. Kiểm tra hạn mức giao dịch (Rate Limiting: tối đa 2 giao dịch/giây)
    recent_transactions = tuple(t for t in state.transaction_history if now - t < 1.0)
    if len(recent_transactions) >= state.max_transactions_per_sec:
        new_state = _clone_state(state, transaction_history=recent_transactions)
        return new_state, Decision(
            approved=False,
            proposal=proposal,
            reason=f"Vượt quá hạn mức {state.max_transactions_per_sec} giao dịch/giây",
        )

    # 4. Kiểm tra giới hạn Boost Gain
    if proposal.gain_db > state.max_boost_db:
        return state, Decision(
            approved=False,
            proposal=proposal,
            reason=f"Gain đề xuất ({proposal.gain_db:+.1f}dB) vượt quá giới hạn an toàn (+{state.max_boost_db}dB)",
        )

    # 5. Phân bổ Band PEQ dành riêng cho hệ thống
    # Với kênh: mặc định [3, 4] (tuyệt đối không chạm 1, 2)
    # Với bus: mặc định [5, 6] (tuyệt đối không chạm 1, 2, 3, 4)
    if is_bus:
        available_bands = state.bus_allowed_bands.get(target_bus, (5, 6))
        target_key_id = -target_bus  # Khóa âm đại diện cho Bus để không trùng Channel ID
    else:
        available_bands = state.allowed_bands.get(ch, (3, 4))
        target_key_id = ch

    allocated_band: Optional[int] = None

    # Tìm xem đã có notch nào tại tần số tương tự (trong phạm vi 5%) chưa
    existing_notch_key: Optional[Tuple[int, int]] = None
    for (t_id, b), notch in state.active_notches.items():
        if t_id == target_key_id:
            if abs(notch.freq_hz - proposal.freq_hz) / notch.freq_hz <= 0.05:
                existing_notch_key = (t_id, b)
                allocated_band = b
                break

    # Nếu chưa có notch tại tần số này: Tìm band trống trong danh sách cho phép
    if allocated_band is None:
        used_bands = {b for (t_id, b) in state.active_notches.keys() if t_id == target_key_id}
        for b in available_bands:
            if b not in used_bands:
                allocated_band = b
                break

    # Xử lý khi cạn band tự động (Phương án 1):
    is_reclaimed = False
    reclaim_info = ""
    if allocated_band is None and state.reclaim_on_exhaustion:
        candidate_notches = [
            (b, state.active_notches[(target_key_id, b)])
            for b in available_bands
            if (target_key_id, b) in state.active_notches
        ]
        if candidate_notches:
            # Ưu tiên: 1) độ sâu cắt nông nhất (abs nhỏ nhất), 2) cũ nhất (last_updated_time nhỏ nhất)
            candidate_notches.sort(key=lambda item: (abs(item[1].current_gain_db), item[1].last_updated_time))
            reclaimed_band, reclaimed_notch = candidate_notches[0]
            allocated_band = reclaimed_band
            is_reclaimed = True
            tgt_name = f"Bus {target_bus}" if is_bus else f"Kênh {ch}"
            reclaim_info = (
                f"[CẠN BAND] Tái sử dụng Band {allocated_band} (thay thế notch {reclaimed_notch.freq_hz:.1f}Hz, "
                f"{reclaimed_notch.current_gain_db:+.1f}dB) trên {tgt_name}"
            )

    # Nếu không thể phân bổ hoặc tái sử dụng band nào
    if allocated_band is None:
        tgt_name = f"Bus {target_bus}" if is_bus else f"Kênh {ch}"
        return state, Decision(
            approved=False,
            proposal=proposal,
            reason=f"{tgt_name} đã sử dụng hết các band PEQ dành riêng cho hệ thống ({available_bands})",
        )

    # 6. Chiến lược Cắt thăm dò vi phân (-3 dB Step Probing)
    new_notches = dict(state.active_notches)
    step_count = 1
    target_gain = state.probe_step_db  # Mặc định -3.0 dB

    if existing_notch_key is not None and not is_reclaimed:
        prev_notch = state.active_notches[existing_notch_key]
        step_count = prev_notch.probe_step_count + 1
        target_gain = max(state.max_cut_db, prev_notch.current_gain_db + state.probe_step_db)

    clamped_q = min(10.0, max(0.3, proposal.q))

    notch_record = ActiveNotch(
        channel=0 if is_bus else ch,
        band=allocated_band,
        freq_hz=proposal.freq_hz,
        current_gain_db=target_gain,
        target_gain_db=target_gain,
        q=clamped_q,
        is_probing=True,
        last_updated_time=now,
        probe_step_count=step_count,
        target="bus" if is_bus else "ch",
        bus=target_bus if is_bus else None,
    )
    new_notches[(target_key_id, allocated_band)] = notch_record

    # Ghi nhận giao dịch mới
    updated_transactions = recent_transactions + (now,)

    new_state = _clone_state(
        state,
        active_notches=new_notches,
        transaction_history=updated_transactions,
    )

    reason_str = (
        reclaim_info
        if is_reclaimed
        else f"Cắt thăm dò bước {step_count} ({target_gain:+.1f}dB tại {proposal.freq_hz:.1f}Hz)"
    )

    approved_proposal = ActionProposal(
        channel=0 if is_bus else ch,
        band=allocated_band,
        freq_hz=proposal.freq_hz,
        gain_db=target_gain,
        q=clamped_q,
        bus=target_bus if is_bus else None,
        target="bus" if is_bus else "ch",
        reason=reason_str,
    )

    return new_state, Decision(
        approved=True,
        proposal=approved_proposal,
        effective_gain_db=target_gain,
        is_probing=True,
        reason=reclaim_info if is_reclaimed else "Chấp thuận can thiệp hạ notch an toàn",
    )


def handle_manual_override(
    state: SafetyState,
    channel: int,
    now: float,
    target: str = "ch",
    bus: Optional[int] = None,
) -> SafetyState:
    """Khóa kênh hoặc bus trong 10 giây khi phát hiện Soundman vừa can thiệp bằng tay trên bàn mixer."""
    if target == "bus" or bus is not None:
        b = bus if bus is not None else channel
        new_bus_locks = dict(state.bus_locks)
        new_bus_locks[b] = now + state.lock_duration_s
        return _clone_state(state, bus_locks=new_bus_locks)
    else:
        new_locks = dict(state.channel_locks)
        new_locks[channel] = now + state.lock_duration_s
        return _clone_state(state, channel_locks=new_locks)


def panic_rollback(state: SafetyState, now: float) -> Tuple[SafetyState, List[ActionProposal]]:
    """Cơ chế Dừng khẩn cấp / Rollback: Hoàn tác toàn bộ các notch hệ thống về 0 dB trong 1 thao tác."""
    rollback_proposals: List[ActionProposal] = []

    for (t_id, band), notch in state.active_notches.items():
        is_bus = notch.target == "bus" or t_id < 0
        rollback_proposals.append(
            ActionProposal(
                channel=0 if is_bus else notch.channel,
                band=band,
                freq_hz=notch.freq_hz,
                gain_db=0.0,  # Nhả về phẳng
                q=notch.q,
                bus=notch.bus if is_bus else None,
                target="bus" if is_bus else ("main" if notch.channel == 0 else "ch"),
                reason="PANIC: Hoàn tác toàn bộ notch về 0 dB",
            )
        )

    # Xóa sạch toàn bộ notch hoạt động
    new_state = _clone_state(
        state,
        active_notches={},
        transaction_history=state.transaction_history + (now,),
    )

    return new_state, rollback_proposals


def check_auto_release(
    state: SafetyState, now: float, step_db: float = 1.0
) -> Tuple[SafetyState, List[ActionProposal]]:
    """Kiểm tra và tự động nhả dần các notch về 0 dB sau khi ổn định (Phương án 3).
    
    Quy tắc an toàn bất biến:
    - Kênh: Chỉ nhả allowed_bands (ví dụ Band 3-4), tuyệt đối không can thiệp Band 1-2.
    - Bus: Chỉ nhả bus_allowed_bands (ví dụ Band 5-6), tuyệt đối không can thiệp Band 1-4.
    - Không bao giờ nhả vượt quá 0.0 dB (không bao giờ boost).
    - Khi notch nhả chạm 0.0 dB, band được giải phóng hoàn toàn để tái sử dụng.
    """
    if not state.auto_release_enabled or not state.active_notches:
        return state, []

    proposals: List[ActionProposal] = []
    new_notches = dict(state.active_notches)

    for (t_id, band), notch in list(state.active_notches.items()):
        is_bus = notch.target == "bus" or t_id < 0

        # Kiểm tra tính hợp lệ của band
        if is_bus:
            bus_idx = notch.bus if notch.bus is not None else -t_id
            if band not in state.bus_allowed_bands.get(bus_idx, ()):
                continue
        else:
            if band not in state.allowed_bands.get(notch.channel, ()):
                continue

        idle_time = now - notch.last_updated_time
        if idle_time >= state.auto_release_wait_s:
            new_gain = round(notch.current_gain_db + step_db, 1)

            if new_gain >= 0.0:
                # Nhả hoàn toàn về 0 dB: giải phóng band khỏi danh sách notch hoạt động
                new_notches.pop((t_id, band), None)
                tgt_name = f"Bus {notch.bus}" if is_bus else f"Kênh {notch.channel}"
                proposals.append(
                    ActionProposal(
                        channel=0 if is_bus else notch.channel,
                        band=band,
                        freq_hz=notch.freq_hz,
                        gain_db=0.0,
                        q=notch.q,
                        bus=notch.bus if is_bus else None,
                        target="bus" if is_bus else ("main" if notch.channel == 0 else "ch"),
                        reason=f"Auto-release: Nhả hoàn toàn Band {band} về 0.0dB sau {idle_time:.1f}s ổn định trên {tgt_name}",
                    )
                )
            else:
                # Nhả một bước (ví dụ: -6.0dB -> -5.0dB)
                updated_notch = ActiveNotch(
                    channel=0 if is_bus else notch.channel,
                    band=band,
                    freq_hz=notch.freq_hz,
                    current_gain_db=new_gain,
                    target_gain_db=new_gain,
                    q=notch.q,
                    is_probing=False,
                    last_updated_time=now,
                    probe_step_count=notch.probe_step_count,
                    target="bus" if is_bus else "ch",
                    bus=notch.bus if is_bus else None,
                )
                new_notches[(t_id, band)] = updated_notch
                tgt_name = f"Bus {notch.bus}" if is_bus else f"Kênh {notch.channel}"
                proposals.append(
                    ActionProposal(
                        channel=0 if is_bus else notch.channel,
                        band=band,
                        freq_hz=notch.freq_hz,
                        gain_db=new_gain,
                        q=notch.q,
                        bus=notch.bus if is_bus else None,
                        target="bus" if is_bus else ("main" if notch.channel == 0 else "ch"),
                        reason=f"Auto-release: Nhả bước Band {band} lên {new_gain:+.1f}dB sau {idle_time:.1f}s ổn định trên {tgt_name}",
                    )
                )

    new_tx = state.transaction_history + ((now,) if proposals else ())
    new_state = _clone_state(
        state,
        active_notches=new_notches,
        transaction_history=new_tx,
    )
    return new_state, proposals


def _clone_state(state: SafetyState, **kwargs: Any) -> SafetyState:
    """Hàm phụ trợ sao chép bất biến trạng thái SafetyState."""
    data = {
        "active_notches": state.active_notches,
        "channel_locks": state.channel_locks,
        "transaction_history": state.transaction_history,
        "whitelist": state.whitelist,
        "allowed_bands": state.allowed_bands,
        "bus_whitelist": state.bus_whitelist,
        "bus_locks": state.bus_locks,
        "bus_allowed_bands": state.bus_allowed_bands,
        "max_boost_db": state.max_boost_db,
        "max_cut_db": state.max_cut_db,
        "probe_step_db": state.probe_step_db,
        "probe_wait_ms": state.probe_wait_ms,
        "max_transactions_per_sec": state.max_transactions_per_sec,
        "lock_duration_s": state.lock_duration_s,
        "reclaim_on_exhaustion": state.reclaim_on_exhaustion,
        "auto_release_wait_s": state.auto_release_wait_s,
        "auto_release_rate_db_per_s": state.auto_release_rate_db_per_s,
        "auto_release_enabled": state.auto_release_enabled,
    }
    data.update(kwargs)
    return SafetyState(**data)
