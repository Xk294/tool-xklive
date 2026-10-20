"""Kiểm thử tích hợp đầu-cuối (End-to-End Integration Test):
Audio IO ảo -> Feedback Detector -> Safety Controller -> Verified Write -> FakeXR18.
"""

import time
import numpy as np
import pytest
from auto_sound.audio.io import AudioCapture
from auto_sound.core.models import ConnectionState
from auto_sound.dsp.detector import FeedbackDetector
from auto_sound.mixer.fake import FakeXR18
from auto_sound.mixer.parameter_mapper import ParameterMapper
from auto_sound.mixer.xair import XAirClient
from auto_sound.safety.controller import SafetyState, decide
from auto_sound.sim.room import RoomSimulator


def test_end_to_end_feedback_suppression_loop() -> None:
    """Kiểm tra khép kín toàn bộ chu trình xử lý âm thanh tự động."""
    # 1. Khởi động mixer giả lập FakeXR18
    fake_mixer = FakeXR18(host="127.0.0.1", port=0)
    fake_mixer.start()

    # 2. Kết nối XAirClient
    mapper = ParameterMapper.from_profile({
        "eq": {
            "freq_min_hz": 20.0, "freq_max_hz": 20000.0, "freq_steps": 201,
            "gain_min_db": -15.0, "gain_max_db": 15.0, "gain_steps": 121,
            "q_min": 0.3, "q_max": 10.0, "q_steps": 72,
        }
    })
    client = XAirClient(ip=fake_mixer.host, port=fake_mixer.port, mapper=mapper, timeout_s=1.0)
    assert client.connect() is True
    assert client.get_state() == ConnectionState.CONNECTED

    # 3. Chuẩn bị bộ sinh tiếng hú thực tế trên Kênh 2 tại 2500 Hz
    sim = RoomSimulator(sample_rate=48000, seed=42)
    feedback_audio_ch2 = sim.generate_feedback_loop(duration_s=1.5, target_freq_hz=2500.0)

    def virtual_audio_source(frames: int, counter: int) -> np.ndarray:
        block = np.zeros((frames, 18), dtype=np.float32)
        end_idx = min(len(feedback_audio_ch2), counter + frames)
        if counter < len(feedback_audio_ch2):
            chunk_len = end_idx - counter
            block[:chunk_len, 1] = feedback_audio_ch2[counter:end_idx]  # Gán vào kênh 2 (index 1)
        return block

    audio_io = AudioCapture(
        channels=18,
        sample_rate=48000,
        is_virtual=True,
        virtual_generator=virtual_audio_source,
    )
    audio_io.start()

    detector = FeedbackDetector(sample_rate=48000, confirmation_frames=3)
    safety_state = SafetyState(
        whitelist={1, 2, 3, 4},
        allowed_bands={ch: (3, 4) for ch in range(1, 17)},
    )

    # 4. Chạy vòng lặp xử lý âm thanh trong 0.8 giây
    read_buffer = np.zeros((512, 18), dtype=np.float32)
    rolling_ch2 = np.zeros(2048, dtype=np.float32)
    applied_notch = False

    t_start = time.time()
    while time.time() - t_start < 1.0:
        if audio_io.ring_buffer.available_read() >= 512:
            audio_io.ring_buffer.read(read_buffer)
            # Cập nhật khung trượt 2048 mẫu cho Kênh 2
            rolling_ch2[: 2048 - 512] = rolling_ch2[512:]
            rolling_ch2[2048 - 512 :] = read_buffer[:, 1]

            # Dò hú trên Kênh 2
            proposals = detector.process_channel_frame(channel=2, frame_samples=rolling_ch2)
            for prop in proposals:
                # Kiểm duyệt qua Safety Controller
                safety_state, decision = decide(safety_state, prop, now=time.time())
                if decision.approved and decision.proposal:
                    p = decision.proposal
                    assert p.band is not None
                    # Gửi lệnh PEQ sang mixer và xác minh
                    ok = client.set_peq(
                        channel=p.channel,
                        band=p.band,
                        freq_hz=p.freq_hz,
                        gain_db=p.gain_db,
                        q=p.q,
                        is_on=True,
                    )
                    assert ok is True
                    applied_notch = True
                    break

        if applied_notch:
            break
        time.sleep(0.01)

    # Khẳng định hệ thống đã tự động phát hiện và hạ notch thành công
    assert applied_notch is True

    # 5. Đọc lại trực tiếp từ Mixer để xác minh kết quả ghi (Verified Readback)
    peq_readback = client.get_peq(channel=2, band=3)
    assert peq_readback is not None
    assert peq_readback.channel == 2
    assert peq_readback.band == 3
    # Tần số đọc lại phải tiệm cận 2500 Hz (dung sai +-3%)
    assert pytest.approx(peq_readback.freq_hz, rel=0.03) == 2500.0
    # Gain đọc lại phải là mức cắt thăm dò -3.0 dB
    assert pytest.approx(peq_readback.gain_db, abs=0.5) == -3.0
    assert peq_readback.is_on is True

    # Dọn dẹp tài nguyên
    audio_io.stop()
    client.disconnect()
    fake_mixer.stop()
