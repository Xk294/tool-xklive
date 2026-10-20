"""Kiểm thử toàn diện các luật an toàn và property-based testing cho Safety Controller."""

import pytest
from hypothesis import given, strategies as st
from auto_sound.core.models import ActionProposal
from auto_sound.safety.controller import (
    SafetyState,
    decide,
    handle_manual_override,
    panic_rollback,
)


def test_whitelist_rejection() -> None:
    state = SafetyState(whitelist={1, 2, 3})
    prop = ActionProposal(channel=4, freq_hz=1000.0, gain_db=-3.0, q=8.0)
    new_state, dec = decide(state, prop, now=10.0)

    assert dec.approved is False
    assert "Whitelist" in dec.reason


def test_manual_override_lock_10s() -> None:
    state = SafetyState()
    # Kỹ sư chỉnh tay kênh 2 ở thời điểm t = 5.0s
    state = handle_manual_override(state, channel=2, now=5.0)

    prop = ActionProposal(channel=2, freq_hz=1000.0, gain_db=-3.0, q=8.0)
    # Thử can thiệp ở t = 10.0s (vẫn trong khoảng khóa 10s: đến 15.0s)
    state, dec1 = decide(state, prop, now=10.0)
    assert dec1.approved is False
    assert "chỉnh tay" in dec1.reason

    # Thử lại ở t = 15.1s (hết khóa)
    state, dec2 = decide(state, prop, now=15.1)
    assert dec2.approved is True


def test_rate_limit_2_transactions_per_sec() -> None:
    state = SafetyState(max_transactions_per_sec=2.0)
    prop1 = ActionProposal(channel=1, freq_hz=1000.0, gain_db=-3.0, q=8.0)
    prop2 = ActionProposal(channel=2, freq_hz=2000.0, gain_db=-3.0, q=8.0)
    prop3 = ActionProposal(channel=3, freq_hz=3000.0, gain_db=-3.0, q=8.0)

    # Giao dịch 1 tại t = 1.0s -> OK
    state, d1 = decide(state, prop1, now=1.0)
    assert d1.approved is True

    # Giao dịch 2 tại t = 1.2s -> OK
    state, d2 = decide(state, prop2, now=1.2)
    assert d2.approved is True

    # Giao dịch 3 tại t = 1.5s (< 1.0s từ giao dịch 1) -> Bị từ chối
    state, d3 = decide(state, prop3, now=1.5)
    assert d3.approved is False
    assert "hạn mức" in d3.reason

    # Thử lại tại t = 2.1s (giao dịch 1 đã trôi qua hơn 1s) -> OK
    state, d4 = decide(state, prop3, now=2.1)
    assert d4.approved is True


def test_max_boost_guard() -> None:
    state = SafetyState(max_boost_db=4.0)
    prop = ActionProposal(channel=1, freq_hz=1000.0, gain_db=+5.0, q=8.0)
    state, dec = decide(state, prop, now=1.0)

    assert dec.approved is False
    assert "giới hạn an toàn" in dec.reason


def test_system_band_isolation_and_exhaustion() -> None:
    # Mặc định chỉ cho phép band 3 và 4
    state = SafetyState(allowed_bands={1: (3, 4)})

    prop1 = ActionProposal(channel=1, freq_hz=1000.0, gain_db=-3.0, q=8.0)
    state, d1 = decide(state, prop1, now=1.0)
    assert d1.approved is True
    assert d1.proposal.band == 3

    # Notch thứ hai tại tần số khác (2000Hz)
    prop2 = ActionProposal(channel=1, freq_hz=2000.0, gain_db=-3.0, q=8.0)
    state, d2 = decide(state, prop2, now=2.1)
    assert d2.approved is True
    assert d2.proposal.band == 4

    # Notch thứ ba tại tần số 3000Hz -> Hết band (không bao giờ đụng vào band 1-2 của soundman)
    prop3 = ActionProposal(channel=1, freq_hz=3000.0, gain_db=-3.0, q=8.0)
    state, d3 = decide(state, prop3, now=3.2)
    assert d3.approved is False
    assert "hết các band PEQ" in d3.reason


