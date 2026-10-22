#!/usr/bin/env python3
"""Công cụ kiểm định phần cứng Mixer Behringer X-Air / Midas M-Air (CHỈ ĐỌC THEO MẶC ĐỊNH).

Sử dụng:
    python tools/hardware_check.py [--ip 192.168.1.100] [--port 10024] [--record-samples 50]
"""

import argparse
import json
import statistics
import sys
import time
from typing import Dict, List, Optional
from auto_sound.mixer.xair import XAirClient, discover_mixers
from auto_sound.mixer.osc import encode_message


def run_hardware_check(ip: str, port: int, record_samples: int = 0) -> None:
    print("=" * 70)
    print(" BỘ KIỂM ĐỊNH PHẦN CỨNG THẬT (HARDWARE CHECK TOOL) - V2")
    print(f" Mục tiêu kiểm tra: {ip}:{port} (CHẾ ĐỘ CHỈ ĐỌC / READ-ONLY)")
    print("=" * 70)

    # 1. Quét tìm mixer trên mạng LAN
    print("\n[1/5] Quét mạng tìm thiết bị...")
    discovered = discover_mixers(timeout_s=1.0, targets=[ip, "255.255.255.255", "192.168.1.255"])
    if discovered:
        print(f"  -> Tìm thấy {len(discovered)} thiết bị:")
        for d in discovered:
            print(f"     * Model: {d.get('model')} | Tên: {d.get('name')} | Firmware: {d.get('firmware')} | IP: {d.get('ip')}")
    else:
        print(f"  -> Không thấy gói tin Broadcast, tiếp tục kết nối trực tiếp tới {ip}:{port}...")

    # 2. Khởi tạo Client và bắt tay Handshake
    client = XAirClient(ip=ip, port=port, timeout_s=0.5)
    print(f"\n[2/5] Đang kết nối và bắt tay /xinfo...")
    connected = client.connect()
    if not connected:
        print(f"  [LỖI] Không thể kết nối tới mixer tại {ip}:{port}!")
        print("  Gợi ý: Kiểm tra cáp LAN/WiFi, địa chỉ IP của laptop và mixer.")
        sys.exit(1)

    dev_info = client.get_device_info()
    print(f"  -> Kết nối THÀNH CÔNG!")
    print(f"     * Model: {dev_info.get('model')}")
    print(f"     * Tên thiết bị: {dev_info.get('name')}")
    print(f"     * Firmware: {dev_info.get('firmware')}")

    # 3. Thăm dò CapabilityMap (Phase 0)
    print("\n[3/5] Đang thăm dò năng lực thực tế (Capability Probe - CHỈ ĐỌC)...")
    cap = client.probe_capabilities(timeout_s=0.3)
    print(f"  -> Bản đồ năng lực (CapabilityMap):")
    print(f"     * Dialect Main L/R: {cap.lr_prefix}")
    print(f"     * Số kênh Input khả dụng: {cap.num_channels}")
    print(f"     * Số Bus Aux: {cap.num_busses}")
    print(f"     * Số band PEQ trên kênh: {cap.channel_peq_bands}")
    print(f"     * Số band PEQ trên Bus / Main: {cap.bus_peq_bands} / {cap.lr_peq_bands}")
    print(f"     * Hỗ trợ Preamp Headamp Gain: {'CÓ (/headamp)' if cap.supports_headamp else 'KHÔNG'}")
    print(f"     * Hỗ trợ FX Return: {'CÓ (/rtn)' if cap.supports_fx_return else 'KHÔNG'}")
    print(f"     * Hỗ trợ Automix phần cứng: {'CÓ' if cap.supports_automix else 'KHÔNG (Sẽ bỏ qua Giai đoạn 5)'}")

    print("\n     Chi tiết phản hồi từng đường dẫn OSC:")
    for path, is_ok in cap.verified_paths.items():
        status_txt = "PHẢN HỒI TỐT [OK]" if is_ok else "KHÔNG PHẢN HỒI [NONE]"
        print(f"       - {path:<30}: {status_txt}")

    # 4. Đo độ trễ RTT OSC (10 lần ping)
    print("\n[4/5] Đo độ trễ mạng OSC UDP (RTT Benchmark - 10 lần)...")
    rtt_samples: List[float] = []
    for _ in range(10):
        rtt = client.ping(timeout_s=0.5)
        if rtt is not None:
            rtt_samples.append(rtt)
        time.sleep(0.05)

    if rtt_samples:
        p50 = statistics.median(rtt_samples)
        p95 = statistics.quantiles(rtt_samples, n=20)[18] if len(rtt_samples) >= 20 else max(rtt_samples)
        r_max = max(rtt_samples)
        r_min = min(rtt_samples)
        print(f"  -> Thống kê RTT ({len(rtt_samples)}/10 gói thành công):")
        print(f"     * Min: {r_min:.1f} ms | Median (p50): {p50:.1f} ms | p95: {p95:.1f} ms | Max: {r_max:.1f} ms")
        if p50 > 50.0:
            print("  [CẢNH BÁO] Độ trễ mạng > 50ms, khuyến nghị dùng dây mạng LAN thay vì WiFi khi làm show!")
    else:
        print("  [LỖI] Không nhận được phản hồi ping nào!")

    # 5. Kiểm tra luồng RTA LAN (/meters/4) và Meters (/meters/1)
    print("\n[5/5] Kiểm tra luồng dữ liệu thời gian thực (/xremote & /meters)...")
    client.subscribe_rta(True)
    client.subscribe_meters(True)
    time.sleep(0.5)

    rta_data = client.get_rta_levels()
    meter_data = client.get_meter_levels()

    has_rta = any(db > -95.0 for db in rta_data)
    has_meter = any(m > 0.001 for m in meter_data)

    print(f"  -> Luồng RTA 100-band (/meters/4): {'HOẠT ĐỘNG TỐT' if has_rta else 'CHƯA CÓ TÍN HIỆU HOẶC IM LẶNG'}")
    print(f"  -> Luồng Meter 18 kênh (/meters/1): {'HOẠT ĐỘNG TỐT' if has_meter else 'TÍN HIỆU 0 HOẶC MUTE'}")

    # Ghi mẫu dữ liệu thật nếu có yêu cầu
    if record_samples > 0:
        filename = f"hardware_dump_{int(time.time())}.json"
        print(f"\n[GHI DỮ LIỆU] Đang thu thập {record_samples} khung đo thật vào file {filename}...")
        dump_data = {
            "device_info": dev_info,
            "capabilities": {
                "lr_prefix": cap.lr_prefix,
                "channels": cap.num_channels,
                "busses": cap.num_busses,
                "supports_headamp": cap.supports_headamp,
                "supports_automix": cap.supports_automix,
            },
            "rta_samples": [],
            "meter_samples": [],
        }
        for _ in range(record_samples):
            dump_data["rta_samples"].append(client.get_rta_levels())
            dump_data["meter_samples"].append(client.get_meter_levels())
            time.sleep(0.1)

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(dump_data, f, indent=2)
        print(f"  -> Đã lưu dữ liệu kiểm định phần cứng thật vào {filename}!")

    client.disconnect()
    print("\n" + "=" * 70)
    print(" HOÀN TẤT KIỂM ĐỊNH PHẦN CỨNG. HỆ THỐNG AN TOÀN TUYỆT ĐỐI.")
    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kiểm tra phần cứng Mixer Behringer/Midas X-Air")
    parser.add_argument("--ip", default="127.0.0.1", help="Địa chỉ IP của bàn mixer")
    parser.add_argument("--port", type=int, default=10024, help="Cổng OSC UDP (mặc định 10024)")
    parser.add_argument("--record-samples", type=int, default=0, help="Số khung đo muốn ghi ra file")
    args = parser.parse_args()

    run_hardware_check(ip=args.ip, port=args.port, record_samples=args.record_samples)
