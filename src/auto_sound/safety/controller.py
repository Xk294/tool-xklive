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


@dataclass(frozen=True)
class SafetyState:
    """Trạng thái an toàn hoàn toàn bất biến (immutable) phục vụ hàm thuần túy."""
    # Các notch đang hoạt động: (channel, band) -> ActiveNotch
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
    # Cấu hình giới hạn an toàn
    max_boost_db: float = 4.0
    max_cut_db: float = -12.0
    probe_step_db: float = -3.0
    probe_wait_ms: float = 80.0
    max_transactions_per_sec: float = 2.0
    lock_duration_s: float = 10.0


def decide(state: SafetyState, proposal: ActionProposal, now: float) -> Tuple[SafetyState, Decision]:
    """Hàm thuần túy: Nhận trạng thái + đề xuất + thời gian thực tế -> Trả về (Trạng thái mới, Quyết định).
    
    Tuyệt đối không thực hiện bất kỳ lệnh I/O, mạng hoặc gọi đồng hồ ngầm bên trong hàm.
    """
    ch = proposal.channel

    # 1. Kiểm tra Channel Whitelist
    if ch not in state.whitelist:
        return state, Decision(
            approved=False,
            proposal=proposal,
            reason=f"Kênh {ch} không nằm trong danh sách cho phép (Whitelist)",
        )

    # 2. Kiểm tra khóa kênh khi Soundman vừa chỉnh tay
    lock_until = state.channel_locks.get(ch, 0.0)
    if now < lock_until:
        remaining = lock_until - now
        return state, Decision(
            approved=False,
            proposal=proposal,
            reason=f"Kênh {ch} đang bị tạm khóa ({remaining:.1f}s còn lại) do kỹ sư chỉnh tay",
        )

    # 3. Kiểm tra hạn mức giao dịch (Rate Limiting: tối đa 2 giao dịch/giây)
    # Lọc các giao dịch trong vòng 1.0 giây gần nhất
    recent_transactions = tuple(t for t in state.transaction_history if now - t < 1.0)
    if len(recent_transactions) >= state.max_transactions_per_sec:
        new_state = SafetyState(
            active_notches=state.active_notches,
            channel_locks=state.channel_locks,
            transaction_history=recent_transactions,
            whitelist=state.whitelist,
            allowed_bands=state.allowed_bands,
            max_boost_db=state.max_boost_db,
            max_cut_db=state.max_cut_db,
            probe_step_db=state.probe_step_db,
            probe_wait_ms=state.probe_wait_ms,
            max_transactions_per_sec=state.max_transactions_per_sec,
            lock_duration_s=state.lock_duration_s,
        )
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

    # 5. Phân bổ Band PEQ dành riêng cho hệ thống (mặc định chỉ dùng band 3 hoặc 4)
    available_bands = state.allowed_bands.get(ch, (3, 4))
    allocated_band: Optional[int] = None

    # Tìm xem đã có notch nào tại tần số tương tự (trong phạm vi 5%) chưa
    existing_notch_key: Optional[Tuple[int, int]] = None
    for (c, b), notch in state.active_notches.items():
        if c == ch:
            if abs(notch.freq_hz - proposal.freq_hz) / notch.freq_hz <= 0.05:
                existing_notch_key = (c, b)
                allocated_band = b
                break

    # Nếu chưa có notch tại tần số này: Tìm band trống trong danh sách cho phép
    if allocated_band is None:
        used_bands = {b for (c, b) in state.active_notches.keys() if c == ch}
        for b in available_bands:
            if b not in used_bands:
                allocated_band = b
                break

    # Nếu tất cả các band hệ thống đều đã dùng hết
    if allocated_band is None:
        return state, Decision(
            approved=False,
            proposal=proposal,
            reason=f"Kênh {ch} đã sử dụng hết các band PEQ dành riêng cho hệ thống ({available_bands})",
        )

    # 6. Chiến lược Cắt thăm dò vi phân (-3 dB Step Probing)
    new_notches = dict(state.active_notches)
    step_count = 1
    target_gain = state.probe_step_db  # Mặc định -3.0 dB

    if existing_notch_key is not None:
        prev_notch = state.active_notches[existing_notch_key]
        step_count = prev_notch.probe_step_count + 1
        # Cắt thêm 1 bước nữa (ví dụ: -3dB -> -6dB), không vượt quá max_cut_db (-12dB)
        target_gain = max(state.max_cut_db, prev_notch.current_gain_db + state.probe_step_db)

    # Giới hạn Q trong dải cho phép (tối đa 10.0 cho notch)
    clamped_q = min(10.0, max(0.3, proposal.q))

    notch_record = ActiveNotch(
        channel=ch,
        band=allocated_band,
        freq_hz=proposal.freq_hz,
        current_gain_db=target_gain,
        target_gain_db=target_gain,
        q=clamped_q,
        is_probing=True,
        last_updated_time=now,
        probe_step_count=step_count,
    )
    new_notches[(ch, allocated_band)] = notch_record

    # Ghi nhận giao dịch mới
    updated_transactions = recent_transactions + (now,)

    new_state = SafetyState(
        active_notches=new_notches,
        channel_locks=state.channel_locks,
        transaction_history=updated_transactions,
        whitelist=state.whitelist,
        allowed_bands=state.allowed_bands,
        max_boost_db=state.max_boost_db,
        max_cut_db=state.max_cut_db,
        probe_step_db=state.probe_step_db,
        probe_wait_ms=state.probe_wait_ms,
        max_transactions_per_sec=state.max_transactions_per_sec,
        lock_duration_s=state.lock_duration_s,
    )

    approved_proposal = ActionProposal(
        channel=ch,
        band=allocated_band,
        freq_hz=proposal.freq_hz,
        gain_db=target_gain,
        q=clamped_q,
        bus=proposal.bus,
        target=proposal.target,
        reason=f"Cắt thăm dò bước {step_count} ({target_gain:+.1f}dB tại {proposal.freq_hz:.1f}Hz)",
    )

    return new_state, Decision(
        approved=True,
        proposal=approved_proposal,
        effective_gain_db=target_gain,
        is_probing=True,
        reason="Chấp thuận can thiệp hạ notch an toàn",
    )


