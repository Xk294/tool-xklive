"""Kiểm thử độ bền bỉ và Fuzzing cho parser/encoder OSC."""

import pytest
from hypothesis import given, strategies as st
from auto_sound.mixer.osc import decode_message, encode_message, OscParseError


def test_encode_decode_roundtrip_valid() -> None:
    """Kiểm tra mã hóa và giải mã các gói tin hợp lệ."""
    data = encode_message("/ch/01/eq/1/f", 0.75)
    addr, args = decode_message(data)
    assert addr == "/ch/01/eq/1/f"
    assert len(args) == 1
    assert pytest.approx(args[0]) == 0.75

    data2 = encode_message("/xinfo", "XR18", 123)
    addr2, args2 = decode_message(data2)
    assert addr2 == "/xinfo"
    assert args2 == ["XR18", 123]


def test_malformed_truncated_packets() -> None:
    """Các gói tin bị cắt cụt, thiếu null byte phải ném OscParseError, không được crash."""
    with pytest.raises(OscParseError):
        decode_message(b"")

    with pytest.raises(OscParseError):
        decode_message(b"/x")  # < 4 bytes

    with pytest.raises(OscParseError):
        decode_message(b"/xinfo")  # len = 6 (không chia hết cho 4)

    with pytest.raises(OscParseError):
        decode_message(b"abcd")  # không bắt đầu bằng '/'

    with pytest.raises(OscParseError):
        decode_message(b"/abcdefgh")  # không có ký tự kết thúc null


@given(st.binary(min_size=0, max_size=512))
def test_fuzz_random_bytes_never_crash(random_bytes: bytes) -> None:
    """Fuzzing với chuỗi bytes ngẫu nhiên: chỉ được phép giải mã thành công hoặc ném OscParseError."""
    try:
        addr, args = decode_message(random_bytes)
        assert isinstance(addr, str)
        assert isinstance(args, list)
    except OscParseError:
        pass
