"""Bộ mã hóa và giải mã gói tin OSC (Open Sound Control) an toàn, chống crash/fuzz."""

from __future__ import annotations
from typing import Any, List, Tuple
from pythonosc.osc_message_builder import OscMessageBuilder
from pythonosc.osc_message import OscMessage, ParseError


class OscParseError(Exception):
    """Lỗi khi gói tin OSC bị sai định dạng, bị cắt cụt hoặc chứa dữ liệu hỏng."""
    pass


def encode_message(address: str, *args: Any) -> bytes:
    """Mã hóa địa chỉ OSC và các đối số thành mảng bytes chuẩn OSC (căn hàng 4 bytes)."""
    if not address or not address.startswith("/"):
        raise ValueError(f"Địa chỉ OSC phải bắt đầu bằng '/': {address}")

    builder = OscMessageBuilder(address=address)
    for arg in args:
        builder.add_arg(arg)
    try:
        msg = builder.build()
        return msg.dgram
    except Exception as e:
        raise OscParseError(f"Không thể mã hóa gói tin OSC: {e}") from e


def decode_message(dgram: bytes) -> Tuple[str, List[Any]]:
    """Giải mã mảng bytes thành (địa chỉ OSC, danh sách đối số).
    
    Bảo đảm không bao giờ sập chương trình hoặc treo vô hạn khi gặp gói tin rác/cụt.
    """
    if not isinstance(dgram, (bytes, bytearray)):
        raise OscParseError("Dữ liệu đầu vào phải là bytes hoặc bytearray")

    if len(dgram) < 4:
        raise OscParseError(f"Gói tin quá ngắn (<4 bytes): {len(dgram)}")

    # Gói tin OSC chuẩn bắt buộc phải là bội số của 4 bytes
    if len(dgram) % 4 != 0:
        raise OscParseError(f"Độ dài gói tin không chia hết cho 4: {len(dgram)}")

    # Địa chỉ OSC phải bắt đầu bằng ký tự '/' (0x2F)
    if dgram[0] != 0x2F:
        raise OscParseError(f"Địa chỉ OSC không bắt đầu bằng '/': {dgram[:4]!r}")

    # Chuỗi địa chỉ OSC phải có ký tự kết thúc '\0'
    null_idx = dgram.find(b"\x00")
    if null_idx == -1:
        raise OscParseError("Chuỗi địa chỉ OSC không có ký tự kết thúc null '\\0'")

    try:
        msg = OscMessage(dgram)
        # Truy cập các trường để kiểm tra xem có phát sinh lỗi ngầm nào không
        address = msg.address
        params = list(msg.params)
        return address, params
    except (ParseError, ValueError, IndexError, TypeError) as e:
        raise OscParseError(f"Lỗi cú pháp gói tin OSC: {e}") from e
    except Exception as e:
        raise OscParseError(f"Lỗi không xác định khi giải mã OSC: {e}") from e
