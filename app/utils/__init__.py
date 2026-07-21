"""Utilitários gerais."""

from app.utils.paths import app_data_dir, app_config_dir, ensure_secure_file
from app.utils.sanitize import sanitize_for_log, redact_secrets
from app.utils.network import find_free_port, is_port_in_use, resolve_host
from app.utils.process import run_external, find_executable

__all__ = [
    "app_data_dir",
    "app_config_dir",
    "ensure_secure_file",
    "sanitize_for_log",
    "redact_secrets",
    "find_free_port",
    "is_port_in_use",
    "resolve_host",
    "run_external",
    "find_executable",
]
