"""Kiểm thử tính năng can thiệp Notch trên Bus Aux/Monitor (Giai đoạn D2 & D3)."""

import pytest
from auto_sound.core.models import ActionProposal
from auto_sound.safety.controller import (
    ActiveNotch,
    SafetyState,
    check_auto_release,
    decide,
    handle_manual_override,
    panic_rollback,
)


def test_bus_notch_allocation_uses_band_5_or_6() -> None:
    """Can thiệp notch trên Bus 1 chỉ được dùng Band 5 hoặc Band 6."""
    state = SafetyState()
    now = 1000.0

    # Đề xuất cắt trên Bus 1 tại 3150 Hz
    prop1 = ActionProposal(
        channel=0,
        bus=1,
        target="bus",
        freq_hz=3150.0,
        gain_db=-3.0,
        q=8.0,
    )
    state, dec1 = decide(state, prop1, now)
    assert dec1.approved is True
    assert dec1.proposal is not None
    assert dec1.proposal.target == "bus"
    assert dec1.proposal.bus == 1
    # Band phân bổ phải là Band 5 hoặc 6 (không bao giờ chạm 1, 2, 3, 4)
    assert dec1.proposal.band in (5, 6)

    # Đề xuất cắt tiếp tần số thứ 2 trên Bus 1 tại 6300 Hz
    prop2 = ActionProposal(
        channel=0,
        bus=1,
        target="bus",
        freq_hz=6300.0,
        gain_db=-3.0,
        q=8.0,
    )
    state, dec2 = decide(state, prop2, now + 0.6)
    assert dec2.approved is True
    assert dec2.proposal is not None
    assert dec2.proposal.band in (5, 6)
    assert dec2.proposal.band != dec1.proposal.band


def test_bus_not_in_whitelist_rejected() -> None:
    """Bus không nằm trong bus_whitelist phải bị từ chối bảo vệ."""
    state = SafetyState(bus_whitelist={1, 2})  # Chỉ cho phép Bus 1, 2 (Monitor Ca sĩ)
    now = 1000.0

    # Can thiệp vào Bus 3 (In-ear Trống) -> Bị từ chối
    prop = ActionProposal(
        channel=0,
        bus=3,
        target="bus",
        freq_hz=2000.0,
        gain_db=-3.0,
        q=5.0,
    )
    state, dec = decide(state, prop, now)
    assert dec.approved is False
    assert "không nằm trong danh sách cho phép" in dec.reason


def test_bus_manual_override_locks_bus() -> None:
    """Khi Soundman chỉnh tay trên Bus, bus đó bị tạm khóa 10s."""
    state = SafetyState()
    now = 1000.0

    # Soundman vặn EQ trên Bus 2
    state = handle_manual_override(state, channel=0, now=now, target="bus", bus=2)

    # Hệ thống đề xuất cắt trên Bus 2 sau 3 giây -> Bị từ chối
    prop = ActionProposal(channel=0, bus=2, target="bus", freq_hz=4000.0, gain_db=-3.0, q=5.0)
    state, dec = decide(state, prop, now + 3.0)
    assert dec.approved is False
    assert "Bus 2 đang bị tạm khóa" in dec.reason

    # Sau 11 giây (hết hạn khóa) -> Được chấp thuận
    state, dec2 = decide(state, prop, now + 11.0)
    assert dec2.approved is True


def test_bus_exhaustion_reclaim_option_1() -> None:
    """Khi cả 2 band 5 và 6 trên Bus đã đầy, tái sử dụng band nông nhất."""
    state = SafetyState(reclaim_on_exhaustion=True)
    now = 1000.0

    # Lấp đầy Band 5 (-6dB) và Band 6 (-3dB) trên Bus 1
    state, _ = decide(state, ActionProposal(channel=0, bus=1, target="bus", freq_hz=1000.0, gain_db=-6.0, q=5.0), now)
    state, _ = decide(state, ActionProposal(channel=0, bus=1, target="bus", freq_hz=1000.0, gain_db=-6.0, q=5.0), now + 0.6)  # Bước 2: -6dB
    state, _ = decide(state, ActionProposal(channel=0, bus=1, target="bus", freq_hz=2000.0, gain_db=-3.0, q=5.0), now + 1.2)  # Band 6: -3dB

    # Tần số thứ 3 xuất hiện: 4000 Hz -> Tái sử dụng Band 6 vì độ cắt nông hơn (-3dB vs -6dB)
    state, dec3 = decide(state, ActionProposal(channel=0, bus=1, target="bus", freq_hz=4000.0, gain_db=-3.0, q=5.0), now + 1.8)
    assert dec3.approved is True
    assert dec3.proposal is not None
    assert dec3.proposal.band == 6
    assert "CẠN BAND" in dec3.reason


def test_bus_auto_release_towards_zero() -> None:
    """Notch trên Bus tự động nhả dần về 0 dB sau 20s ổn định."""
    state = SafetyState(auto_release_wait_s=20.0, auto_release_enabled=True)
    now = 1000.0

    # Cắt notch -3 dB trên Bus 1 Band 5
    state, dec = decide(state, ActionProposal(channel=0, bus=1, target="bus", freq_hz=1500.0, gain_db=-3.0, q=5.0), now)
    assert dec.approved is True
    band = dec.proposal.band

    # Sau 10s: chưa đến hạn 20s -> Không nhả
    state, props_early = check_auto_release(state, now + 10.0, step_db=1.0)
    assert len(props_early) == 0

    # Sau 21s: đã đến hạn -> Nhả 1 bước lên -2.0 dB
    state, props_step1 = check_auto_release(state, now + 21.0, step_db=1.0)
    assert len(props_step1) == 1
    assert props_step1[0].target == "bus"
    assert props_step1[0].bus == 1
    assert props_step1[0].band == band
    assert props_step1[0].gain_db == -2.0
