"""Ring buffer SPSC (Single Producer, Single Consumer) không khóa, cấp phát sẵn cho âm thanh đa kênh."""

from __future__ import annotations
import numpy as np


class AudioRingBuffer:
    """Bộ đệm vòng đa kênh cấp phát sẵn phục vụ thu âm thời gian thực với độ trễ thấp."""

    def __init__(self, num_channels: int = 18, capacity_frames: int = 48000 * 2) -> None:
        self.num_channels = int(num_channels)
        self.capacity = int(capacity_frames)

        # Mảng bộ nhớ chính cấp phát sẵn một lần duy nhất lúc khởi tạo
        self._buffer = np.zeros((self.capacity, self.num_channels), dtype=np.float32)

        self._write_pos = 0
        self._read_pos = 0
        self._available = 0

        # Mảng numpy 1 phần tử lưu biến đếm xrun (tránh cấp phát đối tượng Python trong callback)
        self.xrun_count = np.zeros(1, dtype=np.int64)

    def write(self, data: np.ndarray) -> int:
        """Ghi dữ liệu âm thanh (frames, channels) vào ring buffer không cấp phát bộ nhớ mới.
        
        Sử dụng np.copyto trực tiếp vào các lát cắt (slices) của mảng cấp phát sẵn.
        """
        frames_to_write = data.shape[0]
        if frames_to_write == 0:
            return 0

        free_space = self.capacity - self._available
        if frames_to_write > free_space:
            # Tràn bộ đệm (Overflow): Tăng biến đếm xrun và chỉ ghi phần chứa được
            self.xrun_count[0] += 1
            frames_to_write = free_space
            if frames_to_write == 0:
                return 0

        # Xử lý trường hợp ghi chạm đáy và vòng lại đầu mảng (wraparound)
        tail_space = self.capacity - self._write_pos
        if frames_to_write <= tail_space:
            np.copyto(self._buffer[self._write_pos : self._write_pos + frames_to_write], data[:frames_to_write])
            self._write_pos = (self._write_pos + frames_to_write) % self.capacity
        else:
            first_chunk = tail_space
            second_chunk = frames_to_write - first_chunk
            np.copyto(self._buffer[self._write_pos : self.capacity], data[:first_chunk])
            np.copyto(self._buffer[0 : second_chunk], data[first_chunk:frames_to_write])
            self._write_pos = second_chunk

        self._available += frames_to_write
        return frames_to_write

    def read(self, out: np.ndarray) -> int:
        """Đọc dữ liệu từ ring buffer vào mảng đích out cấp phát sẵn.
        
        Trả về số lượng frames thực tế đọc được.
        """
        requested = out.shape[0]
        frames_to_read = min(requested, self._available)
        if frames_to_read == 0:
            return 0

        tail_available = self.capacity - self._read_pos
        if frames_to_read <= tail_available:
            np.copyto(out[:frames_to_read], self._buffer[self._read_pos : self._read_pos + frames_to_read])
            self._read_pos = (self._read_pos + frames_to_read) % self.capacity
        else:
            first_chunk = tail_available
            second_chunk = frames_to_read - first_chunk
            np.copyto(out[:first_chunk], self._buffer[self._read_pos : self.capacity])
            np.copyto(out[first_chunk:frames_to_read], self._buffer[0 : second_chunk])
            self._read_pos = second_chunk

        self._available -= frames_to_read
        return frames_to_read

    def available_read(self) -> int:
        """Số lượng frames đang sẵn sàng để đọc."""
        return self._available

    def available_write(self) -> int:
        """Số lượng frames còn trống có thể ghi."""
        return self.capacity - self._available

    def reset(self) -> None:
        """Xóa sạch vị trí đọc/ghi và đặt lại bộ đếm."""
        self._write_pos = 0
        self._read_pos = 0
        self._available = 0
        self.xrun_count[0] = 0
