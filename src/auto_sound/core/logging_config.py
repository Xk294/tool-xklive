"""Cấu hình ghi log ra file với cơ chế xoay vòng (Rotating File Handler) và định dạng chuẩn."""

from __future__ import annotations
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

LOGGER_NAME = "auto_sound"


def setup_file_logging(
    log_dir: Optional[Path | str] = None,
    log_filename: str = "auto_sound.log",
    max_bytes: int = 5 * 1024 * 1024,  # 5 MB
    backup_count: int = 3,
    level: int = logging.INFO,
) -> Path:
    """Khởi tạo logging xoay vòng ra thư mục logs/, đảm bảo không nuốt exception."""
    if log_dir is None:
        # Mặc định thư mục logs/ ở root dự án
        log_dir = Path(__file__).resolve().parent.parent.parent.parent / "logs"
    else:
        log_dir = Path(log_dir)

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / log_filename

    root_logger = logging.getLogger(LOGGER_NAME)
    root_logger.setLevel(level)

    # Tránh gắn handler lặp lại nếu hàm được gọi nhiều lần
    has_file_handler = any(isinstance(h, RotatingFileHandler) for h in root_logger.handlers)
    if not has_file_handler:
        file_handler = RotatingFileHandler(
            str(log_path),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s:%(lineno)d] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        root_logger.addHandler(file_handler)

    return log_path
