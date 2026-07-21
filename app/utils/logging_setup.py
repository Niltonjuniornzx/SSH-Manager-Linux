"""Configuração de logging com sanitização automática."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from app.utils.paths import logs_dir
from app.utils.sanitize import redact_secrets


class SanitizingFormatter(logging.Formatter):
    """Formatter que redige segredos de todas as mensagens."""

    def format(self, record: logging.LogRecord) -> str:
        original_msg = record.getMessage()
        record.msg = redact_secrets(str(record.msg))
        if record.args:
            # Evitar formatação com args sensíveis — já redigimos msg
            record.args = ()
        try:
            return super().format(record)
        finally:
            record.msg = original_msg


def setup_logging(level: str = "INFO", log_file: Optional[Path] = None) -> logging.Logger:
    """Configura logging para console e arquivo rotativo."""
    root = logging.getLogger("app")
    root.handlers.clear()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    fmt = SanitizingFormatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(fmt)
    console.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.addHandler(console)

    path = log_file or (logs_dir() / "app.log")
    try:
        file_handler = RotatingFileHandler(
            path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        file_handler.setLevel(logging.DEBUG)
        root.addHandler(file_handler)
        # permissão 0600 no log
        try:
            path.chmod(0o600)
        except OSError:
            pass
    except OSError:
        pass

    # Silenciar loggers verbosos
    logging.getLogger("asyncssh").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    return root
