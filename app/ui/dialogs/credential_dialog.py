"""Solicita senha/passphrase no momento da conexão."""

from __future__ import annotations


from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
)

from app.models.server import AuthMethod, ServerProfile
from app.ui.title_bar import apply_dialog_chrome
from app.ui.widgets import PasswordLineEdit


class CredentialDialog(QDialog):
    def __init__(
        self,
        profile: ServerProfile,
        parent=None,
        *,
        title: str = "Credenciais",
        message: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(400)
        self.profile = profile
        layout = QVBoxLayout(self)
        info = message or (
            f"Informe a credencial para <b>{profile.username}@{profile.display_host()}</b>"
        )
        layout.addWidget(QLabel(info))
        form = QFormLayout()
        self.password = PasswordLineEdit()
        self.remember = QCheckBox("Lembrar no cofre do sistema")
        self.remember.setChecked(profile.remember_credential)
        if profile.auth_method == AuthMethod.PASSWORD:
            form.addRow("Senha", self.password)
        elif profile.auth_method == AuthMethod.KEY_PASSPHRASE:
            form.addRow("Passphrase da chave", self.password)
        else:
            form.addRow("Senha / passphrase", self.password)
        form.addRow("", self.remember)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        apply_dialog_chrome(self)

    def get_secret(self) -> str:
        return self.password.text()

    def should_remember(self) -> bool:
        return self.remember.isChecked()


class HostKeyDialog(QDialog):
    """Confirmação explícita de host key na primeira conexão (nunca silencioso)."""

    def __init__(self, message: str, fingerprint: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Confirmar host key")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        lbl = QLabel(message)
        lbl.setWordWrap(True)
        layout.addWidget(lbl)
        fp = QLabel(f"<code>{fingerprint}</code>")
        fp.setTextInteractionFlags(
            fp.textInteractionFlags()
            | __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(fp)
        note = QLabel(
            "Nenhuma senha, chave ou agente será usado até você confirmar."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No
        )
        yes = buttons.button(QDialogButtonBox.StandardButton.Yes)
        no = buttons.button(QDialogButtonBox.StandardButton.No)
        if yes:
            yes.setText("Confiar e conectar")
        if no:
            no.setText("Recusar")
        # Sem botão "Ignorar" — confirmação explícita ou recusa.
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        apply_dialog_chrome(self)
