"""Lança RDP/VNC/RustDesk/custom de forma segura (sem shell=True)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from app.models.remote import RemoteProfile, RemoteProtocol, RemoteSessionStatus
from app.models.server import ServerProfile
from app.utils.process import (
    ProcessError,
    build_safe_preview,
    find_executable,
    validate_executable,
)
from app.utils.sanitize import sanitize_for_log

logger = logging.getLogger(__name__)

GetPassword = Callable[[RemoteProfile], Optional[str]]


@dataclass
class RemoteSession:
    profile: RemoteProfile
    server: ServerProfile
    process: Optional[subprocess.Popen[bytes]] = None
    status: RemoteSessionStatus = RemoteSessionStatus.IDLE
    error_message: str = ""
    local_tunnel_port: Optional[int] = None
    tunnel_stop: Optional[Callable[[], Any]] = None
    temp_files: list[Path] = field(default_factory=list)

    def is_running(self) -> bool:
        if self.process is None:
            return False
        return self.process.poll() is None


class RemoteDesktopLauncher:
    """Constrói argumentos seguros e lança clientes externos."""

    RDP_CANDIDATES = ("xfreerdp3", "xfreerdp", "wlfreerdp", "wlfreerdp3")
    VNC_CANDIDATES = ("vncviewer", "xtigervncviewer", "tigervncviewer")
    RUSTDESK_CANDIDATES = ("rustdesk",)

    def __init__(
        self,
        get_password: Optional[GetPassword] = None,
        rdp_client: str = "auto",
        vnc_client: str = "auto",
        rustdesk_client: str = "auto",
    ) -> None:
        self.get_password = get_password
        self.rdp_client = rdp_client
        self.vnc_client = vnc_client
        self.rustdesk_client = rustdesk_client
        self._sessions: dict[int, RemoteSession] = {}

    def detect_rdp(self) -> Optional[str]:
        if self.rdp_client and self.rdp_client != "auto":
            return find_executable([self.rdp_client])
        found = find_executable(self.RDP_CANDIDATES)
        if found:
            return found
        try:
            from app.remote_desktop.bundle import resolve_xfreerdp

            return resolve_xfreerdp()
        except Exception:  # noqa: BLE001
            return None

    def detect_vnc(self) -> Optional[str]:
        if self.vnc_client and self.vnc_client != "auto":
            return find_executable([self.vnc_client])
        return find_executable(self.VNC_CANDIDATES)

    def detect_rustdesk(self) -> Optional[str]:
        if self.rustdesk_client and self.rustdesk_client != "auto":
            return find_executable([self.rustdesk_client])
        return find_executable(self.RUSTDESK_CANDIDATES)

    def is_freerdp3(self, exe: str) -> bool:
        name = Path(exe).name
        return "3" in name or "freerdp3" in exe

    def resolve_host_port(
        self,
        profile: RemoteProfile,
        server: ServerProfile,
        *,
        tunnel_local_port: Optional[int] = None,
    ) -> tuple[str, int]:
        if tunnel_local_port:
            return "127.0.0.1", tunnel_local_port
        if profile.use_ssh_host:
            return server.host, profile.port or profile.default_port_for_protocol()
        return (
            profile.host or server.host,
            profile.port or profile.default_port_for_protocol(),
        )

    def build_args(
        self,
        profile: RemoteProfile,
        server: ServerProfile,
        *,
        password: Optional[str] = None,
        tunnel_local_port: Optional[int] = None,
        parent_window: Optional[int] = None,
        freerdp_exe: Optional[str] = None,
    ) -> tuple[list[str], list[Path]]:
        temp_files: list[Path] = []
        host, port = self.resolve_host_port(
            profile, server, tunnel_local_port=tunnel_local_port
        )

        if profile.protocol == RemoteProtocol.RDP:
            return self._build_rdp(
                profile,
                server,
                host,
                port,
                password=password,
                temp_files=temp_files,
                parent_window=parent_window,
                freerdp_exe=freerdp_exe,
            )

        if profile.protocol == RemoteProtocol.VNC:
            return self._build_vnc(
                profile, host, port, password=password, temp_files=temp_files
            )

        if profile.protocol == RemoteProtocol.RUSTDESK:
            return self._build_rustdesk(profile, password=password)

        if profile.protocol == RemoteProtocol.CUSTOM:
            return self._build_custom(profile, server, host, port)

        raise ProcessError(f"Protocolo não suportado: {profile.protocol}")

    def _build_rdp(
        self,
        profile: RemoteProfile,
        server: ServerProfile,
        host: str,
        port: int,
        *,
        password: Optional[str],
        temp_files: list[Path],
        parent_window: Optional[int] = None,
        freerdp_exe: Optional[str] = None,
    ) -> tuple[list[str], list[Path]]:
        exe = freerdp_exe or self.detect_rdp()
        if not exe:
            # tenta bundle embutido
            try:
                from app.remote_desktop.bundle import resolve_xfreerdp

                exe = resolve_xfreerdp()
            except Exception:  # noqa: BLE001
                exe = None
        if not exe:
            raise ProcessError(
                "FreeRDP não encontrado.\n"
                "O app tenta baixar automaticamente; se falhar:\n"
                "  sudo apt install freerdp2-x11"
            )

        v3 = self.is_freerdp3(exe)
        args = [exe, f"/v:{host}:{port}"]
        user = (profile.username or server.username or "").strip()
        if user:
            if profile.domain:
                args.append(f"/u:{profile.domain}\\{user}")
            else:
                args.append(f"/u:{user}")
        # Senha via stdin (/from-stdin) — NUNCA em argv (/proc)
        stdin_password: Optional[str] = None
        if password:
            args.append("/from-stdin")
            stdin_password = password
            # marca para launch() usar stdin
            temp_files.append(Path("__stdin_password__"))

        # Resolução + escala (corrige menus minúsculos no xrdp)
        scale = _parse_scale(profile)
        resolution = profile.resolution if profile.resolution not in ("", "auto") else ""
        if not resolution:
            try:
                from app.remote_desktop.setup import suggest_rdp_geometry

                resolution, suggested_scale = suggest_rdp_geometry()
                if scale == 100 and profile.auto_scale:
                    scale = suggested_scale
            except Exception:  # noqa: BLE001
                resolution = "1600x900"
                if scale == 100:
                    scale = 140

        if parent_window:
            args.append(f"/parent-window:{int(parent_window)}")
        if profile.fullscreen and not parent_window:
            args.append("/f")
        else:
            args.append(f"/size:{resolution}")

        # Escala FreeRDP: 100 | 140 | 180 (menus legíveis no xrdp)
        if scale in (100, 140, 180):
            args.append(f"/scale:{scale}")
            # scale-desktop em alguns builds com xrdp causa crash — só se 140+
            if scale >= 140:
                args.append(f"/scale-desktop:{min(scale, 180)}")
        if not parent_window:
            args.append("/smart-sizing")
        # título da janela
        args.append(f"/t:RDP — {server.name or server.host}")

        # clipboard
        if profile.clipboard:
            args.append("+clipboard")
        else:
            args.append("-clipboard")

        # cert: freerdp2 usa /cert-ignore ; freerdp3 /cert:ignore
        if v3:
            args.append("/cert:ignore")
        else:
            args.append("/cert-ignore")

        # reconexão e qualidade boas p/ xrdp
        if profile.auto_reconnect:
            if v3:
                args.append("+auto-reconnect")
        args.append("/network:auto")
        # cores e qualidade legíveis
        args.append("/bpp:24")
        if profile.audio:
            args.append("/audio-mode:0")
        else:
            args.append("/audio-mode:1")

        if profile.share_folder:
            folder = str(Path(profile.share_folder).expanduser())
            args.append(f"/drive:share,{folder}")

        # xrdp: RFX costuma ir bem; GFX às vezes deixa UI estranha
        if not v3:
            args.append("/gfx:off")
            args.append("/rfx")
        else:
            # freerdp3: preferir modo compatível com xrdp
            args.append("/gfx:AVC420")

        return args, temp_files

    def _build_vnc(
        self,
        profile: RemoteProfile,
        host: str,
        port: int,
        *,
        password: Optional[str],
        temp_files: list[Path],
    ) -> tuple[list[str], list[Path]]:
        exe = self.detect_vnc()
        if not exe:
            raise ProcessError(
                "TigerVNC Viewer não encontrado.\n\n"
                "Instale: sudo apt install tigervnc-viewer"
            )
        if port >= 5900 and port < 6000:
            target = f"{host}:{port - 5900}"
        else:
            target = f"{host}::{port}"
        args = [exe, target]
        if profile.view_only:
            args.append("-ViewOnly")
        if profile.fullscreen:
            args.append("-Fullscreen")
        if password:
            from app.utils.vnc_passwd import write_vnc_passwd_file

            passwd_file = write_vnc_passwd_file(password)
            temp_files.append(passwd_file)
            args.extend(["-passwd", str(passwd_file)])
        return args, temp_files

    def _build_rustdesk(
        self, profile: RemoteProfile, *, password: Optional[str]
    ) -> tuple[list[str], list[Path]]:
        exe = self.detect_rustdesk()
        if not exe:
            raise ProcessError("RustDesk não encontrado. Instale o cliente RustDesk.")
        rid = profile.rustdesk_id.strip()
        if not rid:
            raise ProcessError("ID do RustDesk não configurado.")
        args = [exe, "--connect", rid]
        # NÃO usar --password: expõe a senha em /proc/<pid>/cmdline.
        # O cliente deve solicitar a senha na UI do RustDesk.
        if password:
            logger.warning(
                sanitize_for_log(
                    "RustDesk: senha não enviada por linha de comando "
                    "(risco de exposição em /proc). O cliente pedirá a senha."
                )
            )
        return args, []

    def _build_custom(
        self,
        profile: RemoteProfile,
        server: ServerProfile,
        host: str,
        port: int,
    ) -> tuple[list[str], list[Path]]:
        exe = profile.custom_executable.strip()
        if not exe:
            raise ProcessError("Executável personalizado não configurado.")
        validated = validate_executable(exe)
        raw_args: list[str] = []
        if profile.custom_args.strip():
            try:
                parsed = json.loads(profile.custom_args)
                if not isinstance(parsed, list):
                    raise ValueError("custom_args deve ser lista JSON")
                raw_args = [str(a) for a in parsed]
            except (json.JSONDecodeError, ValueError) as exc:
                raise ProcessError(
                    "Argumentos personalizados inválidos (use lista JSON de strings)."
                ) from exc
        replacements = {
            "{host}": host,
            "{port}": str(port),
            "{user}": profile.username or server.username,
            "{ssh_host}": server.host,
            "{ssh_port}": str(server.port),
        }
        final_args = [str(validated)]
        for a in raw_args:
            for k, v in replacements.items():
                a = a.replace(k, v)
            final_args.append(a)
        return final_args, []

    def preview_args(
        self,
        profile: RemoteProfile,
        server: ServerProfile,
        *,
        tunnel_local_port: Optional[int] = None,
    ) -> str:
        try:
            args, _ = self.build_args(
                profile, server, password=None, tunnel_local_port=tunnel_local_port
            )
            return build_safe_preview(args)
        except ProcessError as exc:
            return f"(erro: {exc})"

    def launch(
        self,
        profile: RemoteProfile,
        server: ServerProfile,
        *,
        password: Optional[str] = None,
        tunnel_local_port: Optional[int] = None,
        tunnel_stop: Optional[Callable[[], Any]] = None,
        parent_window: Optional[int] = None,
        freerdp_exe: Optional[str] = None,
        freerdp_env: Optional[dict[str, str]] = None,
        stderr_path: Optional[Path] = None,
    ) -> RemoteSession:
        if password is None and self.get_password:
            password = self.get_password(profile)

        args, temp_files = self.build_args(
            profile,
            server,
            password=password,
            tunnel_local_port=tunnel_local_port,
            parent_window=parent_window,
            freerdp_exe=freerdp_exe,
        )
        # Extrair marcador de stdin (FreeRDP)
        use_stdin_password = False
        real_temps: list[Path] = []
        for t in temp_files:
            if str(t) == "__stdin_password__":
                use_stdin_password = True
            else:
                real_temps.append(t)
        temp_files = real_temps

        logger.info(
            sanitize_for_log(
                "Iniciando sessão remota",
                protocol=profile.protocol.value
                if hasattr(profile.protocol, "value")
                else str(profile.protocol),
                preview=build_safe_preview(args),
            )
        )
        session = RemoteSession(
            profile=profile,
            server=server,
            status=RemoteSessionStatus.STARTING,
            local_tunnel_port=tunnel_local_port,
            tunnel_stop=tunnel_stop,
            temp_files=temp_files,
        )
        try:
            import subprocess as sp

            err_fh = None
            if stderr_path is not None:
                err_fh = open(stderr_path, "w", encoding="utf-8")  # noqa: SIM115
            stdin_arg = sp.PIPE if use_stdin_password and password else sp.DEVNULL
            proc = sp.Popen(
                args,
                env=freerdp_env,
                shell=False,
                stdin=stdin_arg,
                stdout=sp.DEVNULL,
                stderr=err_fh if err_fh is not None else sp.PIPE,
                start_new_session=True,
            )
            if use_stdin_password and password and proc.stdin is not None:
                try:
                    proc.stdin.write((password + "\n").encode("utf-8"))
                    proc.stdin.flush()
                except BrokenPipeError:
                    pass
                finally:
                    try:
                        proc.stdin.close()
                    except OSError:
                        pass
            # limpar senha da memória local
            password = None
            session.process = proc
            session.status = RemoteSessionStatus.RUNNING
            if server.id is not None:
                self._sessions[server.id] = session
            return session
        except ProcessError as exc:
            session.status = RemoteSessionStatus.ERROR
            session.error_message = str(exc)
            self._cleanup_temps(temp_files)
            raise
        except OSError as exc:
            session.status = RemoteSessionStatus.ERROR
            session.error_message = str(exc)
            self._cleanup_temps(temp_files)
            raise ProcessError(str(exc)) from exc

    def stop(self, server_id: int) -> None:
        session = self._sessions.pop(server_id, None)
        if not session:
            return
        if session.process and session.process.poll() is None:
            try:
                session.process.terminate()
                try:
                    session.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    session.process.kill()
            except OSError:
                pass
        if session.tunnel_stop:
            try:
                session.tunnel_stop()
            except Exception:  # noqa: BLE001
                pass
        self._cleanup_temps(session.temp_files)
        session.status = RemoteSessionStatus.STOPPED

    def stop_all(self) -> None:
        for sid in list(self._sessions.keys()):
            self.stop(sid)

    def get_session(self, server_id: int) -> Optional[RemoteSession]:
        session = self._sessions.get(server_id)
        if session and session.process and session.process.poll() is not None:
            session.status = RemoteSessionStatus.STOPPED
            self._cleanup_temps(session.temp_files)
        return session

    def poll_sessions(self) -> None:
        for sid in list(self._sessions.keys()):
            session = self._sessions[sid]
            if session.process and session.process.poll() is not None:
                if session.tunnel_stop:
                    try:
                        session.tunnel_stop()
                    except Exception:  # noqa: BLE001
                        pass
                self._cleanup_temps(session.temp_files)
                session.status = RemoteSessionStatus.STOPPED
                del self._sessions[sid]

    @staticmethod
    def _cleanup_temps(files: list[Path]) -> None:
        for f in files:
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _write_vnc_passwd(password: str) -> Path:
        from app.utils.vnc_passwd import write_vnc_passwd_file

        return write_vnc_passwd_file(password)


def _parse_scale(profile: RemoteProfile) -> int:
    """Extrai escala 100/140/180 de quality ou auto_scale."""
    q = (profile.quality or "").strip().lower()
    if q in ("100", "140", "180", "200"):
        val = int(q)
        return 180 if val == 200 else val
    if q in ("high", "alto"):
        return 180
    if q in ("medium", "medio", "médio"):
        return 140
    if q in ("low", "baixo"):
        return 100
    if profile.auto_scale:
        return 140  # padrão legível para xrdp
    return 100
