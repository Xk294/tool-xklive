#!/usr/bin/env python3
"""Công cụ thăm dò và kiểm chứng giao thức phần cứng mixer Behringer/Midas (Hardware Probe CLI).

Sử dụng trực tiếp trên bàn mixer thật (XR18/XR12/XR16/MR18/MR12) để kiểm chứng:
1. Thông tin firmware, model qua /xinfo.
2. Giới hạn số lượng client /xremote tối đa (4 client).
3. Độ trễ khứ hồi RTT thực tế của lệnh ghi PEQ + đọc lại.
4. Quét bảng nấc lượng tử hóa thực tế của Freq, Gain, Q.
5. Thăm dò cấu trúc và tần suất luồng RTA 100-band (/meters/4).
6. Đo đạc độ trễ phản hồi echo của /xremote.
7. Thăm dò giới hạn tốc độ truyền nhận lệnh (Rate limit stress test).

Tính năng an toàn:
- Có cờ --dry-read (chỉ đọc, không ghi).
- Luôn sao lưu và khôi phục nguyên trạng PEQ ban đầu khi kết thúc hoặc khi bấm Ctrl-C.
"""

from __future__ import annotations
import argparse
import json
import math
import select
import signal
import socket
import struct
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Bổ sung src vào sys.path để nạp auto_sound module
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

from auto_sound.mixer.osc import decode_message, encode_message, OscParseError


