"""Bộ ánh xạ tham số hai chiều giữa đơn vị vật lý (Hz, dB, Q) và số thực chuẩn hóa [0.0, 1.0] của Behringer OSC."""

from __future__ import annotations
import math
import tomllib
from pathlib import Path
from typing import Any, Union


class SubMapper:
    """Lớp cơ sở ánh xạ một tham số duy nhất."""

    def __init__(self, min_val: float, max_val: float, steps: int, is_log: bool = False) -> None:
        if min_val >= max_val:
            raise ValueError(f"min_val ({min_val}) phải nhỏ hơn max_val ({max_val})")
        if steps < 2:
            raise ValueError(f"steps ({steps}) phải >= 2")
        if is_log and min_val <= 0:
            raise ValueError("Ánh xạ logarit yêu cầu min_val > 0")

        self.min_val = float(min_val)
        self.max_val = float(max_val)
        self.steps = int(steps)
        self.is_log = is_log

        if self.is_log:
            self._log_min = math.log10(self.min_val)
            self._log_max = math.log10(self.max_val)
            self._log_range = self._log_max - self._log_min
        else:
            self._range = self.max_val - self.min_val

    def to_float(self, val: float) -> float:
        """Chuyển từ giá trị vật lý sang số thực chuẩn hóa [0.0, 1.0]."""
        clamped = max(self.min_val, min(self.max_val, float(val)))
        if self.is_log:
            norm = (math.log10(clamped) - self._log_min) / self._log_range
        else:
            norm = (clamped - self.min_val) / self._range
        return max(0.0, min(1.0, norm))

    def from_float(self, f: float) -> float:
        """Chuyển từ số thực chuẩn hóa [0.0, 1.0] sang giá trị vật lý."""
        clamped = max(0.0, min(1.0, float(f)))
        if self.is_log:
            val = 10.0 ** (self._log_min + clamped * self._log_range)
        else:
            val = self.min_val + clamped * self._range
        return max(self.min_val, min(self.max_val, val))

    def quantize_float(self, f: float) -> float:
        """Lượng tử hóa số thực [0.0, 1.0] về bước rời rạc gần nhất."""
        clamped = max(0.0, min(1.0, float(f)))
        step_idx = round(clamped * (self.steps - 1))
        return step_idx / (self.steps - 1)

    def snap(self, val: float) -> float:
        """Bắt giá trị vật lý vào nấc rời rạc gần nhất của phần cứng."""
        norm = self.to_float(val)
        q_norm = self.quantize_float(norm)
        return self.from_float(q_norm)

    @property
    def max_roundtrip_error(self) -> float:
        """Sai số tối đa ước tính giữa giá trị gốc và giá trị sau khi snap."""
        if self.is_log:
            # Tỷ lệ phần trăm tối đa giữa 2 bước liên tiếp
            step_ratio = (self.max_val / self.min_val) ** (1.0 / (self.steps - 1))
            return (step_ratio - 1.0) * self.max_val
        else:
            # Độ phân giải bước tuyến tính
            return self._range / (self.steps - 1)


class ParameterMapper:
    """Bộ điều phối ánh xạ toàn bộ các tham số EQ (Tần số, Gain, Q)."""

    def __init__(self, freq_mapper: SubMapper, gain_mapper: SubMapper, q_mapper: SubMapper) -> None:
        self.freq = freq_mapper
        self.gain = gain_mapper
        self.q = q_mapper

    @classmethod
    def from_profile(cls, profile: Union[str, Path, dict[str, Any]]) -> ParameterMapper:
        """Khởi tạo ParameterMapper từ file TOML cấu hình hoặc dictionary."""
        if isinstance(profile, (str, Path)):
            with open(profile, "rb") as f:
                data = tomllib.load(f)
        elif isinstance(profile, dict):
            data = profile
        else:
            raise TypeError("profile phải là đường dẫn file hoặc dict")

        eq_cfg = data.get("eq", {})
        freq_mapper = SubMapper(
            min_val=eq_cfg.get("freq_min_hz", 20.0),
            max_val=eq_cfg.get("freq_max_hz", 20000.0),
            steps=eq_cfg.get("freq_steps", 201),
            is_log=True,
        )
        gain_mapper = SubMapper(
            min_val=eq_cfg.get("gain_min_db", -15.0),
            max_val=eq_cfg.get("gain_max_db", 15.0),
            steps=eq_cfg.get("gain_steps", 121),
            is_log=False,
        )
        q_mapper = SubMapper(
            min_val=eq_cfg.get("q_min", 0.3),
            max_val=eq_cfg.get("q_max", 10.0),
            steps=eq_cfg.get("q_steps", 72),
            is_log=True,
        )
        return cls(freq_mapper, gain_mapper, q_mapper)
