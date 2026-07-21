"""Controle remoto RDP — campos usuário/senha/porta e conexão estável (janela FreeRDP)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.models.remote import RemoteProfile, RemoteProtocol
from app.models.tunnel import TunnelProfile, TunnelType
from app.remote_desktop import bundle as frdp_bundle
from app.remote_desktop.launcher import RemoteDesktopLauncher
from app.remote_desktop.setup import (
    check_remote_rdp,
    fix_xfce_dpi,
    install_xrdp_desktop,
    start_xrdp_service,
    suggest_rdp_geometry,
)
from app.ui.widgets import PasswordLineEdit
from app.utils.paths import app_cache_dir, ensure_secure_dir
from app.utils.process import ProcessError

if TYPE_CHECKING:
    from app.database.db import Database
    from app.models.server import ServerProfile
    from app.security.credentials import CredentialStore
    from app.ssh.session_manager import SessionManager
    from app.tunnels.manager import TunnelManager


class RemotePanel(QWidget):
    def __init__(
        self,
        profile: "ServerProfile",
        db: "Database",
        credentials: "CredentialStore",
        launcher: RemoteDesktopLauncher,
        tunnel_manager: "TunnelManager",
        session_manager: "SessionManager",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.profile = profile
        self.db = db
        self.credentials = credentials
        self.launcher = launcher
        self.tunnel_manager = tunnel_manager
        self.session_manager = session_manager
        self.remote = self._load_or_default()
        self._tunnel_id: Optional[int] = None
        self._log_file: Optional[Path] = None
        self._build_ui()
        self._load_form()
        QTimer.singleShot(100, self._bootstrap_freerdp)

        self._poll = QTimer(self)
        self._poll.timeout.connect(self._poll_session)
        self._poll.start(1000)

    def _load_or_default(self) -> RemoteProfile:
        if self.profile.id:
            existing = self.db.get_remote_profile(self.profile.id)
            if existing:
                return existing
        res, scale = suggest_rdp_geometry()
        return RemoteProfile(
            server_id=self.profile.id,
            enabled=True,
            protocol=RemoteProtocol.RDP,
            use_ssh_host=True,
            port=3389,
            username=self.profile.username or "root",
            protect_with_tunnel=True,
            resolution=res,
            quality=str(scale),
            auto_scale=True,
            clipboard=True,
            audio=False,
        )

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Status
        self.lbl_status = QLabel("Preparando…")
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        # Formulário limpo e legível
        box = QGroupBox("Conexão RDP")
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.host_lbl = QLabel(self.profile.host)
        self.host_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("usuário do xrdp (ex.: root)")
        self.user_edit.setMinimumHeight(32)

        self.password = PasswordLineEdit()
        self.password.edit.setPlaceholderText("senha do desktop / Linux")
        self.password.edit.setMinimumHeight(32)
        self.password.setMinimumHeight(36)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(3389)
        self.port_spin.setMinimumHeight(32)
        self.port_spin.setMinimumWidth(100)

        self.scale = QComboBox()
        self.scale.setMinimumHeight(32)
        for val, label in (
            ("140", "140% — recomendado"),
            ("180", "180% — maior"),
            ("100", "100% — original"),
        ):
            self.scale.addItem(label, val)

        self.resolution = QComboBox()
        self.resolution.setEditable(True)
        self.resolution.setMinimumHeight(32)
        sug, _ = suggest_rdp_geometry()
        self.resolution.addItems(
            [sug, "1920x1080", "1600x900", "1366x768", "1280x800"]
        )

        self.chk_tunnel = QCheckBox("Usar túnel SSH (recomendado)")
        self.chk_tunnel.setChecked(True)
        self.chk_fullscreen = QCheckBox("Tela cheia")

        form.addRow("Servidor", self.host_lbl)
        form.addRow("Usuário RDP", self.user_edit)
        form.addRow("Senha", self.password)
        form.addRow("Porta RDP", self.port_spin)
        form.addRow("Resolução", self.resolution)
        form.addRow("Escala", self.scale)
        form.addRow("", self.chk_tunnel)
        form.addRow("", self.chk_fullscreen)
        layout.addWidget(box)

        # Botões
        row = QHBoxLayout()
        self.btn_connect = QPushButton("Conectar RDP")
        self.btn_connect.setObjectName("primaryBtn")
        self.btn_connect.setMinimumHeight(36)
        self.btn_disconnect = QPushButton("Desconectar")
        self.btn_disconnect.setObjectName("dangerBtn")
        self.btn_disconnect.setMinimumHeight(36)
        self.btn_fix = QPushButton("Menus maiores na VPS")
        self.btn_prepare = QPushButton("Instalar xrdp na VPS")
        row.addWidget(self.btn_connect)
        row.addWidget(self.btn_disconnect)
        row.addStretch()
        row.addWidget(self.btn_fix)
        row.addWidget(self.btn_prepare)
        layout.addLayout(row)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(160)
        self.log.setPlaceholderText("Log da conexão RDP…")
        layout.addWidget(self.log, 1)

        tip = QLabel(
            "A janela do FreeRDP abre por fora (mais estável com xrdp). "
            "Use a mesma senha do Linux. Escala 140%/180% ajuda se os menus ficarem pequenos."
        )
        tip.setObjectName("mutedLabel")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        self.btn_connect.clicked.connect(self._connect)
        self.btn_disconnect.clicked.connect(self._disconnect)
        self.btn_fix.clicked.connect(self._fix_dpi)
        self.btn_prepare.clicked.connect(self._prepare_vps)

    def _log(self, msg: str) -> None:
        self.log.append(msg)

    def _set_status(self, text: str, *, ok: bool | None = None) -> None:
        self.lbl_status.setText(text)
        if ok is True:
            self.lbl_status.setStyleSheet("color: #3ecf8e; font-weight: 600;")
        elif ok is False:
            self.lbl_status.setStyleSheet("color: #ff6b6b; font-weight: 600;")
        else:
            self.lbl_status.setStyleSheet("color: #e4e6eb;")

    def _load_form(self) -> None:
        r = self.remote
        self.user_edit.setText(r.username or self.profile.username or "root")
        self.port_spin.setValue(r.port or 3389)
        self.chk_tunnel.setChecked(bool(r.protect_with_tunnel))
        self.chk_fullscreen.setChecked(bool(r.fullscreen))
        res = r.resolution or suggest_rdp_geometry()[0]
        idx = self.resolution.findText(res)
        if idx >= 0:
            self.resolution.setCurrentIndex(idx)
        else:
            self.resolution.setEditText(res)
        q = (r.quality or "140").strip()
        if q not in ("100", "140", "180"):
            q = "140"
        sidx = self.scale.findData(q)
        if sidx >= 0:
            self.scale.setCurrentIndex(sidx)
        key = r.credential_service_key()
        if not key and self.profile.id:
            key = f"remote-{self.profile.id}"
        pwd = self.credentials.get_remote_password(key) if key else None
        if not pwd:
            pwd = self.credentials.get_server_password(
                self.profile.credential_service_key()
            )
        if pwd:
            self.password.setText(pwd)

    def _bootstrap_freerdp(self) -> None:
        if frdp_bundle.is_ready():
            self._set_status(
                f"FreeRDP pronto · {frdp_bundle.resolve_xfreerdp()}", ok=True
            )
            return
        self._set_status("Baixando FreeRDP embutido…")
        from app.workers.async_bridge import schedule

        schedule(self._ensure_frdp_async(), name="frdp-bundle")

    async def _ensure_frdp_async(self) -> None:
        ok, msg = await asyncio.to_thread(frdp_bundle.ensure_freerdp)
        self._set_status(msg if ok else msg.split("\n")[0], ok=ok)
        self._log(msg)

    def _collect(self) -> RemoteProfile:
        r = self.remote
        r.server_id = self.profile.id
        r.enabled = True
        r.protocol = RemoteProtocol.RDP
        r.use_ssh_host = True
        r.host = self.profile.host
        r.port = self.port_spin.value()
        r.username = self.user_edit.text().strip() or self.profile.username
        r.protect_with_tunnel = self.chk_tunnel.isChecked()
        r.fullscreen = self.chk_fullscreen.isChecked()
        r.resolution = self.resolution.currentText().strip() or "1600x900"
        r.quality = str(self.scale.currentData() or "140")
        r.auto_scale = True
        r.clipboard = True
        r.audio = False
        return r

    def _save_quiet(self) -> RemoteProfile:
        r = self._collect()
        self.db.save_remote_profile(r)
        self.remote = r
        pwd = self.password.text().strip()
        if pwd:
            try:
                self.credentials.store_remote_password(
                    r.credential_service_key(), pwd
                )
            except RuntimeError as exc:
                self._log(f"Keyring: {exc}")
        return r

    def _require_ssh_if_tunnel(self) -> bool:
        if not self.chk_tunnel.isChecked():
            return True
        if not self.profile.id or not self.session_manager.is_connected(self.profile.id):
            QMessageBox.warning(
                self,
                "SSH",
                "Com túnel SSH ativo, conecte o SSH deste servidor primeiro.",
            )
            return False
        return True

    def _connect(self) -> None:
        if not self._require_ssh_if_tunnel():
            return
        user = self.user_edit.text().strip()
        password = self.password.text().strip()
        if not user:
            QMessageBox.warning(self, "RDP", "Informe o usuário RDP.")
            return
        if not password:
            QMessageBox.warning(self, "RDP", "Informe a senha do desktop.")
            return
        if not frdp_bundle.is_ready():
            self._set_status("Preparando FreeRDP…")
            from app.workers.async_bridge import schedule

            schedule(self._connect_after_bundle(), name="rdp-bundle-then")
            return
        self._start_connect()

    async def _connect_after_bundle(self) -> None:
        ok, msg = await asyncio.to_thread(frdp_bundle.ensure_freerdp)
        self._log(msg)
        if not ok:
            self._set_status("FreeRDP indisponível", ok=False)
            QMessageBox.warning(self, "FreeRDP", msg)
            return
        self._start_connect()

    def _start_connect(self) -> None:
        r = self._save_quiet()
        password = self.password.text().strip()
        self.btn_connect.setEnabled(False)
        self._set_status("Conectando RDP…")
        self._log(
            f"Destino: {self.profile.host}:{r.port} · usuário={r.username} · "
            f"túnel={'sim' if r.protect_with_tunnel else 'não'}"
        )
        from app.workers.async_bridge import schedule

        schedule(self._connect_async(r, password), name="rdp-connect")

    async def _connect_async(self, r: RemoteProfile, password: str) -> None:
        tunnel_port = None
        tunnel_id = None
        try:
            # Encerrar sessão anterior
            if self.profile.id:
                self.launcher.stop(self.profile.id)
            if self._tunnel_id is not None:
                try:
                    await self.tunnel_manager.stop(self._tunnel_id)
                except Exception:  # noqa: BLE001
                    pass
                self._tunnel_id = None

            if r.protect_with_tunnel:
                client = self.session_manager.get(self.profile.id)  # type: ignore[arg-type]
                if client:
                    self._log("Verificando xrdp no servidor…")
                    chk = await check_remote_rdp(client, r.port or 3389)
                    if not chk.rdp_port_open:
                        self._log("Porta RDP fechada — tentando iniciar xrdp…")
                        await start_xrdp_service(client)
                        await asyncio.sleep(1.5)
                        chk = await check_remote_rdp(client, r.port or 3389)
                    if not chk.rdp_port_open:
                        self._set_status("xrdp não está ativo na VPS", ok=False)
                        self._log(
                            "Nenhum serviço na porta RDP. Use «Instalar xrdp na VPS»."
                        )
                        QMessageBox.warning(
                            self,
                            "RDP",
                            f"Nenhum serviço RDP na porta {r.port} do servidor.\n\n"
                            "Clique em «Instalar xrdp na VPS» ou inicie o xrdp manualmente.",
                        )
                        return
                    self._log(f"OK: {chk.message}")

                listen = self.tunnel_manager.allocate_port("127.0.0.1")
                tid = -9200 - int(self.profile.id or 0)
                tp = TunnelProfile(
                    id=tid,
                    server_id=self.profile.id,
                    name=f"rdp-{self.profile.id}",
                    tunnel_type=TunnelType.LOCAL,
                    listen_address="127.0.0.1",
                    listen_port=listen,
                    dest_host="127.0.0.1",
                    dest_port=r.port or 3389,
                    local_only=True,
                )
                await self.tunnel_manager.start(tp)
                tunnel_port = listen
                tunnel_id = tid
                self._tunnel_id = tid
                self._log(f"Túnel SSH: 127.0.0.1:{listen} → 127.0.0.1:{r.port}")
                await asyncio.sleep(0.3)  # estabilizar túnel

            # Log do freerdp em arquivo (para diagnosticar falha)
            log_dir = ensure_secure_dir(app_cache_dir() / "rdp-logs")
            self._log_file = log_dir / f"rdp-{self.profile.id or 0}.log"
            try:
                self._log_file.write_text("", encoding="utf-8")
            except OSError:
                pass

            exe = frdp_bundle.resolve_xfreerdp()
            env = frdp_bundle.freerdp_env(exe or "")

            session = self.launcher.launch(
                r,
                self.profile,
                password=password,
                tunnel_local_port=tunnel_port,
                tunnel_stop=None,  # gerenciamos o túnel aqui
                parent_window=None,  # janela externa — estável
                freerdp_exe=exe,
                freerdp_env=env,
                stderr_path=self._log_file,
            )

            # Aguardar um pouco: se morrer na hora, mostrar erro real
            await asyncio.sleep(1.2)
            proc = session.process
            if proc is not None and proc.poll() is not None:
                err = self._read_rdp_log()
                self._log(f"FreeRDP encerrou (código {proc.returncode}).")
                if err:
                    self._log(err)
                if tunnel_id is not None:
                    await self.tunnel_manager.stop(tunnel_id)
                    self._tunnel_id = None
                self._set_status("Falha ao abrir RDP", ok=False)
                QMessageBox.warning(
                    self,
                    "RDP falhou",
                    "O FreeRDP fechou imediatamente.\n\n"
                    + (err[:800] if err else "Sem detalhes no log.\n"
                    "Confira usuário/senha e se o xrdp está rodando."),
                )
                return

            self._set_status(
                f"RDP ativo · PID {proc.pid if proc else '?'} · "
                f"{r.username}@{self.profile.host}:{r.port}",
                ok=True,
            )
            self._log("Janela do FreeRDP aberta. Use o desktop remoto nela.")
        except ProcessError as exc:
            if tunnel_id is not None:
                try:
                    await self.tunnel_manager.stop(tunnel_id)
                except Exception:  # noqa: BLE001
                    pass
                self._tunnel_id = None
            self._set_status(str(exc), ok=False)
            self._log(str(exc))
            QMessageBox.warning(self, "RDP", str(exc))
        except Exception as exc:  # noqa: BLE001
            if tunnel_id is not None:
                try:
                    await self.tunnel_manager.stop(tunnel_id)
                except Exception:  # noqa: BLE001
                    pass
                self._tunnel_id = None
            self._set_status(str(exc), ok=False)
            self._log(str(exc))
            QMessageBox.warning(self, "RDP", str(exc))
        finally:
            self.btn_connect.setEnabled(True)

    def _read_rdp_log(self) -> str:
        if not self._log_file or not self._log_file.is_file():
            return ""
        try:
            text = self._log_file.read_text(encoding="utf-8", errors="replace")
            # sanitizar senha se vazou
            return text[-2000:]
        except OSError:
            return ""

    def _disconnect(self) -> None:
        if self.profile.id is not None:
            self.launcher.stop(self.profile.id)
        if self._tunnel_id is not None:
            from app.workers.async_bridge import schedule

            tid = self._tunnel_id
            self._tunnel_id = None

            async def _stop() -> None:
                await self.tunnel_manager.stop(tid)

            schedule(_stop(), name="rdp-tun-stop")
        self._set_status("Desconectado")
        self._log("Sessão encerrada.")

    def _poll_session(self) -> None:
        if not self.profile.id:
            return
        session = self.launcher.get_session(self.profile.id)
        if session and session.is_running():
            return
        # processo morreu
        if self._tunnel_id is not None and "RDP ativo" in self.lbl_status.text():
            err = self._read_rdp_log()
            if err:
                self._log("Log FreeRDP:\n" + err)
            from app.workers.async_bridge import schedule

            tid = self._tunnel_id
            self._tunnel_id = None

            async def _stop() -> None:
                try:
                    await self.tunnel_manager.stop(tid)
                except Exception:  # noqa: BLE001
                    pass

            schedule(_stop(), name="rdp-tun-auto-stop")
            self._set_status("Sessão RDP encerrada")

    def _fix_dpi(self) -> None:
        if not self.profile.id or not self.session_manager.is_connected(self.profile.id):
            QMessageBox.warning(self, "SSH", "Conecte o SSH primeiro.")
            return
        scale = int(self.scale.currentData() or 140)
        dpi = {100: 96, 140: 120, 180: 144}.get(scale, 120)
        self._log(f"Ajustando DPI XFCE → {dpi}…")
        from app.workers.async_bridge import schedule

        schedule(self._fix_dpi_async(dpi), name="fix-dpi")

    async def _fix_dpi_async(self, dpi: int) -> None:
        client = self.session_manager.get(self.profile.id)  # type: ignore[arg-type]
        if not client:
            return
        result = await fix_xfce_dpi(client, dpi)
        self._log(result.message)
        self._set_status(result.message, ok=result.success)
        if result.success:
            QMessageBox.information(
                self,
                "Menus",
                result.message
                + "\n\nDesconecte o RDP e conecte de novo para aplicar.",
            )
        else:
            QMessageBox.warning(self, "Menus", result.message)

    def _prepare_vps(self) -> None:
        if not self.profile.id or not self.session_manager.is_connected(self.profile.id):
            QMessageBox.warning(self, "SSH", "Conecte o SSH primeiro.")
            return
        reply = QMessageBox.question(
            self,
            "Instalar xrdp",
            "Instalar xrdp + XFCE na VPS? Pode demorar vários minutos.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.btn_prepare.setEnabled(False)
        self._set_status("Instalando xrdp…")
        self._log("Instalação xrdp iniciada…")
        from app.workers.async_bridge import schedule

        schedule(self._prepare_async(), name="prepare-xrdp")

    async def _prepare_async(self) -> None:
        try:
            client = self.session_manager.get(self.profile.id)  # type: ignore[arg-type]
            if not client:
                return
            result = await install_xrdp_desktop(client)
            self._log(result.message)
            if result.details:
                self._log("\n".join(result.details.strip().splitlines()[-12:]))
            self._set_status(result.message, ok=result.success)
            if result.success:
                QMessageBox.information(self, "VPS", result.message)
            else:
                QMessageBox.warning(self, "VPS", result.message)
        finally:
            self.btn_prepare.setEnabled(True)
