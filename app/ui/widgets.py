"""Widgets reutilizáveis."""

from __future__ import annotations


from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)


class SearchBar(QWidget):
    textChanged = Signal(str)

    def __init__(self, placeholder: str = "Buscar…", parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(f"  🔍  {placeholder}")
        self.edit.setClearButtonEnabled(True)
        self.edit.setMinimumHeight(36)
        self.edit.textChanged.connect(self.textChanged.emit)
        layout.addWidget(self.edit)

    def text(self) -> str:
        return self.edit.text()

    def setText(self, text: str) -> None:
        self.edit.setText(text)


class StatusDot(QWidget):
    """Indicador circular de status."""

    COLORS = {
        "connected": "#3ecf8e",
        "connecting": "#f0c040",
        "disconnected": "#6a7080",
        "error": "#ff6b6b",
        "running": "#3ecf8e",
        "stopped": "#6a7080",
    }

    def __init__(self, status: str = "disconnected", parent=None) -> None:
        super().__init__(parent)
        self._status = status
        self.setFixedSize(12, 12)

    def set_status(self, status: str) -> None:
        self._status = status
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self.COLORS.get(self._status, "#6a7080"))
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(1, 1, 10, 10)


class PasswordLineEdit(QWidget):
    """Campo de senha com botão mostrar/ocultar."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.toggle = QPushButton("👁")
        self.toggle.setFixedWidth(36)
        self.toggle.setCheckable(True)
        self.toggle.toggled.connect(self._on_toggle)
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.toggle)

    def _on_toggle(self, checked: bool) -> None:
        self.edit.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )

    def text(self) -> str:
        return self.edit.text()

    def setText(self, text: str) -> None:
        self.edit.setText(text)

    def clear(self) -> None:
        self.edit.clear()


class FormRow(QWidget):
    def __init__(self, label: str, widget: QWidget, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        lbl = QLabel(label)
        lbl.setMinimumWidth(160)
        lbl.setObjectName("mutedLabel")
        layout.addWidget(lbl)
        layout.addWidget(widget, 1)
