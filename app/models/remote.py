"""Modelos de controle remoto (RDP/VNC/RustDesk/custom)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class RemoteProtocol(str, Enum):
    RDP = "rdp"
    VNC = "vnc"
    RUSTDESK = "rustdesk"
    CUSTOM = "custom"

    @property
    def label_pt(self) -> str:
        return {
            RemoteProtocol.RDP: "RDP (FreeRDP)",
            RemoteProtocol.VNC: "VNC (TigerVNC)",
            RemoteProtocol.RUSTDESK: "RustDesk",
            RemoteProtocol.CUSTOM: "Comando personalizado",
        }[self]


class RemoteSessionStatus(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"

    @property
    def label_pt(self) -> str:
        return {
            RemoteSessionStatus.IDLE: "Inativo",
            RemoteSessionStatus.STARTING: "Iniciando…",
            RemoteSessionStatus.RUNNING: "Em execução",
            RemoteSessionStatus.STOPPED: "Encerrado",
            RemoteSessionStatus.ERROR: "Erro",
        }[self]


@dataclass
class RemoteProfile:
    id: Optional[int] = None
    server_id: Optional[int] = None
    enabled: bool = False
    protocol: RemoteProtocol = RemoteProtocol.RDP
    host: str = ""
    use_ssh_host: bool = True
    port: int = 3389
    username: str = ""
    domain: str = ""  # RDP
    rustdesk_id: str = ""  # apenas ID, senha no keyring
    resolution: str = "1920x1080"
    fullscreen: bool = False
    auto_scale: bool = True
    quality: str = "auto"  # auto, high, medium, low
    color_depth: int = 32
    audio: bool = True
    microphone: bool = False
    clipboard: bool = True
    share_folder: str = ""
    view_only: bool = False
    auto_reconnect: bool = False
    protect_with_tunnel: bool = True
    # Comando personalizado: executável + args separados
    custom_executable: str = ""
    custom_args: str = ""  # JSON array de strings
    credential_key: str = ""  # referência keyring
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    status: RemoteSessionStatus = field(default=RemoteSessionStatus.IDLE, repr=False)

    def to_dict(self, *, for_export: bool = False) -> dict[str, Any]:
        return {
            "id": self.id,
            "server_id": self.server_id,
            "enabled": self.enabled,
            "protocol": self.protocol.value,
            "host": self.host,
            "use_ssh_host": self.use_ssh_host,
            "port": self.port,
            "username": self.username,
            "domain": self.domain,
            "rustdesk_id": self.rustdesk_id,
            "resolution": self.resolution,
            "fullscreen": self.fullscreen,
            "auto_scale": self.auto_scale,
            "quality": self.quality,
            "color_depth": self.color_depth,
            "audio": self.audio,
            "microphone": self.microphone,
            "clipboard": self.clipboard,
            "share_folder": self.share_folder,
            "view_only": self.view_only,
            "auto_reconnect": self.auto_reconnect,
            "protect_with_tunnel": self.protect_with_tunnel,
            "custom_executable": self.custom_executable,
            "custom_args": self.custom_args,
            "credential_key": "" if for_export else self.credential_key,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> RemoteProfile:
        proto = row.get("protocol") or RemoteProtocol.RDP.value
        try:
            protocol = RemoteProtocol(proto)
        except ValueError:
            protocol = RemoteProtocol.RDP
        return cls(
            id=row.get("id"),
            server_id=row.get("server_id"),
            enabled=bool(row.get("enabled")),
            protocol=protocol,
            host=row.get("host") or "",
            use_ssh_host=bool(row.get("use_ssh_host", 1)),
            port=int(row.get("port") or 3389),
            username=row.get("username") or "",
            domain=row.get("domain") or "",
            rustdesk_id=row.get("rustdesk_id") or "",
            resolution=row.get("resolution") or "1920x1080",
            fullscreen=bool(row.get("fullscreen")),
            auto_scale=bool(row.get("auto_scale", 1)),
            quality=row.get("quality") or "auto",
            color_depth=int(row.get("color_depth") or 32),
            audio=bool(row.get("audio", 1)),
            microphone=bool(row.get("microphone")),
            clipboard=bool(row.get("clipboard", 1)),
            share_folder=row.get("share_folder") or "",
            view_only=bool(row.get("view_only")),
            auto_reconnect=bool(row.get("auto_reconnect")),
            protect_with_tunnel=bool(row.get("protect_with_tunnel", 1)),
            custom_executable=row.get("custom_executable") or "",
            custom_args=row.get("custom_args") or "",
            credential_key=row.get("credential_key") or "",
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    def default_port_for_protocol(self) -> int:
        return {
            RemoteProtocol.RDP: 3389,
            RemoteProtocol.VNC: 5900,
            RemoteProtocol.RUSTDESK: 0,
            RemoteProtocol.CUSTOM: 0,
        }[self.protocol]

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.enabled:
            return errors
        if self.protocol == RemoteProtocol.CUSTOM:
            if not self.custom_executable.strip():
                errors.append("Executável do comando personalizado é obrigatório.")
        elif self.protocol == RemoteProtocol.RUSTDESK:
            if not self.rustdesk_id.strip():
                errors.append("ID do RustDesk é obrigatório.")
        else:
            if not self.use_ssh_host and not self.host.strip():
                errors.append("Host de controle remoto é obrigatório.")
            if self.port and not (1 <= self.port <= 65535):
                errors.append("Porta de controle remoto inválida.")
        return errors

    def credential_service_key(self) -> str:
        if self.credential_key:
            return self.credential_key
        if self.id is not None:
            return f"remote-{self.id}"
        return f"remote-{self.server_id}-{self.protocol.value}"
