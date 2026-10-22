"""Đọc và quản lý cấu hình hệ thống từ file TOML."""

from __future__ import annotations
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Union


@dataclass
class DeviceConfig:
    name: str = "Behringer XR18"
    family: str = "X-Air"
    port: int = 10024
    max_clients: int = 4
    heartbeat_interval_s: float = 8.0
    client_timeout_s: float = 10.0
    reconnect_timeout_s: float = 3.0
    has_multichannel_usb: bool = True
    supports_rta_network: bool = True


@dataclass
class ChannelsConfig:
    mic_channels: List[int] = field(default_factory=lambda: list(range(1, 17)))
    return_channels: List[int] = field(default_factory=lambda: [17, 18])
    line_channels: List[int] = field(default_factory=list)
    total_usb_channels: int = 18
    total_channels: int = 18


@dataclass
class EQConfig:
    channel_bands_count: int = 4
    channel_band_names: List[str] = field(default_factory=lambda: ["Low", "LoMid", "HiMid", "High"])
    bus_bands_count: int = 6
    bus_band_names: List[str] = field(default_factory=lambda: ["Low", "Lo2", "LoMid", "HiMid", "High2", "High"])
    main_bands_count: int = 6
    main_band_names: List[str] = field(default_factory=lambda: ["Low", "Lo2", "LoMid", "HiMid", "High2", "High"])
    auto_notch_bands: List[int] = field(default_factory=lambda: [3, 4])
    bus_auto_notch_bands: List[int] = field(default_factory=lambda: [5, 6])
    main_auto_notch_bands: List[int] = field(default_factory=lambda: [3, 4, 5, 6])
    max_notches_per_channel: int = 2
    max_notches_per_target: int = 4
    freq_min_hz: float = 20.0
    freq_max_hz: float = 20000.0
    freq_steps: int = 201
    gain_min_db: float = -15.0
    gain_max_db: float = 15.0
    gain_steps: int = 121
    q_min: float = 0.3
    q_max: float = 10.0
    q_steps: int = 72


@dataclass
class SafetyConfig:
    max_boost_db: float = 4.0
    max_cut_db: float = -12.0
    probe_step_db: float = -3.0
    probe_wait_ms: float = 80.0
    max_transactions_per_sec: float = 2.0
    manual_override_lock_s: float = 10.0
    auto_release_wait_s: float = 20.0
    auto_release_rate_db_per_s: float = 1.0


@dataclass
class NetworkConfig:
    default_mixer_ip: str = "192.168.1.100"
    default_laptop_ip: str = "192.168.1.50"
    default_subnet_mask: str = "255.255.255.0"


@dataclass
class AppConfig:
    device: DeviceConfig = field(default_factory=DeviceConfig)
    channels: ChannelsConfig = field(default_factory=ChannelsConfig)
    eq: EQConfig = field(default_factory=EQConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)

    @classmethod
    def load(cls, path: Union[str, Path]) -> AppConfig:
        """Đọc cấu hình từ file TOML."""
        with open(path, "rb") as f:
            data = tomllib.load(f)

        dev_data = data.get("device", {})
        chan_data = data.get("channels", {})
        eq_data = data.get("eq", {})
        safety_data = data.get("safety", {})
        net_data = data.get("network", {})

        return cls(
            device=DeviceConfig(**dev_data),
            channels=ChannelsConfig(**chan_data),
            eq=EQConfig(**eq_data),
            safety=SafetyConfig(**safety_data),
            network=NetworkConfig(**net_data),
        )
