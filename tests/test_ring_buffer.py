"""Kiểm thử tính toàn vẹn, tính không cấp phát (zero-allocation) và luồng ảo của AudioRingBuffer."""

import tracemalloc
import time
import numpy as np
import pytest
from auto_sound.audio.ring_buffer import AudioRingBuffer
from auto_sound.audio.io import AudioCapture


def test_ring_buffer_basic_read_write() -> None:
    rb = AudioRingBuffer(num_channels=18, capacity_frames=1024)
    data_in = np.ones((256, 18), dtype=np.float32) * 42.0

    written = rb.write(data_in)
    assert written == 256
    assert rb.available_read() == 256

    data_out = np.zeros((256, 18), dtype=np.float32)
    read_frames = rb.read(data_out)
    assert read_frames == 256
    assert rb.available_read() == 0
    assert np.allclose(data_out, 42.0)


def test_ring_buffer_wraparound() -> None:
    capacity = 1000
    rb = AudioRingBuffer(num_channels=2, capacity_frames=capacity)

    # Đưa con trỏ ghi gần chạm đáy (800)
    data1 = np.ones((800, 2), dtype=np.float32)
    rb.write(data1)
    out1 = np.zeros((800, 2), dtype=np.float32)
    rb.read(out1)

    # Bây giờ write_pos = 800, read_pos = 800, available = 0
    # Ghi 400 frames (sẽ vượt quá 1000, quấn 200 về đầu mảng)
    data2 = np.arange(400, dtype=np.float32).reshape(400, 1)
    data2 = np.repeat(data2, 2, axis=1)

    written = rb.write(data2)
    assert written == 400

    out2 = np.zeros((400, 2), dtype=np.float32)
    read_frames = rb.read(out2)
    assert read_frames == 400
    assert np.array_equal(out2, data2)


def test_ring_buffer_overflow_xrun() -> None:
    capacity = 500
    rb = AudioRingBuffer(num_channels=1, capacity_frames=capacity)

    data = np.ones((600, 1), dtype=np.float32)
    written = rb.write(data)

    assert written == 500
    assert rb.xrun_count[0] == 1
    assert rb.available_read() == 500


def test_ring_buffer_zero_allocation_in_steady_state() -> None:
    """Kiểm tra không phát sinh cấp phát bộ nhớ (tracemalloc) trong vòng lặp ghi/đọc ổn định."""
    rb = AudioRingBuffer(num_channels=18, capacity_frames=4096)
    block_in = np.zeros((512, 18), dtype=np.float32)
    block_out = np.zeros((512, 18), dtype=np.float32)

    # Khởi động làm ấm (warm-up)
    for _ in range(10):
        rb.write(block_in)
        rb.read(block_out)

    tracemalloc.start()
    snapshot1 = tracemalloc.take_snapshot()

    # Chạy 100 chu kỳ ghi đọc liên tục
    for _ in range(100):
        rb.write(block_in)
        rb.read(block_out)

    snapshot2 = tracemalloc.take_snapshot()
    tracemalloc.stop()

    stats = snapshot2.compare_to(snapshot1, "lineno")
    total_diff = sum(stat.size_diff for stat in stats if "ring_buffer.py" in stat.traceback[0].filename)
    # Khẳng định chênh lệch bộ nhớ xấp xỉ 0 (<= 64 byte đối tượng lát cắt tạm, không rò rỉ qua 100 vòng lặp)
    assert total_diff <= 64


def test_audio_continuity_and_no_dropped_samples() -> None:
    """Kiểm tra chuỗi số tăng dần liên tục: không bị mất mẫu và không bị lặp mẫu."""
    rb = AudioRingBuffer(num_channels=1, capacity_frames=10000)
    total_samples = 4000
    block_size = 200

    write_buffer = np.zeros((block_size, 1), dtype=np.float32)
    read_buffer = np.zeros((block_size, 1), dtype=np.float32)
    received_samples = []

    for i in range(0, total_samples, block_size):
        write_buffer[:, 0] = np.arange(i, i + block_size, dtype=np.float32)
        rb.write(write_buffer)

        n = rb.read(read_buffer)
        received_samples.extend(read_buffer[:n, 0].tolist())

    assert len(received_samples) == total_samples
    diffs = np.diff(received_samples)
    assert np.all(diffs == 1.0)


def test_audio_capture_virtual_mode() -> None:
    """Kiểm tra AudioCapture ở chế độ nguồn ảo chạy trơn tru không lỗi xrun."""
    cap = AudioCapture(channels=18, sample_rate=48000, is_virtual=True)
    cap.start()

    time.sleep(0.3)  # Để nguồn ảo bơm vài block vào buffer
    cap.stop()

    assert cap.xrun_stats[0] == 0
    assert cap.ring_buffer.available_read() > 0

    out = np.zeros((256, 18), dtype=np.float32)
    n = cap.ring_buffer.read(out)
    assert n == 256
