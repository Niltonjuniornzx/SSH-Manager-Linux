"""Diálogo de configurações."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.i18n import tr
from app.models.settings import AppSettings
from app.security.lock import hash_master_password
from app.ui.title_bar import apply_dialog_chrome

if TYPE_CHECKING:
    from app.security.hostkeys import HostKeyManager


class SettingsDialog(QDialog):
    def __init__(
        self,
        settings: AppSettings,
        parent=None,
        *,
        host_keys: Optional["HostKeyManager"] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Configurações"))
        self.setMinimumWidth(520)
        self._settings = settings
        self._host_keys = host_keys
        self._new_master_hash: Optional[str] = None
        self._clear_master = False
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._tab_general(), tr("Geral"))
        tabs.addTab(self._tab_transfers(), tr("Transferências"))
        tabs.addTab(self._tab_clients(), tr("Clientes externos"))
        tabs.addTab(self._tab_security(), tr("Segurança"))
        layout.addWidget(tabs)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
        if save_btn:
            save_btn.setText(tr("Salvar"))
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn:
            cancel_btn.setText(tr("Cancelar"))
        layout.addWidget(buttons)
        self._load()
        apply_dialog_chrome(self)

    def _tab_general(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.theme = QComboBox()
        self.theme.addItem(tr("Escuro"), "dark")
        self.theme.setEnabled(False)
        self.language = QComboBox()
        self.language.addItem("Português (Brasil)", "pt_BR")
        self.language.addItem("English", "en")
        self.timeout = QSpinBox()
        self.timeout.setRange(1, 600)
        self.timeout.setSuffix(tr(" s"))
        self.keepalive = QSpinBox()
        self.keepalive.setRange(0, 600)
        self.keepalive.setSuffix(tr(" s"))
        self.auto_reconnect = QCheckBox(tr("Reconexão automática"))
        self.confirm_delete = QCheckBox(tr("Confirmar antes de excluir"))
        self.show_hidden = QCheckBox(tr("Mostrar arquivos ocultos"))
        self.notifications = QCheckBox(tr("Notificações do sistema"))
        self.download_dir = QLineEdit()
        btn = QPushButton("…")
        btn.setFixedWidth(36)
        btn.clicked.connect(self._browse_dl)
        row = QHBoxLayout()
        row.addWidget(self.download_dir, 1)
        row.addWidget(btn)
        wrap = QWidget()
        wrap.setLayout(row)
        self.term_font = QLineEdit()
        self.term_font_size = QSpinBox()
        self.term_font_size.setRange(8, 32)
        form.addRow(tr("Tema"), self.theme)
        form.addRow(tr("Idioma"), self.language)
        form.addRow(tr("Timeout padrão"), self.timeout)
        form.addRow(tr("Keep-alive"), self.keepalive)
        form.addRow("", self.auto_reconnect)
        form.addRow("", self.confirm_delete)
        form.addRow("", self.show_hidden)
        form.addRow("", self.notifications)
        form.addRow(tr("Downloads"), wrap)
        form.addRow(tr("Fonte do terminal"), self.term_font)
        form.addRow(tr("Tamanho da fonte"), self.term_font_size)
        return w

    def _tab_transfers(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.max_xfer = QSpinBox()
        self.max_xfer.setRange(1, 16)
        self.speed_limit = QSpinBox()
        self.speed_limit.setRange(0, 100_000_000)
        self.speed_limit.setSuffix(tr(" B/s (0=ilimitado)"))
        self.conflict = QComboBox()
        for val, label in (
            ("ask", tr("Perguntar")),
            ("overwrite", tr("Sobrescrever")),
            ("skip", tr("Ignorar")),
            ("rename", tr("Renomear")),
        ):
            self.conflict.addItem(label, val)
        self.verify_hash = QCheckBox(tr("Verificar hash após transferência"))
        form.addRow(tr("Transferências simultâneas"), self.max_xfer)
        form.addRow(tr("Limite de velocidade"), self.speed_limit)
        form.addRow(tr("Arquivo existente"), self.conflict)
        form.addRow("", self.verify_hash)
        return w

    def _tab_clients(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.ext_term = QComboBox()
        for v in ("auto", "konsole", "gnome-terminal", "xterm"):
            self.ext_term.addItem(v, v)
        self.ext_editor = QLineEdit()
        form.addRow(tr("Terminal externo"), self.ext_term)
        form.addRow(tr("Editor externo"), self.ext_editor)
        return w

    def _tab_security(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        form = QFormLayout()
        self.lock_timeout = QSpinBox()
        self.lock_timeout.setRange(0, 240)
        self.lock_timeout.setSuffix(tr(" min (0=desligado)"))
        self.master_pw = QCheckBox(
            tr("Exigir senha mestra no desbloqueio (camada adicional)")
        )
        form.addRow(tr("Bloqueio automático"), self.lock_timeout)
        form.addRow("", self.master_pw)
        layout.addLayout(form)

        pw_row = QHBoxLayout()
        btn_set = QPushButton(tr("Definir senha mestra…"))
        btn_set.clicked.connect(self._set_master_password)
        btn_clear = QPushButton(tr("Remover senha mestra"))
        btn_clear.clicked.connect(self._clear_master_password)
        pw_row.addWidget(btn_set)
        pw_row.addWidget(btn_clear)
        layout.addLayout(pw_row)
        self.master_status = QLabel("")
        self.master_status.setObjectName("mutedLabel")
        layout.addWidget(self.master_status)

        layout.addWidget(QLabel(tr("Host keys confiáveis")))
        self.trusted_list = QListWidget()
        self.trusted_list.setMinimumHeight(140)
        layout.addWidget(self.trusted_list)
        btn_remove = QPushButton(tr("Remover chave selecionada"))
        btn_remove.clicked.connect(self._remove_trusted_host)
        layout.addWidget(btn_remove)
        note = QLabel(
            tr(
                "Se a host key de um servidor mudar, remova a entrada "
                "confiável e confirme a nova fingerprint na próxima conexão. "
                "Não há opção para ignorar silenciosamente."
            )
        )
        note.setWordWrap(True)
        note.setObjectName("mutedLabel")
        layout.addWidget(note)
        return w

    def _refresh_trusted(self) -> None:
        self.trusted_list.clear()
        if not self._host_keys:
            return
        for h in self._host_keys.list_trusted():
            text = (
                f"{h.get('hostname')}:{h.get('port')}  "
                f"{h.get('key_type')}  {h.get('fingerprint_sha256')}"
            )
            item = QListWidgetItem(text)
            item.setData(256, h.get("id"))  # Qt.UserRole
            item.setData(257, (h.get("hostname"), h.get("port"), h.get("key_type")))
            self.trusted_list.addItem(item)

    def _remove_trusted_host(self) -> None:
        item = self.trusted_list.currentItem()
        if not item or not self._host_keys:
            return
        data = item.data(257)
        if not data:
            return
        hostname, port, key_type = data
        reply = QMessageBox.question(
            self,
            tr("Remover host key"),
            tr(
                "Remover a chave confiável de {host}:{port}?\n"
                "Na próxima conexão será pedida confirmação."
            ).replace("{host}", str(hostname)).replace("{port}", str(port)),
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._host_keys.remove(str(hostname), int(port), key_type)
        self._refresh_trusted()

    def _set_master_password(self) -> None:
        pw1, ok1 = QInputDialog.getText(
            self,
            tr("Senha mestra"),
            tr("Nova senha mestra:"),
            QLineEdit.EchoMode.Password,
        )
        if not ok1 or not pw1:
            return
        pw2, ok2 = QInputDialog.getText(
            self,
            tr("Senha mestra"),
            tr("Confirme a senha mestra:"),
            QLineEdit.EchoMode.Password,
        )
        if not ok2 or pw1 != pw2:
            QMessageBox.warning(self, tr("Senha mestra"), tr("As senhas não coincidem."))
            return
        if len(pw1) < 6:
            QMessageBox.warning(
                self, tr("Senha mestra"), tr("Use pelo menos 6 caracteres.")
            )
            return
        self._new_master_hash = hash_master_password(pw1)
        self._clear_master = False
        self.master_pw.setChecked(True)
        self.master_status.setText(tr("Senha mestra definida (Argon2id). Salve para aplicar."))
        pw1 = pw2 = ""  # noqa: F841

    def _clear_master_password(self) -> None:
        self._clear_master = True
        self._new_master_hash = None
        self.master_pw.setChecked(False)
        self.master_status.setText(tr("Senha mestra será removida ao salvar."))

    def _browse_dl(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            tr("Diretório de downloads"),
            self.download_dir.text() or str(Path.home()),
        )
        if path:
            self.download_dir.setText(path)

    def _load(self) -> None:
        s = self._settings
        idx = self.theme.findData(s.theme)
        if idx >= 0:
            self.theme.setCurrentIndex(idx)
        idx = self.language.findData(s.language)
        if idx >= 0:
            self.language.setCurrentIndex(idx)
        self.timeout.setValue(s.default_timeout)
        self.keepalive.setValue(s.default_keepalive)
        self.auto_reconnect.setChecked(s.auto_reconnect)
        self.confirm_delete.setChecked(s.confirm_delete)
        self.show_hidden.setChecked(s.show_hidden_files)
        self.notifications.setChecked(s.notifications)
        self.download_dir.setText(s.default_download_dir)
        self.term_font.setText(s.terminal_font)
        self.term_font_size.setValue(s.terminal_font_size)
        self.max_xfer.setValue(s.max_concurrent_transfers)
        self.speed_limit.setValue(s.speed_limit_bps)
        idx = self.conflict.findData(s.conflict_policy)
        if idx >= 0:
            self.conflict.setCurrentIndex(idx)
        self.verify_hash.setChecked(s.verify_transfer_hash)
        idx = self.ext_term.findData(s.external_terminal)
        if idx >= 0:
            self.ext_term.setCurrentIndex(idx)
        self.ext_editor.setText(s.external_editor)
        self.lock_timeout.setValue(s.lock_timeout_minutes)
        self.master_pw.setChecked(s.master_password_enabled)
        if s.master_password_hash:
            self.master_status.setText(tr("Senha mestra configurada."))
        else:
            self.master_status.setText(tr("Nenhuma senha mestra definida."))
        self._refresh_trusted()

    def get_settings(self) -> AppSettings:
        s = self._settings
        s.theme = "dark"
        lang = self.language.currentData()
        if lang not in ("pt_BR", "en"):
            lang = "en" if self.language.currentIndex() == 1 else "pt_BR"
        s.language = lang
        s.default_timeout = self.timeout.value()
        s.default_keepalive = self.keepalive.value()
        s.auto_reconnect = self.auto_reconnect.isChecked()
        s.confirm_delete = self.confirm_delete.isChecked()
        s.show_hidden_files = self.show_hidden.isChecked()
        s.notifications = self.notifications.isChecked()
        s.default_download_dir = self.download_dir.text().strip()
        s.terminal_font = self.term_font.text().strip() or "Monospace"
        s.terminal_font_size = self.term_font_size.value()
        s.max_concurrent_transfers = self.max_xfer.value()
        s.speed_limit_bps = self.speed_limit.value()
        s.conflict_policy = self.conflict.currentData()
        s.verify_transfer_hash = self.verify_hash.isChecked()
        s.external_terminal = self.ext_term.currentData()
        s.external_editor = self.ext_editor.text().strip()
        s.lock_timeout_minutes = self.lock_timeout.value()
        s.master_password_enabled = self.master_pw.isChecked()
        if self._clear_master:
            s.master_password_hash = ""
            s.master_password_enabled = False
        elif self._new_master_hash:
            s.master_password_hash = self._new_master_hash
            s.master_password_enabled = True
        return s
