"""Kiểm thử benchmark thuật toán FeedbackDetector trên dữ liệu mô phỏng thực tế."""

import time
import numpy as np
import pytest
from auto_sound.dsp.detector import FeedbackDetector
from auto_sound.sim.room import RoomSimulator


def run_detector_on_audio(
    detector: FeedbackDetector,
    channel: int,
    audio: np.ndarray,
    hop_size: int = 512,
    feedback_start_sample: int = 0,
):
    """Đưa chuỗi âm thanh liên tục vào detector qua từng hop 512 mẫu (cửa sổ 2048).
    
    Đo thời gian từ thời điểm tiếng hú bắt đầu (feedback_start_sample) đến thời điểm
    kết thúc khung phân tích FFT mà tại đó detector phát ra tín hiệu.
    """
    detector.reset_channel(channel)
    frame_size = detector.frame_size
    detected_proposals = []
    detection_end_sample = None

    for start in range(0, len(audio) - frame_size, hop_size):
        frame = audio[start : start + frame_size]
        proposals = detector.process_channel_frame(channel, frame)
        if proposals:
            if detection_end_sample is None:
                detection_end_sample = start + frame_size
            detected_proposals.extend(proposals)

    # Tính độ trễ trung thực bao gồm cả độ dài cửa sổ FFT và các hop xác nhận
    detection_time_ms = (
        ((detection_end_sample - feedback_start_sample) / detector.sample_rate * 1000.0)
        if detection_end_sample is not None
        else None
    )
    return detected_proposals, detection_time_ms


def test_detector_benchmark_recall_and_false_positives() -> None:
    """Benchmark toàn diện đo lường Recall, False Positives và Thời gian phát hiện."""
    sim = RoomSimulator(sample_rate=48000, seed=123)
    detector = FeedbackDetector(sample_rate=48000, confirmation_frames=3)

    # 1. TẬP MẪU DƯƠNG TÍNH: 20 tần số hú khác nhau từ trầm đến cao
    test_freqs = [
        250.0, 315.0, 400.0, 500.0, 630.0, 800.0, 1000.0, 1250.0, 1600.0, 2000.0,
        2500.0, 3150.0, 4000.0, 5000.0, 6300.0, 7500.0, 8000.0, 9000.0, 10000.0, 12000.0
    ]
    positive_count = len(test_freqs)
    true_positives = 0
    detection_times = []

    print("\n--- BẮT ĐẦU CHẠY BENCHMARK DƯƠNG TÍNH (HÚ THẬT) ---")
    for f in test_freqs:
        # Sinh 0.6 giây tín hiệu vòng lặp hú
        audio = sim.generate_feedback_loop(duration_s=0.6, target_freq_hz=f)
        proposals, t_detect = run_detector_on_audio(detector, channel=1, audio=audio)

        if proposals:
            detected_f = proposals[0].freq_hz
            # Cho phép sai số tần số +-3% do độ phân giải bin
            if abs(detected_f - f) / f <= 0.03:
                true_positives += 1
                detection_times.append(t_detect)
                print(f"  [ĐẠT] Tần số {f:.0f}Hz -> Bắt được {detected_f:.1f}Hz trong {t_detect:.1f}ms")
            else:
                print(f"  [LỆCH] Tần số {f:.0f}Hz -> Bắt nhầm sang {detected_f:.1f}Hz")
        else:
            print(f"  [TRƯỢT] Tần số {f:.0f}Hz -> Không bắt được")

    recall = true_positives / positive_count
    avg_detection_time = np.mean(detection_times) if detection_times else 0.0

    # 2. TẬP MẪU ÂM TÍNH (NHẠC CỤ & GIỌNG HÁT KHÔNG PHẢI HÚ): 20 mẫu
    false_positives = 0
    print("\n--- BẮT ĐẦU CHẠY BENCHMARK ÂM TÍNH (NHẠC CỤ & GIỌNG HÁT) ---")

    # 5 ca giọng hát có vibrato
    for f in [220.0, 440.0, 880.0, 1200.0, 1500.0]:
        vocal = sim.generate_vocal_sustain(duration_s=0.8, freq_hz=f, with_vibrato=True)
        props, _ = run_detector_on_audio(detector, channel=2, audio=vocal)
        if props:
            false_positives += 1
            print(f"  [BÁO NHẦM] Giọng hát Vibrato {f}Hz bị nhận nhầm thành hú!")

    # 5 ca giọng hát nốt thẳng không vibrato
    for f in [220.0, 440.0, 660.0, 880.0, 1100.0]:
        vocal_straight = sim.generate_vocal_sustain(duration_s=0.8, freq_hz=f, with_vibrato=False)
        props, _ = run_detector_on_audio(detector, channel=3, audio=vocal_straight)
        if props:
            false_positives += 1
            print(f"  [BÁO NHẦM] Giọng hát nốt thẳng {f}Hz bị nhận nhầm thành hú!")

    # 5 ca guitar distortion
    for f in [110.0, 220.0, 330.0, 440.0, 660.0]:
        guitar = sim.generate_guitar_distortion(duration_s=0.8, note_hz=f)
        props, _ = run_detector_on_audio(detector, channel=4, audio=guitar)
        if props:
            false_positives += 1
            print(f"  [BÁO NHẦM] Guitar Distortion {f}Hz bị nhận nhầm thành hú!")

    # 5 ca cymbal crash
    for _ in range(5):
        cymbal = sim.generate_cymbal_crash(duration_s=0.8)
        props, _ = run_detector_on_audio(detector, channel=5, audio=cymbal)
        if props:
            false_positives += 1
            print("  [BÁO NHẦM] Cymbal Crash bị nhận nhầm thành hú!")

    p50_latency = float(np.percentile(detection_times, 50)) if detection_times else 0.0
    p95_latency = float(np.percentile(detection_times, 95)) if detection_times else 0.0
    max_latency = float(np.max(detection_times)) if detection_times else 0.0

    print("\n================ TỔNG HỢP KẾT QUẢ BENCHMARK ================")
    print(f"  Tổng số mẫu kiểm thử: 40 (20 hú, 20 âm nhạc/nhạc cụ)")
    print(f"  Độ nhạy (Recall): {recall * 100:.1f}% ({true_positives}/{positive_count})")
    print(f"  Số ca báo động giả (False Positives): {false_positives}/20")
    print(f"  Thời gian phát hiện trung bình (tính cả cửa sổ 2048 mẫu): {avg_detection_time:.1f} ms")
    print(f"  Thời gian phát hiện p50: {p50_latency:.1f} ms | p95: {p95_latency:.1f} ms | max: {max_latency:.1f} ms")
    print("============================================================")

    # Khẳng định ngưỡng chất lượng nghiêm ngặt:
    # 1. Recall >= 95% (ít nhất 19/20 ca hú được phát hiện)
    assert recall >= 0.95, f"Recall quá thấp: {recall * 100:.1f}%"
    # 2. False Positives = 0 (tuyệt đối không báo nhầm trên 20 ca nhạc cụ)
    assert false_positives == 0, f"Có {false_positives} ca báo động giả"
    # 3. Thời gian phát hiện (tính cả cửa sổ FFT 42.6ms và 3 frame) p95 <= 100 ms
    assert p95_latency <= 100.0, f"Độ trễ p95 quá chậm: {p95_latency:.1f}ms > 100ms"
    assert avg_detection_time <= 100.0, f"Thời gian phát hiện trung bình quá chậm: {avg_detection_time:.1f}ms"