def handle_manual_override(state: SafetyState, channel: int, now: float) -> SafetyState:
    """Khóa kênh trong 10 giây khi phát hiện Soundman vừa can thiệp bằng tay trên bàn mixer."""
    new_locks = dict(state.channel_locks)
    new_locks[channel] = now + state.lock_duration_s

    return SafetyState(
        active_notches=state.active_notches,
        channel_locks=new_locks,
        transaction_history=state.transaction_history,
        whitelist=state.whitelist,
        allowed_bands=state.allowed_bands,
        max_boost_db=state.max_boost_db,
        max_cut_db=state.max_cut_db,
        probe_step_db=state.probe_step_db,
        probe_wait_ms=state.probe_wait_ms,
        max_transactions_per_sec=state.max_transactions_per_sec,
        lock_duration_s=state.lock_duration_s,
    )


def panic_rollback(state: SafetyState, now: float) -> Tuple[SafetyState, List[ActionProposal]]:
    """Cơ chế Dừng khẩn cấp / Rollback: Hoàn tác toàn bộ các notch hệ thống về 0 dB trong 1 thao tác."""
    rollback_proposals: List[ActionProposal] = []

    for (ch, band), notch in state.active_notches.items():
        rollback_proposals.append(
            ActionProposal(
                channel=ch,
                band=band,
                freq_hz=notch.freq_hz,
                gain_db=0.0,  # Nhả về phẳng
                q=notch.q,
                target="main" if ch == 0 else "ch",
                reason="PANIC: Hoàn tác toàn bộ notch về 0 dB",
            )
        )

    # Xóa sạch toàn bộ notch hoạt động
    new_state = SafetyState(
        active_notches={},
        channel_locks=state.channel_locks,
        transaction_history=state.transaction_history + (now,),
        whitelist=state.whitelist,
        allowed_bands=state.allowed_bands,
        max_boost_db=state.max_boost_db,
        max_cut_db=state.max_cut_db,
        probe_step_db=state.probe_step_db,
        probe_wait_ms=state.probe_wait_ms,
        max_transactions_per_sec=state.max_transactions_per_sec,
        lock_duration_s=state.lock_duration_s,
    )

    return new_state, rollback_proposals