def test_incremental_probing_step() -> None:
    state = SafetyState(probe_step_db=-3.0, max_cut_db=-12.0)
    prop = ActionProposal(channel=1, freq_hz=1000.0, gain_db=-3.0, q=8.0)

    # Lần 1: Cắt -3dB
    state, d1 = decide(state, prop, now=1.0)
    assert d1.approved is True
    assert d1.effective_gain_db == -3.0

    # Lần 2: Cắt tiếp -3dB thành -6dB
    state, d2 = decide(state, prop, now=2.1)
    assert d2.approved is True
    assert d2.effective_gain_db == -6.0

    # Lần 3: Cắt thành -9dB
    state, d3 = decide(state, prop, now=3.2)
    assert d3.effective_gain_db == -9.0

    # Lần 4: Cắt thành -12dB
    state, d4 = decide(state, prop, now=4.3)
    assert d4.effective_gain_db == -12.0

    # Lần 5: Chạm đáy max_cut_db (-12dB), không cắt sâu hơn
    state, d5 = decide(state, prop, now=5.4)
    assert d5.effective_gain_db == -12.0


def test_panic_rollback() -> None:
    state = SafetyState()
    # Tạo 2 notch hoạt động
    prop1 = ActionProposal(channel=1, freq_hz=1000.0, gain_db=-3.0, q=8.0)
    prop2 = ActionProposal(channel=2, freq_hz=2000.0, gain_db=-3.0, q=8.0)
    state, _ = decide(state, prop1, now=1.0)
    state, _ = decide(state, prop2, now=1.2)
    assert len(state.active_notches) == 2

    # Kích hoạt PANIC
    state, rollback_proposals = panic_rollback(state, now=2.0)
    assert len(rollback_proposals) == 2
    assert len(state.active_notches) == 0

    # Mọi proposal hoàn tác đều có gain_db = 0.0 (nhả về phẳng)
    for p in rollback_proposals:
        assert p.gain_db == 0.0


# Property-based test với Hypothesis
@given(
    st.lists(
        st.tuples(
            st.integers(min_value=1, max_value=20),        # channel
            st.floats(min_value=20.0, max_value=20000.0), # freq
            st.floats(min_value=-20.0, max_value=10.0),   # gain
            st.floats(min_value=0.1, max_value=15.0),     # q
            st.floats(min_value=0.0, max_value=100.0),    # delta_t
        ),
        min_size=1,
        max_size=30,
    )
)
def test_safety_invariants_property_based(event_list) -> None:
    """Kiểm thử bất biến: Dù nhận chuỗi sự kiện ngẫu nhiên nào, không bao giờ vi phạm luật an toàn."""
    state = SafetyState(
        whitelist=set(range(1, 17)),
        allowed_bands={ch: (3, 4) for ch in range(1, 17)},
        max_boost_db=4.0,
        max_cut_db=-12.0,
    )
    current_time = 0.0

    for ch, freq, gain, q, dt in event_list:
        current_time += dt
        prop = ActionProposal(channel=ch, freq_hz=freq, gain_db=gain, q=q)
        state, decision = decide(state, prop, now=current_time)

        if decision.approved:
            approved_p = decision.proposal
            assert approved_p is not None
            # Bất biến 1: Kênh phải nằm trong Whitelist
            assert approved_p.channel in state.whitelist
            # Bất biến 2: Chỉ được phép dùng band 3 hoặc 4 (không bao giờ đụng vào band 1-2)
            assert approved_p.band in (3, 4)
            # Bất biến 3: Không bao giờ boost quá +4 dB
            assert approved_p.gain_db <= 4.0
            # Bất biến 4: Không bao giờ cắt sâu hơn -12 dB
            assert approved_p.gain_db >= -12.0
            # Bất biến 5: Q không vượt quá 10.0
            assert approved_p.q <= 10.0
