"""Module Snapshot và Rollback trạng thái PEQ mixer (Giai đoạn D5).

Mục tiêu:
- Chụp ảnh (Snapshot) toàn bộ trạng thái PEQ trước khi bắt đầu phiên diễn.
- Rollback khôi phục về snapshot ban đầu (không chỉ đơn thuần đưa về 0 dB).
- Hoàn tất trong thời gian < 1.0 giây trong điều kiện mạng bình thường.
- Có cờ trạng thái cảnh báo nếu một phần lệnh thất bại (Partial Failure Flag).
"""

from __future__ import annotations
from dataclasses import dataclass, field
import json
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple, Union
from auto_sound.mixer.osc import encode_message
from auto_sound.mixer.xair import XAirClient


@dataclass
class BandState:
    """Trạng thái một dải PEQ."""
    f: float = 0.5
    g: float = 0.5
    q: float = 0.5
    on: int = 1


@dataclass
class PEQSnapshot:
    """Ảnh chụp trạng thái PEQ tại một thời điểm."""
    timestamp: float
    created_at_iso: str
    bands: Dict[str, BandState] = field(default_factory=dict)  # address prefix -> BandState

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "created_at_iso": self.created_at_iso,
            "bands": {
                addr: {"f": b.f, "g": b.g, "q": b.q, "on": b.on}
                for addr, b in self.bands.items()
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PEQSnapshot:
        bands = {
            addr: BandState(f=d["f"], g=d["g"], q=d["q"], on=d["on"])
            for addr, d in data.get("bands", {}).items()
        }
        return cls(
            timestamp=data["timestamp"],
            created_at_iso=data["created_at_iso"],
            bands=bands,
        )

    def save_file(self, path: Union[str, Path]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load_file(cls, path: Union[str, Path]) -> PEQSnapshot:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)


@dataclass
class RollbackReport:
    """Báo cáo kết quả thực thi hoàn tác trạng thái PEQ."""
    success: bool
    total_bands: int
    restored_count: int
    failed_addresses: List[str]
    duration_s: float
    partial_failure: bool
    status_message: str


class SnapshotManager:
    """Điều phối chụp và hoàn tác trạng thái PEQ."""

    def __init__(self, client: XAirClient) -> None:
        self.client = client
        self.current_snapshot: Optional[PEQSnapshot] = None

    def take_snapshot(
        self,
        channels: Optional[List[int]] = None,
        buses: Optional[List[int]] = None,
        include_main: bool = True,
        channel_bands_count: Optional[int] = None,
        bus_bands_count: int = 6,
        main_bands_count: int = 6,
    ) -> PEQSnapshot:
        """Chụp trạng thái toàn bộ các band PEQ từ cache của mixer client.
        Số band quét có thể tự động thích ứng hoặc cấu hình theo device profile.
        """
        if channels is None:
            channels = list(range(1, 17))
        if buses is None:
            buses = list(range(1, 7))

        ch_bands = channel_bands_count if channel_bands_count is not None else getattr(self.client, "channel_bands_count", 4)

        bands_dict: Dict[str, BandState] = {}
        now = time.time()

        # 1. Quét Channel PEQ (Band 1..ch_bands)
        for ch in channels:
            for band in range(1, ch_bands + 1):
                prefix = f"/ch/{ch:02d}/eq/{band}"
                bands_dict[prefix] = self._read_band_from_cache(prefix)

        # 2. Quét Bus PEQ (Band 1..bus_bands_count)
        for bus in buses:
            for band in range(1, bus_bands_count + 1):
                prefix = f"/bus/{bus}/eq/{band}"
                bands_dict[prefix] = self._read_band_from_cache(prefix)

        # 3. Quét Main Stereo PEQ (Band 1..main_bands_count)
        if include_main:
            for band in range(1, main_bands_count + 1):
                prefix = f"/main/st/eq/{band}"
                bands_dict[prefix] = self._read_band_from_cache(prefix)

        snapshot = PEQSnapshot(
            timestamp=now,
            created_at_iso=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
            bands=bands_dict,
        )
        self.current_snapshot = snapshot
        return snapshot

    def _read_band_from_cache(self, prefix: str) -> BandState:
        """Đọc giá trị f, g, q, on từ cache của client (mặc định 0.5 nếu chưa có trong cache)."""
        f = float(self.client._params_cache.get(f"{prefix}/f", 0.5))
        g = float(self.client._params_cache.get(f"{prefix}/g", 0.5))
        q = float(self.client._params_cache.get(f"{prefix}/q", 0.5))
        on = int(self.client._params_cache.get(f"{prefix}/on", 1))
        return BandState(f=f, g=g, q=q, on=on)

    def rollback(
        self,
        snapshot: Optional[PEQSnapshot] = None,
        target_prefixes: Optional[List[str]] = None,
    ) -> RollbackReport:
        """Hoàn tác trạng thái PEQ về snapshot trong thời gian < 1.0 giây.
        
        Args:
            snapshot: Đối tượng PEQSnapshot cần hoàn tác (mặc định là current_snapshot).
            target_prefixes: Danh sách tiền tố cần hoàn tác (nếu chỉ muốn rollback 1 phần).
        """
        snap = snapshot if snapshot is not None else self.current_snapshot
        if snap is None:
            return RollbackReport(
                success=False,
                total_bands=0,
                restored_count=0,
                failed_addresses=[],
                duration_s=0.0,
                partial_failure=False,
                status_message="Không tìm thấy bản chụp snapshot để hoàn tác",
            )

        t_start = time.perf_counter()
        failed: List[str] = []
        restored = 0

        # Lọc danh sách band cần khôi phục
        bands_to_restore = snap.bands
        if target_prefixes is not None:
            prefix_set = set(target_prefixes)
            bands_to_restore = {k: v for k, v in snap.bands.items() if k in prefix_set}

        for prefix, state in bands_to_restore.items():
            try:
                # Gửi gói tin cập nhật tham số
                ok_f = self.client._send_raw(encode_message(f"{prefix}/f", float(state.f)))
                ok_g = self.client._send_raw(encode_message(f"{prefix}/g", float(state.g)))
                ok_q = self.client._send_raw(encode_message(f"{prefix}/q", float(state.q)))
                ok_on = self.client._send_raw(encode_message(f"{prefix}/on", int(state.on)))

                if ok_f and ok_g and ok_q and ok_on:
                    restored += 1
                    # Cập nhật lại cache cục bộ
                    with self.client._lock:
                        self.client._params_cache[f"{prefix}/f"] = state.f
                        self.client._params_cache[f"{prefix}/g"] = state.g
                        self.client._params_cache[f"{prefix}/q"] = state.q
                        self.client._params_cache[f"{prefix}/on"] = state.on
                else:
                    failed.append(prefix)
            except Exception:
                failed.append(prefix)

        t_end = time.perf_counter()
        duration_s = t_end - t_start

        partial = len(failed) > 0 and restored > 0
        success = len(failed) == 0 and restored > 0

        if success:
            msg = f"Hoàn tác thành công {restored} dải PEQ trong {duration_s*1000:.1f}ms (< 1.0s)"
        elif partial:
            msg = f"[CẢNH BÁO] Hoàn tác một phần: {restored} thành công, {len(failed)} thất bại trong {duration_s*1000:.1f}ms"
        else:
            msg = f"Hoàn tác thất bại toàn bộ ({len(failed)} lỗi)"

        return RollbackReport(
            success=success,
            total_bands=len(bands_to_restore),
            restored_count=restored,
            failed_addresses=failed,
            duration_s=round(duration_s, 4),
            partial_failure=partial,
            status_message=msg,
        )
