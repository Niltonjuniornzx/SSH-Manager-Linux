"""Configurações da aplicação."""

from __future__ import annotations

from dataclasses import dataclass, asdict, fields
from pathlib import Path
from typing import Any


@dataclass
class AppSettings:
    theme: str = "dark"  # apenas dark
    language: str = "pt_BR"  # pt_BR | en
    external_terminal: str = "auto"  # auto, konsole, gnome-terminal, xterm
    external_editor: str = ""
    rdp_client: str = "auto"
    vnc_client: str = "auto"
    rustdesk_client: str = "auto"
    default_timeout: int = 30
    default_keepalive: int = 30
    auto_reconnect: bool = False
    max_concurrent_transfers: int = 3
    speed_limit_bps: int = 0  # 0 = ilimitado
    confirm_delete: bool = True
    show_hidden_files: bool = False
    default_download_dir: str = ""
    lock_timeout_minutes: int = 0  # 0 = desabilitado
    master_password_enabled: bool = False
    master_password_hash: str = ""  # Argon2id versionado; nunca exportar
    notifications: bool = True
    terminal_font: str = "Monospace"
    terminal_font_size: int = 11
    conflict_policy: str = "ask"
    verify_transfer_hash: bool = False
    log_level: str = "INFO"
    window_geometry: str = ""
    sidebar_width: int = 280

    def __post_init__(self) -> None:
        if not self.default_download_dir:
            self.default_download_dir = str(Path.home() / "Downloads")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppSettings:
        known = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)
