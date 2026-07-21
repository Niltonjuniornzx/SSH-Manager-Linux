"""Gerenciador de sessões SSH ativas em memória."""

from __future__ import annotations

import logging
from typing import Optional

from app.models.server import ConnectionStatus, ServerProfile
from app.ssh.client import SSHClient
from app.utils.sanitize import sanitize_for_log

logger = logging.getLogger(__name__)


class SessionManager:
    """Mantém clientes SSH ativos indexados por server_id."""

    def __init__(self) -> None:
        self._clients: dict[int, SSHClient] = {}
        self._status: dict[int, ConnectionStatus] = {}

    def get(self, server_id: int) -> Optional[SSHClient]:
        return self._clients.get(server_id)

    def set(self, server_id: int, client: SSHClient) -> None:
        self._clients[server_id] = client
        self._status[server_id] = ConnectionStatus.CONNECTED

    def remove(self, server_id: int) -> Optional[SSHClient]:
        self._status[server_id] = ConnectionStatus.DISCONNECTED
        return self._clients.pop(server_id, None)

    def status(self, server_id: int) -> ConnectionStatus:
        client = self._clients.get(server_id)
        if client and client.is_connected:
            return ConnectionStatus.CONNECTED
        return self._status.get(server_id, ConnectionStatus.DISCONNECTED)

    def set_status(self, server_id: int, status: ConnectionStatus) -> None:
        self._status[server_id] = status

    def is_connected(self, server_id: int) -> bool:
        client = self._clients.get(server_id)
        return bool(client and client.is_connected)

    def list_connected(self) -> list[int]:
        return [sid for sid, c in self._clients.items() if c.is_connected]

    async def disconnect(self, server_id: int) -> None:
        client = self.remove(server_id)
        if client:
            await client.disconnect()
            logger.info(sanitize_for_log("Sessão encerrada", server_id=server_id))

    async def disconnect_all(self) -> None:
        ids = list(self._clients.keys())
        for sid in ids:
            await self.disconnect(sid)

    def get_profile(self, server_id: int) -> Optional[ServerProfile]:
        client = self._clients.get(server_id)
        return client.profile if client else None
