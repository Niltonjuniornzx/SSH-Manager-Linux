"""Painel de terminal SSH com emulador PTY embutido (estilo terminal real)."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from app.ui.panels.terminal_widget import TerminalWidget
from app.utils.process import ProcessError, find_executable, start_process
from app.utils.sanitize import sanitize_for_log

if TYPE_CHECKING:
    from app.models.server import ServerProfile
    from app.ssh.client import SSHClient

logger = logging.getLogger(__name__)


class TerminalPanel(QWidget):
    """
    Terminal SSH interativo:
    - Digite direto no terminal (sem campo de comando separado)
    - PTY com cores ANSI, redimensionamento, Ctrl+C/Z
    - Botão opcional para terminal externo (Konsole/GNOME/xterm)
    """

    connection_lost = Signal()

    def __init__(
        self,
        profile: "ServerProfile",
        client: Optional["SSHClient"] = None,
        *,
        external_terminal: str = "auto",
        font_family: str = "Monospace",
        font_size: int = 12,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.profile = profile
        self.client = client
        self.external_terminal = external_terminal
        self._font_family = font_family
        self._font_size = font_size
        self._process = None
        self._reader_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._opening = False
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        # Quase sem margem — terminal ocupa a aba inteira
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Labels só para estado interno / tooltip (não ocupam barra)
        self.status_lbl = QLabel("Desconectado")
        self.status_lbl.setVisible(False)
        self.size_lbl = QLabel("")
        self.size_lbl.setVisible(False)

        self.term = TerminalWidget(
            cols=80,
            rows=24,
            font_family=self._font_family,
            font_size=self._font_size,
        )
        self.term.set_encoding(self.profile.terminal_encoding or "utf-8")
        self.term.data_out.connect(self._on_user_input)
        self.term.resized.connect(self._on_term_resized)
        self.term.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.term.customContextMenuRequested.connect(self._term_context_menu)
        self.term.setToolTip("Botão direito: reconectar · terminal externo")
        layout.addWidget(self.term, 1)

    def _term_context_menu(self, pos) -> None:
        menu = QMenu(self)
        st = self.status_lbl.text() or ""
        sz = self.size_lbl.text() or ""
        if st or sz:
            info = menu.addAction(f"{st}" + (f"  ·  {sz}" if sz else ""))
            info.setEnabled(False)
            menu.addSeparator()
        menu.addAction("Reconectar shell", self._start_shell)
        menu.addAction("Abrir terminal externo…", self.open_external)
        menu.exec(self.term.mapToGlobal(pos))

    # ── Conexão ─────────────────────────────────────────────

    def set_client(self, client: Optional["SSHClient"]) -> None:
        self.client = client
        if client and client.is_connected:
            self.status_lbl.setText("Conectado")
            self.status_lbl.setObjectName("statusConnected")
            self.status_lbl.style().unpolish(self.status_lbl)
            self.status_lbl.style().polish(self.status_lbl)
            self._start_shell()
        else:
            self.status_lbl.setText("Desconectado")
            self.status_lbl.setObjectName("statusDisconnected")
            self.term.set_connected(False)
            self._close_shell()

    def _start_shell(self) -> None:
        if not self.client or not self.client.is_connected:
            self.term.feed("\r\n\x1b[31mNão conectado. Conecte-se ao servidor primeiro.\x1b[0m\r\n")
            return
        if self._opening:
            return
        from app.workers.async_bridge import schedule

        schedule(self._open_shell(), name="term-shell")

    async def _open_shell(self) -> None:
        if self._opening:
            return
        self._opening = True
        try:
            await self._close_shell_async()
            conn = self.client.connection  # type: ignore[union-attr]
            if conn is None:
                return

            cols, rows = self.term.term_size()
            # Shell de login interativo com PTY real
            process = await conn.create_process(
                term_type="xterm-256color",
                term_size=(cols, rows),
                encoding=None,  # bytes — decodificamos nós
            )
            self._process = process
            self.term.reset()
            self.term.set_connected(True)
            self.term.setFocus()
            self.status_lbl.setText("Shell ativo")
            self.status_lbl.setObjectName("statusConnected")
            self.status_lbl.style().unpolish(self.status_lbl)
            self.status_lbl.style().polish(self.status_lbl)
            self.size_lbl.setText(f"{cols}×{rows}")

            banner = (
                f"\x1b[1;32m{self.profile.username}@{self.profile.display_host()}\x1b[0m "
                f"— terminal interativo ({cols}×{rows})\r\n"
            )
            self.term.feed(banner)

            self._reader_task = asyncio.create_task(
                self._read_stream(process.stdout), name="term-stdout"
            )
            # stderr do create_process às vezes é o mesmo canal no PTY
            if getattr(process, "stderr", None) is not None and process.stderr is not process.stdout:
                self._stderr_task = asyncio.create_task(
                    self._read_stream(process.stderr), name="term-stderr"
                )

            logger.info(
                sanitize_for_log(
                    "Shell PTY iniciado",
                    host=self.profile.host,
                    size=f"{cols}x{rows}",
                )
            )
        except Exception as exc:  # noqa: BLE001
            self.term.feed(f"\r\n\x1b[31mFalha ao abrir shell: {exc}\x1b[0m\r\n")
            self.term.set_connected(False)
            self.status_lbl.setText("Erro no shell")
            logger.error(sanitize_for_log("Falha shell PTY", error=str(exc)))
        finally:
            self._opening = False

    async def _read_stream(self, stream) -> None:
        enc = self.profile.terminal_encoding or "utf-8"
        try:
            while True:
                data = await stream.read(8192)
                if not data:
                    break
                if isinstance(data, str):
                    text = data
                else:
                    text = data.decode(enc, errors="replace")
                self.term.feed(text)
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001
            logger.debug("terminal read ended: %s", exc)
        self.term.set_connected(False)
        self.term.feed("\r\n\x1b[33m[shell encerrado]\x1b[0m\r\n")
        self.status_lbl.setText("Shell encerrado")
        self.connection_lost.emit()

    def _on_user_input(self, text: str) -> None:
        """Teclas digitadas no widget → stdin do PTY."""
        process = self._process
        if process is None:
            return
        try:
            stdin = process.stdin
            if stdin is None:
                return
            # AsyncSSH: write str ou bytes
            data = text.encode(self.profile.terminal_encoding or "utf-8", errors="replace")
            # write pode ser sync no canal
            result = stdin.write(data)
            if asyncio.iscoroutine(result):
                from app.workers.async_bridge import schedule

                schedule(result, name="term-write")
        except Exception as exc:  # noqa: BLE001
            self.term.feed(f"\r\n\x1b[31m[erro ao enviar: {exc}]\x1b[0m\r\n")

    def _on_term_resized(self, cols: int, rows: int) -> None:
        self.size_lbl.setText(f"{cols}×{rows}")
        process = self._process
        if process is None:
            return
        from app.workers.async_bridge import schedule

        async def _resize() -> None:
            try:
                # SSHClientProcess.change_terminal_size(width, height)
                if hasattr(process, "change_terminal_size"):
                    process.change_terminal_size(cols, rows)
                elif hasattr(process, "terminal_size"):
                    process.terminal_size = (cols, rows)
            except Exception as exc:  # noqa: BLE001
                logger.debug("resize PTY: %s", exc)

        schedule(_resize(), name="term-resize")

    def _close_shell(self) -> None:
        from app.workers.async_bridge import schedule

        schedule(self._close_shell_async(), name="term-close")

    async def _close_shell_async(self) -> None:
        for task in (self._reader_task, self._stderr_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
        self._reader_task = None
        self._stderr_task = None
        if self._process is not None:
            try:
                self._process.close()
                if hasattr(self._process, "wait"):
                    try:
                        await asyncio.wait_for(self._process.wait(), timeout=1.0)
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001
                pass
            self._process = None

    def cleanup(self) -> None:
        self.term.set_connected(False)
        self._close_shell()

    # ── Terminal externo ────────────────────────────────────

    def open_external(self) -> None:
        try:
            args = self._build_external_ssh_args()
            start_process(args)
            self.term.feed(
                f"\r\n\x1b[36m[terminal externo: {args[0]}]\x1b[0m\r\n"
            )
            logger.info(
                sanitize_for_log(
                    "Terminal externo aberto",
                    host=self.profile.host,
                    term=args[0],
                )
            )
        except ProcessError as exc:
            QMessageBox.warning(self, "Terminal externo", str(exc))

    def _build_external_ssh_args(self) -> list[str]:
        term = self._detect_terminal()
        ssh = find_executable(["ssh"])
        if not ssh:
            raise ProcessError("Cliente openssh (ssh) não encontrado.")

        from app.utils.enums import enum_value

        ssh_args = [
            ssh,
            "-p",
            str(self.profile.port),
            "-o",
            "StrictHostKeyChecking=ask",
            "-o",
            "UpdateHostKeys=yes",
        ]
        auth = enum_value(self.profile.auth_method)
        if auth in ("key", "key_passphrase") and self.profile.private_key_path:
            ssh_args.extend(["-i", os.path.expanduser(self.profile.private_key_path)])
        ssh_args.append(f"{self.profile.username}@{self.profile.host}")

        name = os.path.basename(term)
        if name == "konsole":
            return [term, "-e", *ssh_args]
        if name == "gnome-terminal":
            return [term, "--", *ssh_args]
        if name in ("xterm", "uxterm"):
            return [term, "-e", *ssh_args]
        if name == "xfce4-terminal":
            # -x passa args separados (sem shell)
            return [term, "-x", *ssh_args]
        return [term, "-e", *ssh_args]

    def _detect_terminal(self) -> str:
        if self.external_terminal and self.external_terminal != "auto":
            path = find_executable([self.external_terminal])
            if path:
                return path
        for candidate in ("konsole", "gnome-terminal", "xfce4-terminal", "xterm", "uxterm"):
            path = find_executable([candidate])
            if path:
                return path
        raise ProcessError(
            "Nenhum terminal externo encontrado (konsole, gnome-terminal, xterm)."
        )