class HardwareProber:
    """Điều phối toàn bộ chu trình thăm dò giao thức phần cứng mixer."""

    def __init__(
        self,
        ip: str,
        port: int,
        target_ch: int = 16,
        target_band: int = 4,
        dry_read: bool = False,
        rtt_count: int = 200,
        output_file: Optional[Path] = None,
    ) -> None:
        self.ip = ip
        self.port = port
        self.target_ch = target_ch
        self.target_band = target_band
        self.dry_read = dry_read
        self.rtt_count = rtt_count
        self.output_file = output_file

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)

        self.original_peq: Dict[str, Any] = {}
        self.results: Dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "target": f"{self.ip}:{self.port}",
            "dry_read": self.dry_read,
        }

        # Đăng ký signal handler để khôi phục PEQ nếu bị ngắt bởi Ctrl-C
        signal.signal(signal.SIGINT, self._handle_sigint)

    def _handle_sigint(self, signum: int, frame: Any) -> None:
        print("\n[CẢNH BÁO] Phát hiện Ctrl-C! Đang khôi phục cài đặt gốc của mixer...")
        self.restore_original()
        self.sock.close()
        sys.exit(130)

    def send_and_wait(self, address: str, args: List[Any], expect_addr: Optional[str] = None, timeout: float = 0.5) -> Optional[Tuple[str, List[Any]]]:
        """Gửi 1 gói tin OSC và chờ phản hồi có địa chỉ khớp expect_addr."""
        data = encode_message(address, *args)
        target_addr = expect_addr or address
        try:
            self.sock.sendto(data, (self.ip, self.port))
        except Exception as e:
            return None

        deadline = time.time() + timeout
        while time.time() < deadline:
            rlist, _, _ = select.select([self.sock], [], [], max(0.01, deadline - time.time()))
            if not rlist:
                break
            try:
                rx_data, _ = self.sock.recvfrom(4096)
                rx_addr, rx_args = decode_message(rx_data)
                if rx_addr == target_addr:
                    return rx_addr, rx_args
            except (BlockingIOError, socket.error):
                break
            except OscParseError:
                continue
        return None

    def probe_xinfo(self) -> Dict[str, Any]:
        """Bước 1: Bắt tay /xinfo, đọc IP, model, firmware."""
        print(f"\n[1/7] Bắt tay /xinfo với mixer tại {self.ip}:{self.port}...")
        resp = self.send_and_wait("/xinfo", [], timeout=1.0)
        if not resp:
            print("  --> [LỖI] Không nhận được phản hồi /xinfo! Kiểm tra cáp mạng và IP mixer.")
            info = {"status": "NO_RESPONSE"}
            self.results["xinfo"] = info
            return info

        _, args = resp
        info = {
            "status": "OK",
            "mixer_ip": args[0] if len(args) > 0 else "unknown",
            "model": args[1] if len(args) > 1 else "unknown",
            "name": args[2] if len(args) > 2 else "unknown",
            "firmware": args[3] if len(args) > 3 else "unknown",
        }
        print(f"  --> Model: {info['model']} | Tên: {info['name']} | Firmware: {info['firmware']}")
        self.results["xinfo"] = info
        return info

    def backup_original_peq(self) -> None:
        """Đọc và lưu giữ giá trị PEQ ban đầu của channel và band được chọn."""
        ch_str = f"{self.target_ch:02d}"
        band = self.target_band
        prefix = f"/ch/{ch_str}/eq/{band}"

        for param in ("f", "g", "q", "on"):
            addr = f"{prefix}/{param}"
            resp = self.send_and_wait(addr, [], timeout=0.4)
            if resp and len(resp[1]) > 0:
                self.original_peq[addr] = resp[1][0]
            else:
                self.original_peq[addr] = 0.5

        print(f"  --> Đã sao lưu trạng thái ban đầu của {prefix}: {self.original_peq}")

    def restore_original(self) -> None:
        """Khôi phục lại chính xác tham số PEQ ban đầu."""
        if not self.original_peq or self.dry_read:
            return
        print("  --> Đang khôi phục tham số PEQ gốc...")
        for addr, val in self.original_peq.items():
            self.sock.sendto(encode_message(addr, val), (self.ip, self.port))
            time.sleep(0.02)
        print("  --> Hoàn tất khôi phục an toàn.")

    def probe_max_clients(self) -> Dict[str, Any]:
        """Bước 2: Mở 5 client socket đồng thời, kiểm tra giới hạn client /xremote."""
        print("\n[2/7] Kiểm tra giới hạn số lượng client /xremote tối đa...")
        sockets: List[socket.socket] = []
        for i in range(5):
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setblocking(False)
            sockets.append(s)

        client_status: Dict[str, Any] = {}
        try:
            # Gửi /xremote từ cả 5 socket
            for i, s in enumerate(sockets, start=1):
                s.sendto(encode_message("/xremote"), (self.ip, self.port))
                time.sleep(0.05)

            # Thay đổi 1 tham số nhẹ để xem những socket nào nhận được broadcast echo
            test_addr = f"/ch/{self.target_ch:02d}/eq/{self.target_band}/on"
            curr_val = self.original_peq.get(test_addr, 1)
            # Nếu dry_read thì không ghi, chỉ thử query
            if not self.dry_read:
                # Ghi giá trị tương tự để kích hoạt broadcast
                self.sock.sendto(encode_message(test_addr, curr_val), (self.ip, self.port))
                time.sleep(0.1)

                received_counts = 0
                for i, s in enumerate(sockets, start=1):
                    rlist, _, _ = select.select([s], [], [], 0.2)
                    has_echo = False
                    if rlist:
                        try:
                            rx_data, _ = s.recvfrom(4096)
                            has_echo = True
                            received_counts += 1
                        except Exception:
                            pass
                    client_status[f"client_{i}"] = "ACTIVE" if has_echo else "NO_BROADCAST"

                client_status["active_clients_count"] = received_counts
                print(f"  --> Số client nhận được broadcast: {received_counts}/5")
                print(f"  --> Hành vi client thứ 5: {client_status.get('client_5')}")
            else:
                client_status["note"] = "Bỏ qua ghi tham số do cờ --dry-read bật"
                print("  --> [DRY-READ] Bỏ qua kiểm tra broadcast qua ghi tham số.")
        finally:
            for s in sockets:
                s.close()

        self.results["max_clients_probe"] = client_status
        return client_status

    def probe_rtt(self) -> Dict[str, Any]:
        """Bước 3: Đo RTT thực tế của lệnh ghi PEQ + đọc lại (>= 200 lần)."""
        print(f"\n[3/7] Đo độ trễ khứ hồi RTT ({self.rtt_count} lần thử)...")
        if self.dry_read:
            print("  --> [DRY-READ] Đo RTT bằng lệnh GET tham số...")
        else:
            print(f"  --> Ghi và đọc lại trên Kênh {self.target_ch} Band {self.target_band}...")

        ch_str = f"{self.target_ch:02d}"
        addr = f"/ch/{ch_str}/eq/{self.target_band}/g"
        target_val = self.original_peq.get(addr, 0.5)

        rtt_list: List[float] = []
        dropped_packets = 0

        for i in range(self.rtt_count):
            t_start = time.perf_counter()
            if self.dry_read:
                resp = self.send_and_wait(addr, [], timeout=0.2)
            else:
                # Ghi rồi đọc lại
                self.sock.sendto(encode_message(addr, float(target_val)), (self.ip, self.port))
                resp = self.send_and_wait(addr, [], timeout=0.2)
            t_end = time.perf_counter()

            if resp:
                rtt_ms = (t_end - t_start) * 1000.0
                rtt_list.append(rtt_ms)
            else:
                dropped_packets += 1

            # Giữ nhịp gửi không làm nghẽn mixer
            time.sleep(0.01)

        if not rtt_list:
            stats = {"error": "Toàn bộ gói tin bị rớt (100% loss)"}
        else:
            rtt_list.sort()
            n = len(rtt_list)
            stats = {
                "total_sent": self.rtt_count,
                "successful": n,
                "dropped": dropped_packets,
                "drop_rate_pct": (dropped_packets / self.rtt_count) * 100.0,
                "min_ms": round(rtt_list[0], 2),
                "max_ms": round(rtt_list[-1], 2),
                "mean_ms": round(sum(rtt_list) / n, 2),
                "p50_ms": round(rtt_list[int(n * 0.50)], 2),
                "p95_ms": round(rtt_list[min(n - 1, int(n * 0.95))], 2),
                "p99_ms": round(rtt_list[min(n - 1, int(n * 0.99))], 2),
            }
            print(f"  --> RTT: p50 = {stats['p50_ms']}ms | p95 = {stats['p95_ms']}ms | p99 = {stats['p99_ms']}ms | Max = {stats['max_ms']}ms")
            print(f"  --> Tỷ lệ rớt gói: {stats['drop_rate_pct']:.1f}% ({dropped_packets}/{self.rtt_count})")

        self.results["rtt_stats"] = stats
        return stats

    def probe_quantization(self) -> Dict[str, Any]:
        """Bước 4: Quét nấc lượng tử hóa thực tế của Freq, Gain, Q."""
        print("\n[4/7] Quét nấc lượng tử hóa tham số (Quantization Steps Scan)...")
        if self.dry_read:
            print("  --> [DRY-READ] Bỏ qua quét ghi lượng tử hóa để bảo vệ an toàn.")
            self.results["quantization_scan"] = {"status": "SKIPPED_DRY_READ"}
            return self.results["quantization_scan"]

        ch_str = f"{self.target_ch:02d}"
        band = self.target_band
        params_to_scan = [
            ("gain", f"/ch/{ch_str}/eq/{band}/g", 250),   # Quét 250 điểm giữa 0.0 và 1.0
            ("q", f"/ch/{ch_str}/eq/{band}/q", 150),
            ("freq", f"/ch/{ch_str}/eq/{band}/f", 300),
        ]

        quant_results: Dict[str, Any] = {}
        for name, addr, sample_points in params_to_scan:
            print(f"  --> Đang quét tham số '{name}' ({sample_points} điểm mẫu)...")
            detected_steps = set()
            test_floats = [i / (sample_points - 1) for i in range(sample_points)]

            for val in test_floats:
                self.sock.sendto(encode_message(addr, float(val)), (self.ip, self.port))
                resp = self.send_and_wait(addr, [], timeout=0.15)
                if resp and len(resp[1]) > 0:
                    readback = round(float(resp[1][0]), 4)
                    detected_steps.add(readback)
                time.sleep(0.01)

            sorted_steps = sorted(list(detected_steps))
            quant_results[name] = {
                "unique_steps_count": len(sorted_steps),
                "min_step_detected": sorted_steps[0] if sorted_steps else None,
                "max_step_detected": sorted_steps[-1] if sorted_steps else None,
                "steps_sample": sorted_steps[:10],
            }
            print(f"      Số nấc thực tế nhận diện: {len(sorted_steps)} nấc")

        self.results["quantization_scan"] = quant_results
        return quant_results

    def probe_meters_rta(self) -> Dict[str, Any]:
        """Bước 5: Kiểm tra luồng RTA 100-band (/meters/4)."""
        print("\n[5/7] Thăm dò luồng phổ RTA 100-band (/meters/4)...")
        # Gửi đăng ký subscription /meters/4
        self.sock.sendto(encode_message("/meters", "/meters/4"), (self.ip, self.port))
        self.sock.sendto(encode_message("/meters/4"), (self.ip, self.port))

        t_end = time.time() + 2.0
        packets: List[bytes] = []
        timestamps: List[float] = []

        while time.time() < t_end:
            rlist, _, _ = select.select([self.sock], [], [], 0.1)
            if rlist:
                try:
                    data, _ = self.sock.recvfrom(4096)
                    rx_addr, rx_args = decode_message(data)
                    if rx_addr == "/meters/4" and len(rx_args) > 0:
                        raw_blob = rx_args[0]
                        if isinstance(raw_blob, (bytes, bytearray)):
                            packets.append(raw_blob)
                            timestamps.append(time.time())
                except Exception:
                    break

        if not packets:
            rta_stats = {"status": "NO_RTA_PACKETS", "note": "Không nhận được gói tin /meters/4 nào sau 2.0 giây"}
            print("  --> [CẢNH BÁO] Không nhận được gói tin RTA! Cần kiểm tra xem có cần bật RTA trên X-Air Edit.")
        else:
            first_blob = packets[0]
            blob_len = len(first_blob)
            intervals = [t2 - t1 for t1, t2 in zip(timestamps[:-1], timestamps[1:])]
            avg_interval_ms = (sum(intervals) / len(intervals) * 1000.0) if intervals else 0.0

            # Phân tích cấu trúc blob
            has_size_header = (blob_len >= 204)
            data_offset = 4 if has_size_header else 0
            shorts_count = (blob_len - data_offset) // 2

            rta_stats = {
                "status": "OK",
                "packets_received": len(packets),
                "blob_byte_length": blob_len,
                "has_size_header_int32": has_size_header,
                "shorts_detected": shorts_count,
                "avg_update_interval_ms": round(avg_interval_ms, 2),
                "fps": round(1000.0 / avg_interval_ms, 1) if avg_interval_ms > 0 else 0,
            }
            print(f"  --> Nhận {len(packets)} gói | Kích thước blob: {blob_len} bytes | Số bands: {shorts_count}")
            print(f"  --> Tần suất cập nhật: ~{rta_stats['avg_update_interval_ms']} ms/khung ({rta_stats['fps']} FPS)")

        self.results["rta_probe"] = rta_stats
        return rta_stats

    def probe_xremote_echo(self) -> Dict[str, Any]:
        """Bước 6: Đo đạc hành vi và thời gian phản hồi echo của /xremote."""
        print("\n[6/7] Đo đạc độ trễ phản hồi echo /xremote...")
        if self.dry_read:
            echo_stats = {"status": "SKIPPED_DRY_READ"}
            self.results["xremote_echo_probe"] = echo_stats
            print("  --> [DRY-READ] Bỏ qua kiểm tra echo qua ghi.")
            return echo_stats

        # Đăng ký /xremote trước
        self.sock.sendto(encode_message("/xremote"), (self.ip, self.port))
        time.sleep(0.1)

        addr = f"/ch/{self.target_ch:02d}/eq/{self.target_band}/on"
        curr_val = int(self.original_peq.get(addr, 1))
        new_val = 0 if curr_val == 1 else 1

        echo_delays: List[float] = []
        for _ in range(10):
            t_send = time.perf_counter()
            self.sock.sendto(encode_message(addr, new_val), (self.ip, self.port))

            # Chờ nhận lại gói echo broadcast
            deadline = time.time() + 0.5
            got_echo = False
            while time.time() < deadline:
                rlist, _, _ = select.select([self.sock], [], [], 0.05)
                if rlist:
                    try:
                        data, _ = self.sock.recvfrom(4096)
                        rx_addr, rx_args = decode_message(data)
                        if rx_addr == addr and len(rx_args) > 0 and int(rx_args[0]) == new_val:
                            delay_ms = (time.perf_counter() - t_send) * 1000.0
                            echo_delays.append(delay_ms)
                            got_echo = True
                            break
                    except Exception:
                        pass
            # Đổi lại
            new_val = 1 if new_val == 0 else 0
            time.sleep(0.05)

        if echo_delays:
            echo_stats = {
                "echo_received_count": len(echo_delays),
                "min_delay_ms": round(min(echo_delays), 2),
                "max_delay_ms": round(max(echo_delays), 2),
                "mean_delay_ms": round(sum(echo_delays) / len(echo_delays), 2),
            }
            print(f"  --> Nhận {len(echo_delays)}/10 echo | Trễ trung bình: {echo_stats['mean_delay_ms']} ms (Max: {echo_stats['max_delay_ms']} ms)")
        else:
            echo_stats = {"status": "NO_ECHO_RECEIVED", "note": "Mixer không tự gửi lại broadcast echo cho socket gửi lệnh"}
            print("  --> [CHÚ Ý] Không nhận được echo phản hồi trực tiếp cho socket gửi lệnh.")

        self.results["xremote_echo_probe"] = echo_stats
        return echo_stats

    def probe_rate_limit(self) -> Dict[str, Any]:
        """Bước 7: Thăm dò giới hạn tốc độ truyền (tăng dần tần suất 2, 5, 10, 20 lệnh/s)."""
        print("\n[7/7] Thăm dò giới hạn tốc độ truyền (Rate Limit Stress Test)...")
        if self.dry_read:
            rate_stats = {"status": "SKIPPED_DRY_READ"}
            self.results["rate_limit_probe"] = rate_stats
            print("  --> [DRY-READ] Bỏ qua kiểm tra stress rate limit.")
            return rate_stats

        rates_to_test = [2.0, 5.0, 10.0, 20.0]
        rate_results: Dict[str, Any] = {}
        addr = f"/ch/{self.target_ch:02d}/eq/{self.target_band}/g"
        base_val = self.original_peq.get(addr, 0.5)

        for rate in rates_to_test:
            interval = 1.0 / rate
            total_packets = int(rate * 2)  # Thử trong 2.0 giây
            received = 0
            t_start = time.time()

            for _ in range(total_packets):
                t_tx = time.time()
                self.sock.sendto(encode_message(addr, float(base_val)), (self.ip, self.port))
                resp = self.send_and_wait(addr, [], timeout=min(0.2, interval))
                if resp:
                    received += 1
                sleep_rem = interval - (time.time() - t_tx)
                if sleep_rem > 0:
                    time.sleep(sleep_rem)

            rate_results[f"{int(rate)}_per_sec"] = {
                "sent": total_packets,
                "received": received,
                "loss_pct": round((1.0 - received / total_packets) * 100.0, 1),
            }
            print(f"  --> Tốc độ {int(rate)} lệnh/s: Nhận {received}/{total_packets} (Rớt: {rate_results[f'{int(rate)}_per_sec']['loss_pct']}%)")

        self.results["rate_limit_probe"] = rate_results
        return rate_results

    def run_all(self) -> Dict[str, Any]:
        """Thực thi tuần tự toàn bộ các bài kiểm tra."""
        print(f"=== BẮT ĐẦU THĂM DÒ PHẦN CỨNG MIXER TẠI {self.ip}:{self.port} ===")
        if self.dry_read:
            print(">>> CHẾ ĐỘ DRY-READ (CHỈ ĐỌC): Tuyệt đối không thay đổi bất kỳ tham số nào trên mixer. <<<")

        try:
            # 1. /xinfo
            info = self.probe_xinfo()
            if info.get("status") == "NO_RESPONSE":
                print("\n[DỪNG] Không thể kết nối với mixer. Vui lòng kiểm tra lại địa chỉ IP và cáp mạng LAN.")
                return self.results

            # Sao lưu cài đặt PEQ
            self.backup_original_peq()

            # 2. Max clients
            self.probe_max_clients()

            # 3. RTT
            self.probe_rtt()

            # 4. Quantization
            self.probe_quantization()

            # 5. RTA 100-band
            self.probe_meters_rta()

            # 6. xremote echo
            self.probe_xremote_echo()

            # 7. Rate limit
            self.probe_rate_limit()

        finally:
            self.restore_original()
            self.sock.close()

        # Lưu kết quả ra file JSON
        if self.output_file:
            self.output_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.output_file, "w", encoding="utf-8") as f:
                json.dump(self.results, f, ensure_ascii=False, indent=2)
            print(f"\n[HOÀN TẤT] Kết quả chi tiết đã được lưu tại: {self.output_file}")

        return self.results


