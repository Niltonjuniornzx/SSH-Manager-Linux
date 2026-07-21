"""Cliente SSH baseado em AsyncSSH com verificação de host key pré-autenticação."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import asyncssh

from app.models.server import AuthMethod, ServerProfile
from app.security.credentials import CredentialStore
from app.security.hostkeys import HostKeyDecision, HostKeyManager, HostKeyResult
from app.utils.sanitize import sanitize_for_log

logger = logging.getLogger(__name__)

# AsyncSSH trata known_hosts vazio (b'' / []) como "usar ~/.ssh/known_hosts".
# Isso pula o nosso validate_host_public_key quando o host já está no OpenSSH
# e quebra a política do app. Um comentário é truthy e não confia em nenhuma key.
_EMPTY_KNOWN_HOSTS = b"# ssh-manager-linux empty trusted set\n"


class SSHConnectionError(Exception):
    """Erro de conexão SSH (rede, timeout, host key, etc.)."""

    def __init__(self, message: str, *, code: str = "connection_error") -> None:
        super().__init__(message)
        self.code = code


class SSHAuthError(SSHConnectionError):
    """Falha de autenticação."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="auth_error")


class HostKeyChangedError(SSHConnectionError):
    def __init__(self, result: HostKeyResult) -> None:
        super().__init__(result.message, code="host_key_changed")
        self.result = result


class HostKeyUnknownError(SSHConnectionError):
    def __init__(self, result: HostKeyResult) -> None:
        super().__init__(result.message, code="host_key_unknown")
        self.result = result


class _HostKeyVerifyingClient(asyncssh.SSHClient):
    """
    Valida a host key no handshake SSH (validate_host_public_key).

    Com known_hosts=b'' (vazio, NUNCA None), o AsyncSSH chama este callback
    antes de qualquer userauth — senha, chave, agente ou comando.
    """

    def __init__(
        self,
        host_keys: HostKeyManager,
        *,
        hostname: str,
        port: int,
        auto_accept_new: bool = False,
        session_trusted: bool = False,
    ) -> None:
        super().__init__()
        self._host_keys = host_keys
        self._hostname = hostname
        self._port = port
        self._auto_accept_new = auto_accept_new
        self._session_trusted = session_trusted
        self.host_key_result: Optional[HostKeyResult] = None
        self.auth_phase_reached = False
        self.credentials_sent = False

    def validate_host_public_key(
        self, host: str, addr: str, port: int, key: asyncssh.SSHKey
    ) -> bool:
        check_host = (self._hostname or host or addr or "").strip()
        check_port = int(port or self._port or 22)
        try:
            key_type = str(key.get_algorithm())
            public_data = bytes(key.public_data)
        except Exception as exc:  # noqa: BLE001
            logger.error(sanitize_for_log("Falha ao extrair host key", error=str(exc)))
            return False

        result = self._host_keys.check(check_host, check_port, key_type, public_data)
        self.host_key_result = result

        if result.decision == HostKeyDecision.ACCEPT:
            return True

        if result.decision == HostKeyDecision.CHANGED_BLOCK:
            return False

        # Host key desconhecida
        if self._session_trusted:
            return True

        if self._auto_accept_new and result.is_new:
            self._host_keys.accept(
                result.hostname,
                result.port,
                result.key_type,
                result.fingerprint_sha256,
                result.public_key_b64,
            )
            self.host_key_result = HostKeyResult(
                decision=HostKeyDecision.ACCEPT,
                fingerprint_sha256=result.fingerprint_sha256,
                key_type=result.key_type,
                hostname=result.hostname,
                port=result.port,
                public_key_b64=result.public_key_b64,
                message="Host key aceita automaticamente (teste).",
            )
            return True
        return False

    def auth_completed(self) -> None:
        self.auth_phase_reached = True
        self.credentials_sent = True


@dataclass
class ConnectionResult:
    success: bool
    message: str = ""
    latency_ms: Optional[float] = None
    server_version: str = ""
    fingerprint: str = ""
    error_code: str = ""
    host_key_result: Optional[HostKeyResult] = None


