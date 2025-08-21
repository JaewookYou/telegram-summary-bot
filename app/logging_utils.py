from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logging(
    *,
    log_dir: str = "logs",
    log_level: str = "INFO",  # INFO로 변경하여 DEBUG 출력 제거
    log_file: str = "app.log",
    error_log_file: str = "error.log",
) -> None:
    os.makedirs(log_dir, exist_ok=True)

    level = getattr(logging, log_level.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Quiet overly verbose third parties by default
    logging.getLogger("telethon").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(fmt)
    root_logger.addHandler(ch)

    # Rotating app log
    app_path = os.path.join(log_dir, log_file)
    fh = RotatingFileHandler(app_path, maxBytes=5 * 1024 * 1024, backupCount=5)
    fh.setLevel(level)
    fh.setFormatter(fmt)
    root_logger.addHandler(fh)

    # Rotating error-only log
    err_path = os.path.join(log_dir, error_log_file)
    eh = RotatingFileHandler(err_path, maxBytes=5 * 1024 * 1024, backupCount=5)
    eh.setLevel(logging.ERROR)
    eh.setFormatter(fmt)
    root_logger.addHandler(eh)


