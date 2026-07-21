"""Modelos de servidor e grupos."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


class AuthMethod(str, Enum):
    PASSWORD = "password"
    KEY = "key"
    KEY_PASSPHRASE = "key_passphrase"
    AGENT = "agent"

    @property
    def label_pt(self) -> str:
        return {
            AuthMethod.PASSWORD: "Senha",
            AuthMethod.KEY: "Chave SSH",
            AuthMethod.KEY_PASSPHRASE: "Chave SSH com passphrase",
            AuthMethod.AGENT: "SSH Agent",
        }[self]


class ConnectionStatus(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"
    RECONNECTING = "reconnecting"

    @property
    def label_pt(self) -> str:
        return {
            ConnectionStatus.DISCONNECTED: "Desconectado",
            ConnectionStatus.CONNECTING: "Conectando…",
            ConnectionStatus.CONNECTED: "Conectado",
            ConnectionStatus.ERROR: "Erro",
            ConnectionStatus.RECONNECTING: "Reconectando…",
        }[self]


@dataclass
class ServerGroup:
    id: Optional[int] = None
    name: str = "Padrão"
    color: str = "#4a9eff"
    sort_order: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ServerGroup:
        return cls(
            id=row.get("id"),
            name=row.get("name") or "Padrão",
            color=row.get("color") or "#4a9eff",
            sort_order=int(row.get("sort_order") or 0),
        )


@dataclass
class ServerProfile:
    id: Optional[int] = None
    name: str = ""
    group_id: Optional[int] = None
    description: str = ""
    host: str = ""
    port: int = 22
    username: str = ""
    auth_method: AuthMethod = AuthMethod.PASSWORD
    private_key_path: str = ""
    # Referência keyring (não a senha em si)
    credential_key: str = ""
    remote_path: str = "~"
    local_path: str = ""
    timeout: int = 30
    keepalive: int = 30
    terminal_encoding: str = "utf-8"
    color: str = "#4a9eff"
    auto_reconnect: bool = False
    jump_host_id: Optional[int] = None
    remember_credential: bool = True
    # Metadados de UI (não sensíveis)
    last_connected_at: Optional[str] = None
    last_latency_ms: Optional[float] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    # Estado em memória (não persistido)
    status: ConnectionStatus = field(default=ConnectionStatus.DISCONNECTED, repr=False)
    group_name: str = field(default="", repr=False)

    def to_dict(self, *, for_export: bool = False) -> dict[str, Any]:
        data = {
            "id": self.id,
            "name": self.name,
            "group_id": self.group_id,
            "description": self.description,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "auth_method": (
                self.auth_method.value
                if hasattr(self.auth_method, "value")
                else str(self.auth_method)
            ),
            "private_key_path": self.private_key_path if not for_export else "",
            "credential_key": "" if for_export else self.credential_key,
            "remote_path": self.remote_path,
            "local_path": self.local_path,
            "timeout": self.timeout,
            "keepalive": self.keepalive,
            "terminal_encoding": self.terminal_encoding,
            "color": self.color,
            "auto_reconnect": self.auto_reconnect,
            "jump_host_id": self.jump_host_id,
            "remember_credential": self.remember_credential,
            "last_connected_at": self.last_connected_at,
            "last_latency_ms": self.last_latency_ms,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        return data

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ServerProfile:
        auth = row.get("auth_method") or AuthMethod.PASSWORD.value
        try:
            auth_method = AuthMethod(auth)
        except ValueError:
            auth_method = AuthMethod.PASSWORD
        return cls(
            id=row.get("id"),
            name=row.get("name") or "",
            group_id=row.get("group_id"),
            description=row.get("description") or "",
            host=row.get("host") or "",
            port=int(row.get("port") or 22),
            username=row.get("username") or "",
            auth_method=auth_method,
            private_key_path=row.get("private_key_path") or "",
            credential_key=row.get("credential_key") or "",
            remote_path=row.get("remote_path") or "~",
            local_path=row.get("local_path") or "",
            timeout=int(row.get("timeout") or 30),
            keepalive=int(row.get("keepalive") or 30),
            terminal_encoding=row.get("terminal_encoding") or "utf-8",
            color=row.get("color") or "#4a9eff",
            auto_reconnect=bool(row.get("auto_reconnect")),
            jump_host_id=row.get("jump_host_id"),
            remember_credential=bool(row.get("remember_credential", 1)),
            last_connected_at=row.get("last_connected_at"),
            last_latency_ms=row.get("last_latency_ms"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
            group_name=row.get("group_name") or "",
        )

    def validate(self) -> list[str]:
        """Valida campos obrigatórios. Retorna lista de erros em PT."""
        errors: list[str] = []
        if not self.name.strip():
            errors.append("Nome da conexão é obrigatório.")
        if not self.host.strip():
            errors.append("IP ou hostname é obrigatório.")
        if not (1 <= self.port <= 65535):
            errors.append("Porta SSH deve estar entre 1 e 65535.")
        if not self.username.strip():
            errors.append("Nome de usuário é obrigatório.")
        if self.auth_method in (AuthMethod.KEY, AuthMethod.KEY_PASSPHRASE):
            if not self.private_key_path.strip():
                errors.append("Caminho da chave privada é obrigatório para autenticação por chave.")
        if self.timeout < 1:
            errors.append("Timeout deve ser pelo menos 1 segundo.")
        if self.keepalive < 0:
            errors.append("Keep-alive não pode ser negativo.")
        if self.jump_host_id is not None and self.jump_host_id == self.id and self.id is not None:
            errors.append("O servidor não pode ser jump host de si mesmo.")
        return errors

    def display_host(self) -> str:
        return f"{self.host}:{self.port}" if self.port != 22 else self.host

    def credential_service_key(self) -> str:
        """Chave estável para o keyring."""
        if self.credential_key:
            return self.credential_key
        if self.id is not None:
            return f"server-{self.id}"
        return f"server-{self.host}-{self.username}-{self.port}"
