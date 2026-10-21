"""Kiểm thử bộ định vị nguồn hú hai nhân tố (Two-Factor Localizer - Giai đoạn D1)."""

import numpy as np
import pytest
from auto_sound.dsp.localizer import (
    RoutingSnapshot,
    TwoFactorLocalizer,
)


@pytest.fixture
def localizer() -> TwoFactorLocalizer:
    return TwoFactorLocalizer(sample_rate=48000, frame_size=2048)


def test_single_mic_howling_identified(localizer: TwoFactorLocalizer) -> None:
    """Kiểm tra micro đơn có năng lượng f0 cao được xác định chính xác vị trí số 1."""
    f0 = 2500.0  # 2.5 kHz
    t = np.arange(2048) / 48000.0

    frames = {}
    for ch in range(1, 17):
        frames[ch] = 0.001 * np.random.randn(2048)  # Nhiễu trắng nền rất nhỏ

    # Kênh 3 bị hú 2500 Hz biên độ lớn
    frames[3] = 0.5 * np.sin(2 * np.pi * f0 * t)

    routing = RoutingSnapshot()
    result = localizer.localize(frames, f0_hz=f0, routing=routing)

    assert result.top_candidate is not None
    assert result.top_candidate.channel == 3
    assert result.top_candidate.score > 0.6
    assert result.is_ambiguous is False
    assert result.recommended_mode == "auto"


def test_multiple_mics_bleeding_resolved_by_routing(localizer: TwoFactorLocalizer) -> None:
    """Kịch bản âm thanh hú lọt vào cả Mic 1 và Mic 2, nhưng chỉ Mic 1 send lớn vào Monitor Bus 1."""
    f0 = 3150.0
    t = np.arange(2048) / 48000.0

    frames = {ch: 0.001 * np.random.randn(2048) for ch in range(1, 17)}
    # Cả Mic 1 và Mic 2 đều thu được tiếng hú (Mic 1 gần loa hơn một chút)
    frames[1] = 0.40 * np.sin(2 * np.pi * f0 * t)
    frames[2] = 0.35 * np.sin(2 * np.pi * f0 * t)

    routing = RoutingSnapshot()
    # Mic 1 send mạnh vào Bus 1 (0.85 ~ +2 dB)
    routing.bus_sends[(1, 1)] = 0.85
    # Mic 2 chỉ send nhẹ vào Bus 1 (0.20 ~ -14 dB)
    routing.bus_sends[(2, 1)] = 0.20

    result = localizer.localize(frames, f0_hz=f0, routing=routing, suspected_bus=1)

    assert result.top_candidate is not None
    assert result.top_candidate.channel == 1
    assert result.top_candidate.bus == 1
    # Ứng viên thứ 2 là Kênh 2 trên Bus 1 với điểm thấp hơn đáng kể
    assert result.candidates[1].channel == 2
    assert result.top_candidate.score > result.candidates[1].score


def test_ambiguous_case_downgrades_to_semi(localizer: TwoFactorLocalizer) -> None:
    """Khi 2 mic có năng lượng và routing gần giống hệt nhau -> Báo mơ hồ và chuyển sang SEMI."""
    f0 = 1000.0
    t = np.arange(2048) / 48000.0

    frames = {ch: 0.001 * np.random.randn(2048) for ch in range(1, 17)}
    # Hai mic sinh đôi có biên độ bằng nhau tuyệt đối
    frames[1] = 0.30 * np.sin(2 * np.pi * f0 * t)
    frames[2] = 0.30 * np.sin(2 * np.pi * f0 * t)

    routing = RoutingSnapshot()
    routing.bus_sends[(1, 1)] = 0.75
    routing.bus_sends[(2, 1)] = 0.75

    result = localizer.localize(frames, f0_hz=f0, routing=routing, suspected_bus=1)

    assert result.is_ambiguous is True
    assert result.recommended_mode == "semi"
    assert result.ambiguity_delta < 0.05


def test_muted_channel_receives_zero_score(localizer: TwoFactorLocalizer) -> None:
    """Kênh đang Mute không bao giờ bị coi là nguồn gây vòng hồi tiếp âm học."""
    f0 = 4000.0
    t = np.arange(2048) / 48000.0

    frames = {ch: 0.001 * np.random.randn(2048) for ch in range(1, 17)}
    # Kênh 4 có biên độ rất lớn nhưng đang bị MUTE trên mixer
    frames[4] = 0.80 * np.sin(2 * np.pi * f0 * t)
    frames[5] = 0.20 * np.sin(2 * np.pi * f0 * t)

    routing = RoutingSnapshot()
    routing.channel_on[4] = False  # Mute Kênh 4
    routing.channel_on[5] = True   # Bật Kênh 5

    result = localizer.localize(frames, f0_hz=f0, routing=routing, suspected_bus=1)

    # Kênh 5 phải được chọn thay vì Kênh 4
    assert result.top_candidate is not None
    assert result.top_candidate.channel == 5

    # Tìm lại ứng viên kênh 4 để xác minh score = 0.0
    cand_4 = [c for c in result.candidates if c.channel == 4 and c.bus == 1][0]
    assert cand_4.score == 0.0
    assert cand_4.is_channel_muted is True
