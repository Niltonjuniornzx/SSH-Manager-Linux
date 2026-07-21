"""Túneis locais, remotos e SOCKS5 via AsyncSSH."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

import asyncssh

from app.models.tunnel import TunnelProfile, TunnelStatus, TunnelType
from app.utils.network import find_free_port, is_port_in_use
from app.utils.sanitize import sanitize_for_log

logger = logging.getLogger(__name__)

GetConnection = Callable[[int], Optional[asyncssh.SSHClientConnection]]
StatusCallback = Callable[[TunnelProfile], None]


class TunnelManager:
    """Inicia/para túneis e rastreia estado em memória."""

    def __init__(
        self,
        get_connection: GetConnection,
        on_status: Optional[StatusCallback] = None,
    ) -> None:
        self.get_connection = get_connection
        self.on_status = on_status
        self._listeners: dict[int, Any] = {}  # tunnel_id -> listener/forwarder
        self._profiles: dict[int, TunnelProfile] = {}
        self._tasks: dict[int, asyncio.Task[None]] = {}

    def get_profile(self, tunnel_id: int) -> Optional[TunnelProfile]:
        return self._profiles.get(tunnel_id)

    def list_active(self) -> list[TunnelProfile]:
        return [
            p
            for p in self._profiles.values()
            if p.status == TunnelStatus.RUNNING
        ]

    def validate_port(
        self,
        listen_port: int,
        listen_address: str = "127.0.0.1",
        *,
        exclude_id: Optional[int] = None,
    ) -> list[str]:
        errors: list[str] = []
        if listen_port == 0:
            return errors  # auto
        if not (1 <= listen_port <= 65535):
            errors.append("Porta de escuta inválida.")
            return errors
        # conflito com túneis ativos
        for tid, profile in self._profiles.items():
            if exclude_id is not None and tid == exclude_id:
                continue
            if (
                profile.status == TunnelStatus.RUNNING
                and profile.listen_port == listen_port
                and profile.effective_listen_address() == listen_address
            ):
                errors.append(
                    f"Porta {listen_port} já em uso pelo túnel '{profile.name}'."
                )
        if is_port_in_use(listen_port, listen_address):
            errors.append(f"Porta {listen_port} já está em uso no sistema.")
        return errors

    def allocate_port(self, listen_address: str = "127.0.0.1") -> int:
        return find_free_port(listen_address)

    async def start(self, profile: TunnelProfile) -> TunnelProfile:
        if profile.id is None:
            raise ValueError("Túnel sem id")
        if profile.server_id is None:
            raise ValueError("Túnel sem server_id")

        # Segurança: não expor 0.0.0.0 sem confirmação (local_only)
        listen_addr = profile.effective_listen_address()
        if listen_addr in ("0.0.0.0", "::", "*") and profile.local_only:
            raise RuntimeError(
                "Expor túnel em 0.0.0.0 exige desmarcar 'somente conexões locais' "
                "e confirmação explícita."
            )

        listen_port = profile.listen_port
        if listen_port == 0:
            listen_port = self.allocate_port(listen_addr)
            profile.listen_port = listen_port

        errors = self.validate_port(listen_port, listen_addr, exclude_id=profile.id)
        if errors:
            profile.status = TunnelStatus.ERROR
            profile.error_message = errors[0]
            self._emit(profile)
            raise RuntimeError(errors[0])

        conn = self.get_connection(profile.server_id)
        closed = True
        if conn is not None:
            try:
                closed = bool(conn.is_closed()) if hasattr(conn, "is_closed") else False
            except Exception:  # noqa: BLE001
                closed = True
        if conn is None or closed:
            profile.status = TunnelStatus.ERROR
            profile.error_message = "Sem conexão SSH. Conecte-se ao servidor primeiro."
            self._emit(profile)
            raise RuntimeError(profile.error_message)

        profile.status = TunnelStatus.STARTING
        profile.error_message = ""
        self._profiles[profile.id] = profile
        self._emit(profile)

        try:
            if profile.tunnel_type == TunnelType.LOCAL:
                listener = await conn.forward_local_port(
                    listen_addr,
                    listen_port,
                    profile.dest_host,
                    profile.dest_port,
                )
                self._listeners[profile.id] = listener
            elif profile.tunnel_type == TunnelType.REMOTE:
                listener = await conn.forward_remote_port(
                    listen_addr if listen_addr != "127.0.0.1" else "",
                    listen_port,
                    profile.dest_host,
                    profile.dest_port,
                )
                self._listeners[profile.id] = listener
            elif profile.tunnel_type == TunnelType.DYNAMIC:
                listener = await conn.forward_socks(
                    listen_addr,
                    listen_port,
                )
                self._listeners[profile.id] = listener
            else:
                raise RuntimeError(f"Tipo de túnel desconhecido: {profile.tunnel_type}")

            profile.status = TunnelStatus.RUNNING
            profile.listen_port = listen_port
            self._emit(profile)
            logger.info(
                sanitize_for_log(
                    "Túnel iniciado",
                    name=profile.name,
                    type=profile.tunnel_type.value,
                    listen=f"{listen_addr}:{listen_port}",
                )
            )
        except Exception as exc:  # noqa: BLE001
            profile.status = TunnelStatus.ERROR
            profile.error_message = str(exc)
            self._emit(profile)
            logger.error(
                sanitize_for_log("Falha ao iniciar túnel", name=profile.name, error=str(exc))
            )
            raise

        return profile

    async def stop(self, tunnel_id: int) -> None:
        profile = self._profiles.get(tunnel_id)
        listener = self._listeners.pop(tunnel_id, None)
        task = self._tasks.pop(tunnel_id, None)
        if task:
            task.cancel()
        if listener is not None:
            try:
                listener.close()
                if hasattr(listener, "wait_closed"):
                    await listener.wait_closed()
            except Exception:  # noqa: BLE001
                pass
        if profile:
            profile.status = TunnelStatus.STOPPED
            profile.active_connections = 0
            self._emit(profile)
            logger.info(sanitize_for_log("Túnel encerrado", name=profile.name))

    async def restart(self, profile: TunnelProfile) -> TunnelProfile:
        if profile.id is not None:
            await self.stop(profile.id)
        return await self.start(profile)

    async def stop_all(self) -> None:
        ids = list(self._listeners.keys())
        for tid in ids:
            await self.stop(tid)

    async def stop_for_server(self, server_id: int) -> None:
        ids = [
            tid
            for tid, p in self._profiles.items()
            if p.server_id == server_id and p.status == TunnelStatus.RUNNING
        ]
        for tid in ids:
            await self.stop(tid)

    async def start_auto(self, profiles: list[TunnelProfile]) -> None:
        for p in profiles:
            if p.auto_start:
                try:
                    await self.start(p)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        sanitize_for_log(
                            "Auto-start de túnel falhou", name=p.name, error=str(exc)
                        )
                    )

    def _emit(self, profile: TunnelProfile) -> None:
        if self.on_status:
            try:
                self.on_status(profile)
            except Exception:  # noqa: BLE001
                pass