def main() -> None:
    parser = argparse.ArgumentParser(description="Công cụ thăm dò và đo kiểm giao thức mixer Behringer/Midas")
    parser.add_argument("--ip", default="192.168.1.100", help="Địa chỉ IP của mixer (mặc định: 192.168.1.100)")
    parser.add_argument("--port", type=int, default=10024, help="Cổng OSC UDP của mixer (mặc định: 10024)")
    parser.add_argument("--target-ch", type=int, default=16, help="Kênh micro dùng để thử ghi (mặc định: 16)")
    parser.add_argument("--target-band", type=int, default=4, help="Band PEQ dùng để thử ghi (mặc định: 4)")
    parser.add_argument("--dry-read", action="store_true", help="Chế độ chỉ đọc, không gửi bất kỳ lệnh ghi nào")
    parser.add_argument("--rtt-count", type=int, default=200, help="Số lần gửi để đo thống kê RTT (mặc định: 200)")
    parser.add_argument("--output", default="probe_results.json", help="File JSON lưu kết quả đo (mặc định: probe_results.json)")

    args = parser.parse_args()

    out_path = Path(args.output).resolve()
    prober = HardwareProber(
        ip=args.ip,
        port=args.port,
        target_ch=args.target_ch,
        target_band=args.target_band,
        dry_read=args.dry_read,
        rtt_count=args.rtt_count,
        output_file=out_path,
    )
    prober.run_all()


if __name__ == "__main__":
    main()
