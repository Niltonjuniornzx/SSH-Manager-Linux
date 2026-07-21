"""Modelos de túneis SSH."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class TunnelType(str, Enum):
    LOCAL = "local"
    REMOTE = "remote"
    DYNAMIC = "dynamic"  # SOCKS5

    @property
    def label_pt(self) -> str:
        return {
            TunnelType.LOCAL: "Encaminhamento local",
            TunnelType.REMOTE: "Encaminhamento remoto",
            TunnelType.DYNAMIC: "Proxy SOCKS5 dinâmico",
        }[self]


class TunnelStatus(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"
    RECONNECTING = "reconnecting"

    @property
    def label_pt(self) -> str:
        return {
            TunnelStatus.STOPPED: "Parado",
            TunnelStatus.STARTING: "Iniciando…",
            TunnelStatus.RUNNING: "Ativo",
            TunnelStatus.ERROR: "Erro",
            TunnelStatus.RECONNECTING: "Reconectando…",
        }[self]


@dataclass
class TunnelProfile:
    id: Optional[int] = None
    server_id: Optional[int] = None
    name: str = ""
    tunnel_type: TunnelType = TunnelType.LOCAL
    listen_address: str = "127.0.0.1"
    listen_port: int = 0
    dest_host: str = "127.0.0.1"
    dest_port: int = 0
    auto_start: bool = False
    auto_reconnect: bool = True
    local_only: bool = True  # força 127.0.0.1 se True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    # Estado em memória
    status: TunnelStatus = field(default=TunnelStatus.STOPPED, repr=False)
    bytes_sent: int = field(default=0, repr=False)
    bytes_received: int = field(default=0, repr=False)
    error_message: str = field(default="", repr=False)
    active_connections: int = field(default=0, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "server_id": self.server_id,
            "name": self.name,
            "tunnel_type": self.tunnel_type.value,
            "listen_address": self.listen_address,
            "listen_port": self.listen_port,
            "dest_host": self.dest_host,
            "dest_port": self.dest_port,
            "auto_start": self.auto_start,
            "auto_reconnect": self.auto_reconnect,
            "local_only": self.local_only,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> TunnelProfile:
        ttype = row.get("tunnel_type") or TunnelType.LOCAL.value
        try:
            tunnel_type = TunnelType(ttype)
        except ValueError:
            tunnel_type = TunnelType.LOCAL
        return cls(
            id=row.get("id"),
            server_id=row.get("server_id"),
            name=row.get("name") or "",
            tunnel_type=tunnel_type,
            listen_address=row.get("listen_address") or "127.0.0.1",
            listen_port=int(row.get("listen_port") or 0),
            dest_host=row.get("dest_host") or "127.0.0.1",
            dest_port=int(row.get("dest_port") or 0),
            auto_start=bool(row.get("auto_start")),
            auto_reconnect=bool(row.get("auto_reconnect", 1)),
            local_only=bool(row.get("local_only", 1)),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.name.strip():
            errors.append("Nome do túnel é obrigatório.")
        if self.server_id is None:
            errors.append("Perfil SSH é obrigatório.")
        if not (0 <= self.listen_port <= 65535):
            errors.append("Porta de escuta inválida.")
        if self.tunnel_type != TunnelType.DYNAMIC:
            if not self.dest_host.strip():
                errors.append("Host de destino é obrigatório.")
            if not (1 <= self.dest_port <= 65535):
                errors.append("Porta de destino deve estar entre 1 e 65535.")
        if self.local_only and self.listen_address not in ("127.0.0.1", "localhost", "::1"):
            errors.append(
                "Com 'somente local' o endereço de escuta deve ser 127.0.0.1."
            )
        if self.listen_address in ("0.0.0.0", "::", "*") and self.local_only:
            errors.append(
                "Expor em 0.0.0.0 exige desmarcar 'somente conexões locais' "
                "e confirmação explícita."
            )
        return errors

    def effective_listen_address(self) -> str:
        if self.local_only:
            return "127.0.0.1"
        return self.listen_address or "127.0.0.1"
