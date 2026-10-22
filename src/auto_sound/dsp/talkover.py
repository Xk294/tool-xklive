"""Module Smart FX Auto-Talkover / Auto-Ducking (Giai đoạn 4).

Nguyên tắc:
- Tự động hạ hoặc ngắt FX Return (Reverb / Delay) khi ca sĩ/MC giao lưu nói chuyện và nhạc beat dừng.
- Khi nhạc nổi lên hoặc bắt đầu hát lại -> Fade-in FX Return mượt mà trong 300ms.
- Bộ điều tốc (Rate Limiter) riêng cho Fader FX để đảm bảo chuyển động mượt mà không bị kẹp 2 tx/s của PEQ.
- Hysteresis và Hold Time (1.0 - 3.0s) ngăn hiện tượng nhấp nháy (chattering).
- Ưu tiên độ chính xác tuyệt đối: Thà không kích hoạt còn hơn dập reverb nhầm giữa bài hát!
"""

from __future__ import annotations
from dataclasses import dataclass, field
import time
from typing import Dict, List, Optional, Tuple


@dataclass
class TalkoverConfig:
    """Cấu hình cho thuật toán Smart FX Talkover."""
    enabled: bool = False                  # Mặc định TẮT (an toàn tuyệt đối)
    mic_channel: int = 1                   # Kênh micro chính (Lead Vocal / MC)
    music_channels: List[int] = field(default_factory=lambda: [17, 18])  # Kênh nhạc nền (Stereo In)
    fx_return_channel: int = 1             # Kênh FX Return cần duck (mặc định FX 1: Reverb)
    
    # Ngưỡng phát hiện
    mic_speech_threshold_dbfs: float = -42.0  # Ngưỡng nhận diện giọng nói
    music_silence_threshold_dbfs: float = -48.0 # Ngưỡng nhận diện nhạc dừng (im lặng)
    
    # Thời gian giữ và làm mượt
    hold_time_s: float = 1.5               # Thời gian giữ Speech Mode sau tiếng nói cuối cùng (1.5s)
    fade_duration_ms: float = 300.0        # Thời gian fade-down / fade-in (300 ms)
    ducking_depth_db: float = -18.0        # Độ sâu giảm fader (-18 dB hoặc Mute hoàn toàn)
    use_hard_mute_fallback: bool = False   # Hạ cấp sang Mute/Unmute nếu mạng trễ


class TalkoverController:
    """Bộ điều khiển trạng thái Talkover và nội suy Fader Ramp."""

    def __init__(self, config: Optional[TalkoverConfig] = None) -> None:
        self.config = config or TalkoverConfig()
        self.is_ducked: bool = False
        self.last_speech_time: float = 0.0

        # Giá trị Fader FX Return gốc đọc từ mixer
        self.original_fader_val: float = 0.75   # ~0 dB trên X-Air
        self.ducked_fader_val: float = 0.40     # ~-18 dB
        self.current_fader_val: float = 0.75

        # Quản lý đường cong fade (Fader Ramp Generator)
        self._fade_start_val: float = 0.75
        self._fade_target_val: float = 0.75
        self._fade_start_time: float = 0.0
        self._is_fading: bool = False

    def set_original_fader(self, val: float) -> None:
        """Lưu lại giá trị fader gốc đọc từ mixer trước khi can thiệp."""
        self.original_fader_val = val
        # Tính giá trị ducked tương ứng (-18 dB)
        self.ducked_fader_val = max(0.0, val - 0.35)
        if not self.is_ducked and not self._is_fading:
            self.current_fader_val = val

    def process_frame(
        self,
        mic_energy_dbfs: float,
        music_energy_dbfs: float,
        now: float,
    ) -> Tuple[Optional[float], Optional[bool], str]:
        """Xử lý tín hiệu mic và nhạc để quyết định trạng thái Talkover.
        
        Trả về:
            (new_fader_val_if_changed, mute_state_if_hard_mute, event_log_message)
        """
        if not self.config.enabled:
            return None, None, ""

        is_music_silent = music_energy_dbfs < self.config.music_silence_threshold_dbfs
        is_speech_present = mic_energy_dbfs > self.config.mic_speech_threshold_dbfs

        msg = ""

        # Điều kiện kích hoạt Talkover:
        # Nhạc nền đã DỪNG (hoặc rất nhỏ) VÀ ca sĩ/MC đang nói chuyện
        if is_music_silent and is_speech_present:
            self.last_speech_time = now
            if not self.is_ducked:
                self.is_ducked = True
                msg = f"Kích hoạt Talkover: Nhạc dừng ({music_energy_dbfs:.1f}dBFS) & Mic nói ({mic_energy_dbfs:.1f}dBFS)"
                self._start_fade(target_val=self.ducked_fader_val, now=now)

        # Điều kiện nhả Talkover (trở lại trạng thái ban đầu):
        # Khi nhạc beat NỔI LÊN TRỞ LẠI HOẶC sau khi hết hold_time_s không còn tiếng nói
        elif self.is_ducked:
            music_resumed = not is_music_silent
            hold_expired = (now - self.last_speech_time) >= self.config.hold_time_s

            if music_resumed or hold_expired:
                self.is_ducked = False
                trigger = "Nhạc nổi lên" if music_resumed else "Hết câu giao lưu"
                msg = f"Nhả Talkover ({trigger}) -> Khôi phục FX Return về {self.original_fader_val:.2f}"
                self._start_fade(target_val=self.original_fader_val, now=now)

        # Cập nhật nội suy Fader nếu đang trong quá trình Fade
        fader_out = None
        if self._is_fading:
            fader_out = self._update_fade(now)

        return fader_out, None, msg

    def _start_fade(self, target_val: float, now: float) -> None:
        """Khởi động quá trình ramp fader mượt mà."""
        self._fade_start_val = self.current_fader_val
        self._fade_target_val = target_val
        self._fade_start_time = now
        self._is_fading = True

    def _update_fade(self, now: float) -> Optional[float]:
        """Nội suy fader tuyến tính theo thời gian (300 ms)."""
        duration_s = max(0.05, self.config.fade_duration_ms / 1000.0)
        progress = (now - self._fade_start_time) / duration_s

        if progress >= 1.0:
            self.current_fader_val = self._fade_target_val
            self._is_fading = False
            return round(self.current_fader_val, 3)

        # Tuyến tính mượt
        val = self._fade_start_val + (self._fade_target_val - self._fade_start_val) * progress
        self.current_fader_val = val
        return round(val, 3)
