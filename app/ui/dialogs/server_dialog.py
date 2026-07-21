"""Diálogo de cadastro/edição de servidor."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.models.server import AuthMethod, ServerGroup, ServerProfile
from app.ui.title_bar import apply_dialog_chrome
from app.ui.widgets import PasswordLineEdit
from app.utils.enums import coerce_enum


class ServerDialog(QDialog):
    """Cadastro/edição de servidor SSH."""

    def __init__(
        self,
        parent=None,
        *,
        server: Optional[ServerProfile] = None,
        groups: Optional[list[ServerGroup]] = None,
        servers: Optional[list[ServerProfile]] = None,
        remote=None,  # legado ignorado
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Editar servidor" if server else "Novo servidor")
        self.setMinimumWidth(560)
        self.setMinimumHeight(520)
        self._server = server
        self._groups = groups or []
        self._servers = servers or []
        self._password = PasswordLineEdit()
        self._passphrase = PasswordLineEdit()
        self._build_ui()
        if server:
            self._load(server)
        apply_dialog_chrome(self)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._tab_general(), "Geral")
        tabs.addTab(self._tab_auth(), "Autenticação")
        tabs.addTab(self._tab_paths(), "Caminhos e opções")
        root.addWidget(tabs)

        self.btn_test = QPushButton("Testar conexão")
        self.btn_test.clicked.connect(self._on_test_clicked)
        self.test_result = QLabel("")
        self.test_result.setWordWrap(True)
        self.test_result.setObjectName("mutedLabel")

        row = QHBoxLayout()
        row.addWidget(self.btn_test)
        row.addWidget(self.test_result, 1)
        root.addLayout(row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
        if save_btn:
            save_btn.setObjectName("primaryBtn")
            save_btn.setText("Salvar")
        root.addWidget(buttons)

    def _tab_general(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Ex: Produção Web")
        self.group_combo = QComboBox()
        self._reload_groups()
        from app.ui.icons import set_button_icon

        self.btn_new_group = QPushButton()
        self.btn_new_group.setObjectName("iconBtn")
        self.btn_new_group.setFixedSize(40, 36)
        set_button_icon(self.btn_new_group, "plus", size=16, tooltip="Criar novo grupo")
        self.btn_new_group.clicked.connect(self._create_group)
        group_row = QHBoxLayout()
        group_row.setContentsMargins(0, 0, 0, 0)
        group_row.setSpacing(8)
        group_row.addWidget(self.group_combo, 1)
        group_row.addWidget(self.btn_new_group)
        group_wrap = QWidget()
        group_wrap.setLayout(group_row)
        self.desc_edit = QTextEdit()
        self.desc_edit.setMaximumHeight(70)
        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("IP ou hostname")
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(22)
        self.user_edit = QLineEdit()

        form.addRow("Nome da conexão *", self.name_edit)
        form.addRow("Grupo", group_wrap)
        form.addRow("Descrição", self.desc_edit)
        form.addRow("IP / Hostname *", self.host_edit)
        form.addRow("Porta SSH", self.port_spin)
        form.addRow("Usuário *", self.user_edit)
        return w

    def _reload_groups(self, select_id: Optional[int] = None) -> None:
        current = select_id if select_id is not None else self.group_combo.currentData()
        self.group_combo.clear()
        self.group_combo.addItem("— Sem grupo —", None)
        for g in self._groups:
            self.group_combo.addItem(g.name, g.id)
        if current is not None:
            idx = self.group_combo.findData(current)
            if idx >= 0:
                self.group_combo.setCurrentIndex(idx)

    def _create_group(self) -> None:
        """Cria grupo na hora (precisa do Database via parent MainWindow)."""
        parent = self.parent()
        db = getattr(parent, "db", None) if parent is not None else None
        if db is None:
            QMessageBox.information(
                self,
                "Grupos",
                "Abra “Editar → Gerenciar grupos…” na janela principal para criar grupos.",
            )
            return
        from app.ui.dialogs.group_dialog import quick_create_group

        group = quick_create_group(db, self)
        if group is None:
            return
        self._groups = db.list_groups()
        self._reload_groups(select_id=group.id)

    def _tab_auth(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.auth_combo = QComboBox()
        # Guardar .value (str): QComboBox do PySide6 não preserva str Enum
        for m in AuthMethod:
            self.auth_combo.addItem(m.label_pt, m.value)
        self.auth_combo.currentIndexChanged.connect(self._on_auth_changed)
        self.key_path = QLineEdit()
        self.key_browse = QPushButton("…")
        self.key_browse.setFixedWidth(36)
        self.key_browse.clicked.connect(self._browse_key)
        key_row = QHBoxLayout()
        key_row.addWidget(self.key_path, 1)
        key_row.addWidget(self.key_browse)
        key_w = QWidget()
        key_w.setLayout(key_row)
        self.remember_cb = QCheckBox("Lembrar credencial no cofre do sistema (keyring)")
        self.remember_cb.setChecked(True)

        form.addRow("Método *", self.auth_combo)
        form.addRow("Senha", self._password)
        form.addRow("Chave privada", key_w)
        form.addRow("Passphrase", self._passphrase)
        form.addRow("", self.remember_cb)

        self.jump_combo = QComboBox()
        self.jump_combo.addItem("— Nenhum —", None)
        for s in self._servers:
            if self._server and s.id == self._server.id:
                continue
            self.jump_combo.addItem(f"{s.name} ({s.display_host()})", s.id)
        form.addRow("Jump host / bastion", self.jump_combo)
        self._on_auth_changed()
        return w

    def _tab_paths(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.remote_path = QLineEdit("~")
        self.local_path = QLineEdit()
        self.local_browse = QPushButton("…")
        self.local_browse.setFixedWidth(36)
        self.local_browse.clicked.connect(self._browse_local)
        local_row = QHBoxLayout()
        local_row.addWidget(self.local_path, 1)
        local_row.addWidget(self.local_browse)
        local_w = QWidget()
        local_w.setLayout(local_row)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1, 600)
        self.timeout_spin.setValue(30)
        self.timeout_spin.setSuffix(" s")
        self.keepalive_spin = QSpinBox()
        self.keepalive_spin.setRange(0, 600)
        self.keepalive_spin.setValue(30)
        self.keepalive_spin.setSuffix(" s")
        self.encoding_combo = QComboBox()
        self.encoding_combo.addItems(["utf-8", "latin-1", "cp850", "iso-8859-1"])
        self.auto_reconnect = QCheckBox("Reconexão automática")

        form.addRow("Caminho remoto inicial", self.remote_path)
        form.addRow("Caminho local inicial", local_w)
        form.addRow("Timeout", self.timeout_spin)
        form.addRow("Keep-alive", self.keepalive_spin)
        form.addRow("Codificação do terminal", self.encoding_combo)
        form.addRow("", self.auto_reconnect)
        return w

    def _current_auth(self) -> AuthMethod:
        return coerce_enum(AuthMethod, self.auth_combo.currentData(), AuthMethod.PASSWORD)

    def _on_auth_changed(self) -> None:
        method = self._current_auth()
        is_pass = method == AuthMethod.PASSWORD
        is_key = method in (AuthMethod.KEY, AuthMethod.KEY_PASSPHRASE)
        is_passphrase = method == AuthMethod.KEY_PASSPHRASE
        self._password.setEnabled(is_pass)
        self.key_path.setEnabled(is_key)
        self.key_browse.setEnabled(is_key)
        self._passphrase.setEnabled(is_passphrase)

    def _browse_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Chave privada SSH", str(Path.home() / ".ssh"), "All (*)"
        )
        if path:
            self.key_path.setText(path)

    def _browse_local(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Diretório local", str(Path.home()))
        if path:
            self.local_path.setText(path)

    def _load(self, server: ServerProfile) -> None:
        self.name_edit.setText(server.name)
        idx = self.group_combo.findData(server.group_id)
        if idx >= 0:
            self.group_combo.setCurrentIndex(idx)
        self.desc_edit.setPlainText(server.description)
        self.host_edit.setText(server.host)
        self.port_spin.setValue(server.port)
        self.user_edit.setText(server.username)
        auth_val = (
            server.auth_method.value
            if isinstance(server.auth_method, AuthMethod)
            else server.auth_method
        )
        aidx = self.auth_combo.findData(auth_val)
        if aidx >= 0:
            self.auth_combo.setCurrentIndex(aidx)
        self.key_path.setText(server.private_key_path)
        self.remember_cb.setChecked(server.remember_credential)
        jidx = self.jump_combo.findData(server.jump_host_id)
        if jidx >= 0:
            self.jump_combo.setCurrentIndex(jidx)
        self.remote_path.setText(server.remote_path)
        self.local_path.setText(server.local_path)
        self.timeout_spin.setValue(server.timeout)
        self.keepalive_spin.setValue(server.keepalive)
        eidx = self.encoding_combo.findText(server.terminal_encoding)
        if eidx >= 0:
            self.encoding_combo.setCurrentIndex(eidx)
        self.auto_reconnect.setChecked(server.auto_reconnect)

    def get_profile(self) -> ServerProfile:
        base = self._server or ServerProfile()
        base.name = self.name_edit.text().strip()
        base.group_id = self.group_combo.currentData()
        base.description = self.desc_edit.toPlainText().strip()
        base.host = self.host_edit.text().strip()
        base.port = self.port_spin.value()
        base.username = self.user_edit.text().strip()
        base.auth_method = self._current_auth()
        base.private_key_path = self.key_path.text().strip()
        base.remember_credential = self.remember_cb.isChecked()
        base.jump_host_id = self.jump_combo.currentData()
        base.remote_path = self.remote_path.text().strip() or "~"
        base.local_path = self.local_path.text().strip()
        base.timeout = self.timeout_spin.value()
        base.keepalive = self.keepalive_spin.value()
        base.terminal_encoding = self.encoding_combo.currentText()
        # cor de perfil removida da UI — mantém valor existente ou padrão
        if not base.color:
            base.color = "#2dd4bf"
        base.auto_reconnect = self.auto_reconnect.isChecked()
        return base

    def get_password(self) -> str:
        return self._password.text()

    def get_passphrase(self) -> str:
        return self._passphrase.text()

    def _on_accept(self) -> None:
        profile = self.get_profile()
        errors = profile.validate()
        if errors:
            QMessageBox.warning(self, "Validação", "\n".join(errors))
            return
        self.accept()

    def _on_test_clicked(self) -> None:
        # Sinalizado para o MainWindow interceptar via atributo
        self.test_result.setText("Use Conectar na janela principal para validar a conexão.")
        # O main window conecta btn_test se necessário
        if hasattr(self, "on_test_request") and callable(self.on_test_request):
            self.on_test_request()