@dataclass
class SSHClient:
    """
    Gerencia uma conexão SSH (e jump chain) para um ServerProfile.

    A host key é sempre validada no handshake, ANTES de:
    - enviar senha
    - desbloquear chave privada
    - usar agente SSH
    """

    profile: ServerProfile
    credentials: CredentialStore
    host_keys: HostKeyManager
    password: Optional[str] = None
    passphrase: Optional[str] = None
    resolve_server: Optional[Callable[[int], Optional[ServerProfile]]] = None
    # Só para testes: aceita host key nova sem UI.
    auto_accept_new_host_key: bool = False

    connection: Optional[asyncssh.SSHClientConnection] = field(default=None, repr=False)
    _jump_connections: list[asyncssh.SSHClientConnection] = field(
        default_factory=list, repr=False
    )
    _connected_at: Optional[float] = field(default=None, repr=False)

    @property
    def is_connected(self) -> bool:
        if self.connection is None:
            return False
        try:
            if hasattr(self.connection, "is_closed"):
                return not bool(self.connection.is_closed())
            return True
        except Exception:  # noqa: BLE001
            return False

    async def connect(self) -> ConnectionResult:
        start = time.perf_counter()
        try:
            conn = await self._connect_profile(self.profile, is_target=True)
            self.connection = conn
            self._connected_at = time.perf_counter()
            latency = (self._connected_at - start) * 1000.0
            version = ""
            try:
                version = conn.get_extra_info("server_version") or ""
                if isinstance(version, bytes):
                    version = version.decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                version = ""
            logger.info(
                sanitize_for_log(
                    "SSH conectado",
                    host=self.profile.host,
                    port=self.profile.port,
                    user=self.profile.username,
                    latency_ms=round(latency, 1),
                )
            )
            return ConnectionResult(
                success=True,
                message="Conectado com sucesso.",
                latency_ms=round(latency, 1),
                server_version=str(version),
            )
        except HostKeyChangedError as exc:
            return ConnectionResult(
                success=False,
                message=str(exc),
                error_code=exc.code,
                host_key_result=exc.result,
            )
        except HostKeyUnknownError as exc:
            return ConnectionResult(
                success=False,
                message=str(exc),
                error_code=exc.code,
                host_key_result=exc.result,
            )
        except SSHAuthError as exc:
            return ConnectionResult(
                success=False, message=str(exc), error_code=exc.code
            )
        except SSHConnectionError as exc:
            return ConnectionResult(
                success=False, message=str(exc), error_code=exc.code
            )
        except asyncssh.DisconnectError as exc:
            msg = self._map_disconnect(exc)
            logger.error(sanitize_for_log("SSH desconectado", error=msg))
            return ConnectionResult(success=False, message=msg, error_code="disconnect")
        except asyncssh.PermissionDenied as exc:
            msg = "Credenciais inválidas ou permissão negada."
            logger.error(sanitize_for_log(msg, detail=str(exc)))
            return ConnectionResult(success=False, message=msg, error_code="auth_error")
        except (OSError, asyncio.TimeoutError, asyncssh.Error) as exc:
            msg = self._map_os_error(exc)
            logger.error(sanitize_for_log("Erro SSH", error=msg))
            return ConnectionResult(success=False, message=msg, error_code="network")

    async def _connect_profile(
        self,
        profile: ServerProfile,
        *,
        is_target: bool,
        tunnel: Optional[Any] = None,
    ) -> asyncssh.SSHClientConnection:
        # Jump host first (cada hop valida host key antes da auth)
        jump_tunnel = tunnel
        if profile.jump_host_id is not None and self.resolve_server:
            jump_profile = self.resolve_server(profile.jump_host_id)
            if jump_profile is None:
                raise SSHConnectionError(
                    f"Jump host id={profile.jump_host_id} não encontrado.",
                    code="jump_not_found",
                )
            if jump_profile.id == profile.id:
                raise SSHConnectionError(
                    "Loop de jump host detectado.", code="jump_loop"
                )
            jump_conn = await self._connect_profile(
                jump_profile, is_target=False, tunnel=tunnel
            )
            self._jump_connections.append(jump_conn)
            jump_tunnel = jump_conn

        # Fase 1: handshake + host key SEM credenciais (sem senha/chave/agente).
        verifier = _HostKeyVerifyingClient(
            self.host_keys,
            hostname=profile.host,
            port=profile.port,
            auto_accept_new=self.auto_accept_new_host_key,
        )
        await self._probe_host_key(profile, verifier, jump_tunnel)

        result = verifier.host_key_result
        if result is None:
            raise SSHConnectionError(
                "Não foi possível obter a host key do servidor.",
                code="host_key_error",
            )
        if result.decision == HostKeyDecision.CHANGED_BLOCK:
            raise HostKeyChangedError(result)
        if result.decision != HostKeyDecision.ACCEPT and result.is_new:
            raise HostKeyUnknownError(result)
        if result.decision != HostKeyDecision.ACCEPT:
            raise HostKeyUnknownError(result)

        # Fase 2: só agora resolve segredos e autentica
        password, passphrase = self._resolve_secrets(profile, is_target=is_target)
        connect_kwargs = await self._build_connect_kwargs(
            profile, password=password, passphrase=passphrase
        )
        auth_verifier = _HostKeyVerifyingClient(
            self.host_keys,
            hostname=profile.host,
            port=profile.port,
            auto_accept_new=False,
            session_trusted=True,  # já validada na fase 1
        )
        connect_kwargs["known_hosts"] = _EMPTY_KNOWN_HOSTS
        connect_kwargs["client_factory"] = lambda: auth_verifier

        try:
            conn = await self._raw_connect(profile, connect_kwargs, jump_tunnel)
        except asyncssh.PublicKeyLoadError as exc:
            raise SSHAuthError(
                "Chave privada inválida ou formato não suportado."
            ) from exc
        except asyncssh.KeyImportError as exc:
            raise SSHAuthError(
                "Não foi possível importar a chave privada. "
                "Verifique o arquivo e a passphrase."
            ) from exc
        except asyncssh.KeyEncryptionError as exc:
            raise SSHAuthError("Passphrase incorreta ou chave privada inválida.") from exc
        except asyncssh.PermissionDenied as exc:
            raise SSHAuthError("Credenciais inválidas.") from exc

        # Limpar referências locais a segredos assim que possível
        password = None
        passphrase = None
        return conn

    async def _probe_host_key(
        self,
        profile: ServerProfile,
        verifier: _HostKeyVerifyingClient,
        jump_tunnel: Optional[Any],
    ) -> None:
        """Handshake sem credenciais — valida host key antes de qualquer auth."""
        probe_kwargs: dict[str, Any] = {
            "username": profile.username or "probe",
            # NUNCA None (desliga verificação) e NUNCA b'' (cai no known_hosts do SO)
            "known_hosts": _EMPTY_KNOWN_HOSTS,
            "client_factory": lambda: verifier,
            "client_keys": None,
            "password": None,
            "agent_path": None,
            "login_timeout": profile.timeout,
            # Preferir algoritmos comuns; o callback decide confiança
            "server_host_key_algs": "default",
        }
        try:
            conn = await self._raw_connect(profile, probe_kwargs, jump_tunnel)
            # Conectou sem auth (servidor permissivo) — fechar; host key já validada
            await self._safe_close(conn)
        except HostKeyChangedError:
            raise
        except HostKeyUnknownError:
            raise
        except (
            asyncssh.PermissionDenied,
            asyncssh.DisconnectError,
            asyncssh.HostKeyNotVerifiable,
            asyncssh.KeyExchangeFailed,
            ValueError,
            asyncssh.Error,
        ) as exc:
            result = verifier.host_key_result
            if result is not None:
                if result.is_changed:
                    raise HostKeyChangedError(result) from exc
                if result.is_new and result.decision != HostKeyDecision.ACCEPT:
                    raise HostKeyUnknownError(result) from exc
                if result.decision == HostKeyDecision.ACCEPT:
                    # Host key OK; falha esperada de autenticação no probe
                    return
                raise HostKeyUnknownError(result) from exc

            # Sem resultado: o callback não rodou (não deve acontecer com
            # _EMPTY_KNOWN_HOSTS). Não tratar PermissionDenied como sucesso.
            msg = str(exc).lower()
            if "host key" in msg or "not trusted" in msg:
                raise SSHConnectionError(
                    f"Falha na verificação da host key: {exc}",
                    code="host_key_error",
                ) from exc
            raise SSHConnectionError(
                f"Não foi possível validar a host key do servidor: {exc}",
                code="host_key_error",
            ) from exc
        except (OSError, asyncio.TimeoutError) as exc:
            raise SSHConnectionError(self._map_os_error(exc), code="network") from exc

    async def _raw_connect(
        self,
        profile: ServerProfile,
        connect_kwargs: dict[str, Any],
        jump_tunnel: Optional[Any],
    ) -> asyncssh.SSHClientConnection:
        timeout = float(profile.timeout or 30)
        if jump_tunnel is not None:
            return await asyncio.wait_for(
                jump_tunnel.connect_ssh(
                    profile.host,
                    port=profile.port,
                    **{k: v for k, v in connect_kwargs.items() if k != "host"},
                ),
                timeout=timeout,
            )
        return await asyncio.wait_for(
            asyncssh.connect(
                profile.host,
                port=profile.port,
                **connect_kwargs,
            ),
            timeout=timeout,
        )

    def _resolve_secrets(
        self, profile: ServerProfile, *, is_target: bool
    ) -> tuple[Optional[str], Optional[str]]:
        password = None
        passphrase = None
        key = profile.credential_service_key()

        if profile.auth_method == AuthMethod.PASSWORD:
            if is_target and self.password:
                password = self.password
            else:
                password = self.credentials.get_server_password(key)
        elif profile.auth_method == AuthMethod.KEY_PASSPHRASE:
            if is_target and self.passphrase:
                passphrase = self.passphrase
            else:
                passphrase = self.credentials.get_passphrase(key)
        return password, passphrase

    async def _build_connect_kwargs(
        self,
        profile: ServerProfile,
        *,
        password: Optional[str],
        passphrase: Optional[str],
    ) -> dict[str, Any]:
        """Monta kwargs de autenticação — só chamado APÓS host key aceita."""
        kwargs: dict[str, Any] = {
            "username": profile.username,
            "login_timeout": profile.timeout,
        }
        if profile.keepalive > 0:
            kwargs["keepalive_interval"] = profile.keepalive
            kwargs["keepalive_count_max"] = 3

        if profile.auth_method == AuthMethod.PASSWORD:
            if not password:
                raise SSHAuthError(
                    "Senha não fornecida. Informe a senha ou habilite 'Lembrar'."
                )
            kwargs["password"] = password
            kwargs["client_keys"] = None
            kwargs["agent_path"] = None
        elif profile.auth_method in (AuthMethod.KEY, AuthMethod.KEY_PASSPHRASE):
            key_path = Path(profile.private_key_path).expanduser()
            if not key_path.is_file():
                raise SSHAuthError(f"Chave privada não encontrada: {key_path}")
            # Passar path + passphrase: AsyncSSH carrega na fase de opções
            # imediatamente antes do connect autenticado (já pós host key).
            kwargs["client_keys"] = [str(key_path)]
            if passphrase:
                kwargs["passphrase"] = passphrase
            kwargs["password"] = None
            kwargs["agent_path"] = None
        elif profile.auth_method == AuthMethod.AGENT:
            kwargs["client_keys"] = None
            kwargs["agent_path"] = ()  # agente padrão
            kwargs["password"] = None
        return kwargs

    async def disconnect(self) -> None:
        if self.connection is not None:
            await self._safe_close(self.connection)
            self.connection = None
        for jc in reversed(self._jump_connections):
            await self._safe_close(jc)
        self._jump_connections.clear()
        logger.info(
            sanitize_for_log(
                "SSH desconectado",
                host=self.profile.host,
                user=self.profile.username,
            )
        )

    @staticmethod
    async def _safe_close(conn: asyncssh.SSHClientConnection) -> None:
        try:
            conn.close()
            await conn.wait_closed()
        except Exception:  # noqa: BLE001
            pass

    async def open_session(self, **kwargs: Any) -> asyncssh.SSHClientSession:
        if not self.is_connected:
            raise SSHConnectionError("Não conectado.", code="not_connected")
        return await self.connection.create_session(
            asyncssh.SSHClientSession, **kwargs
        )  # type: ignore[union-attr]

    async def open_sftp(self) -> asyncssh.SFTPClient:
        if not self.is_connected:
            raise SSHConnectionError("Não conectado.", code="not_connected")
        return await self.connection.start_sftp_client()  # type: ignore[union-attr]

    async def run_command(self, command: str, timeout: float = 30.0) -> tuple[int, str, str]:
        """Executa comando remoto (lista segura — sem shell no cliente)."""
        if not self.is_connected:
            raise SSHConnectionError("Não conectado.", code="not_connected")
        try:
            result = await asyncio.wait_for(
                self.connection.run(command, check=False),  # type: ignore[union-attr]
                timeout=timeout,
            )
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            return int(result.exit_status or 0), str(stdout), str(stderr)
        except asyncio.TimeoutError as exc:
            raise SSHConnectionError("Timeout ao executar comando.", code="timeout") from exc

    def get_jump_route(self) -> list[str]:
        """Rota visual de jump hosts até o destino."""
        route: list[str] = []
        if not self.resolve_server:
            return [self.profile.display_host()]
        current: Optional[ServerProfile] = self.profile
        chain: list[ServerProfile] = []
        seen: set[int] = set()
        while current is not None:
            if current.id is not None:
                if current.id in seen:
                    break
                seen.add(current.id)
            chain.append(current)
            if current.jump_host_id and self.resolve_server:
                current = self.resolve_server(current.jump_host_id)
            else:
                break
        for s in reversed(chain):
            route.append(f"{s.username}@{s.display_host()}")
        return route

    @staticmethod
    def _map_disconnect(exc: asyncssh.DisconnectError) -> str:
        reason = str(exc)
        lower = reason.lower()
        if "auth" in lower or "permission" in lower:
            return "Credenciais inválidas."
        if "host key" in lower:
            return "Falha na verificação da host key."
        return f"Desconectado pelo servidor: {reason}"

    @staticmethod
    def _map_os_error(exc: BaseException) -> str:
        msg = str(exc).lower()
        if isinstance(exc, asyncio.TimeoutError) or "timeout" in msg or "timed out" in msg:
            return "Timeout ao conectar ao servidor."
        if "name or service not known" in msg or "nodename nor servname" in msg or "getaddrinfo" in msg:
            return "Host não encontrado (falha na resolução DNS)."
        if "connection refused" in msg or "errno 111" in msg:
            return "Conexão recusada (porta SSH fechada ou firewall)."
        if "network is unreachable" in msg:
            return "Rede inacessível."
        if "no route to host" in msg:
            return "Sem rota para o host."
        return f"Erro de conexão: {exc}"


async def test_connection(
    profile: ServerProfile,
    credentials: CredentialStore,
    host_keys: HostKeyManager,
    *,
    password: Optional[str] = None,
    passphrase: Optional[str] = None,
    resolve_server: Optional[Callable[[int], Optional[ServerProfile]]] = None,
    auto_accept_new_host_key: bool = False,
    on_host_key_prompt: Optional[Callable[[HostKeyResult], bool]] = None,
) -> ConnectionResult:
    """Testa conexão SSH e desconecta.

    on_host_key_prompt é legado: se fornecido e a key for nova, o caller
    deve aceitar a key e chamar test_connection de novo. Não é invocado
    dentro da corrotina de conexão (evita reentrância com Qt).
    """
    del on_host_key_prompt  # não usar dentro do connect
    client = SSHClient(
        profile=profile,
        credentials=credentials,
        host_keys=host_keys,
        password=password,
        passphrase=passphrase,
        resolve_server=resolve_server,
        auto_accept_new_host_key=auto_accept_new_host_key,
    )
    result = await client.connect()
    if result.success:
        await client.disconnect()
    return result
