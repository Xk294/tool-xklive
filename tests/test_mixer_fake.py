"""Kiểm thử hoạt động của server giả lập FakeXR18."""

import socket
import time
import pytest
from auto_sound.mixer.fake import FakeXR18
from auto_sound.mixer.osc import decode_message, encode_message


@pytest.fixture
def fake_server():
    server = FakeXR18(host="127.0.0.1", port=0, max_clients=4)
    server.start()
    yield server
    server.stop()


def test_fake_xinfo_response(fake_server: FakeXR18) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(1.0)
    sock.sendto(encode_message("/xinfo"), (fake_server.host, fake_server.port))

    data, _ = sock.recvfrom(1024)
    addr, args = decode_message(data)
    assert addr == "/xinfo"
    assert "XR18" in args
    sock.close()


def test_fake_param_get_set(fake_server: FakeXR18) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(1.0)

    # Set tham số
    target_addr = "/ch/01/eq/1/f"
    sock.sendto(encode_message(target_addr, 0.85), (fake_server.host, fake_server.port))
    time.sleep(0.05)

    # Query lại
    sock.sendto(encode_message(target_addr), (fake_server.host, fake_server.port))
    data, _ = sock.recvfrom(1024)
    addr, args = decode_message(data)
    assert addr == target_addr
    assert pytest.approx(args[0]) == 0.85
    sock.close()


def test_fake_max_4_clients(fake_server: FakeXR18) -> None:
    sockets = []
    # Tạo 4 client hợp lệ
    for _ in range(4):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.sendto(encode_message("/xremote"), (fake_server.host, fake_server.port))
        sockets.append(s)

    time.sleep(0.1)
    with fake_server._lock:
        assert len(fake_server.clients) == 4

    # Tạo client thứ 5
    s5 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s5.sendto(encode_message("/xremote"), (fake_server.host, fake_server.port))
    time.sleep(0.1)

    # Client thứ 5 bị bỏ qua, danh sách vẫn giữ 4
    with fake_server._lock:
        assert len(fake_server.clients) == 4

    for s in sockets:
        s.close()
    s5.close()
