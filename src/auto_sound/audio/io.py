"""Module thu âm thanh 18 kênh từ USB của Behringer XR18 với callback zero-allocation."""

from __future__ import annotations
import threading
import time
from typing import Callable, Optional
import numpy as np
import sounddevice as sd
from auto_sound.audio.ring_buffer import AudioRingBuffer


class AudioCapture:
    """Thu nhận luồng âm thanh đa kênh thời gian thực từ phần cứng USB hoặc nguồn ảo."""

    def __init__(
        self,
        channels: int = 18,
        sample_rate: int = 48000,
        buffer_capacity_frames: int = 48000 * 2,
        device: Optional[str | int] = None,
        is_virtual: bool = False,
        virtual_generator: Optional[Callable[[int, int], np.ndarray]] = None,
    ) -> None:
        self.channels = int(channels)
        self.sample_rate = int(sample_rate)
        self.device = device
        self.is_virtual = is_virtual
        self.virtual_generator = virtual_generator

        self.ring_buffer = AudioRingBuffer(num_channels=self.channels, capacity_frames=buffer_capacity_frames)
        self.xrun_stats = np.zeros(1, dtype=np.int64)

        self._stream: Optional[sd.InputStream] = None
        self._virtual_thread: Optional[threading.Thread] = None
        self._running = False

        # Mảng đệm nạp trước cho nguồn ảo (tránh cấp phát trong luồng phát ảo)
        self._preallocated_block = np.zeros((512, self.channels), dtype=np.float32)

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: dict,
        status: sd.CallbackFlags,
    ) -> None:
        """Callback âm thanh thời gian thực.
        
        Quy tắc nghiêm ngặt: Tuyệt đối không malloc/cấp phát bộ nhớ, không print, không lock.
        """
        if status:
            self.xrun_stats[0] += 1
        if indata.shape[1] < self.channels:
            self._preallocated_block[:frames, : indata.shape[1]] = indata
            self._preallocated_block[:frames, indata.shape[1] :] = 0.0
            self.ring_buffer.write(self._preallocated_block[:frames, :])
        else:
            self.ring_buffer.write(indata)

    def _virtual_worker(self) -> None:
        """Bộ sinh tín hiệu âm thanh ảo phục vụ kiểm thử CI khi không có soundcard vật lý."""
        block_size = self._preallocated_block.shape[0]
        block_duration = block_size / self.sample_rate
        sample_counter = 0

        while self._running:
            t0 = time.perf_counter()
            if self.virtual_generator:
                generated = self.virtual_generator(block_size, sample_counter)
                np.copyto(self._preallocated_block, generated)
            else:
                # Mặc định: Sinh chuỗi số tăng dần liên tục để kiểm tra mất/trùng mẫu
                for ch in range(self.channels):
                    self._preallocated_block[:, ch] = np.arange(
                        sample_counter, sample_counter + block_size, dtype=np.float32
                    )

            self.ring_buffer.write(self._preallocated_block)
            sample_counter += block_size

            elapsed = time.perf_counter() - t0
            sleep_time = block_duration - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def start(self) -> None:
        """Bắt đầu thu âm thanh."""
        if self._running:
            return

        self._running = True
        if self.is_virtual:
            self._virtual_thread = threading.Thread(target=self._virtual_worker, daemon=True)
            self._virtual_thread.start()
        else:
            try:
                # Tự động thích ứng số kênh thực tế của phần cứng đầu vào (ví dụ micro mono/stereo)
                actual_in_channels = self.channels
                try:
                    dev_info = sd.query_devices(self.device, "input")
                    max_in = int(dev_info.get("max_input_channels", self.channels))
                    if max_in > 0:
                        actual_in_channels = min(self.channels, max_in)
                except Exception:
                    pass

                self._stream = sd.InputStream(
                    samplerate=self.sample_rate,
                    channels=actual_in_channels,
                    dtype="float32",
                    blocksize=512,
                    device=self.device,
                    callback=self._audio_callback,
                )
                self._stream.start()
            except Exception as e:
                self._running = False
                raise RuntimeError(f"Không thể mở thiết bị âm thanh USB '{self.device}': {e}") from e

    def stop(self) -> None:
        """Dừng thu âm thanh và giải phóng luồng."""
        self._running = False
        if self._virtual_thread and self._virtual_thread.is_alive():
            self._virtual_thread.join(timeout=1.0)
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
