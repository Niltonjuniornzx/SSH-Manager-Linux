"""Barra de transferências mínima — só status, sem botões inúteis."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QWidget,
)

from app.models.transfer import TransferStatus
from app.sftp.client import format_size

if TYPE_CHECKING:
    from app.transfers.queue import TransferQueue


class TransfersPanel(QWidget):
    """Uma linha fina de status. Sem Pausar/Continuar/lista expandida."""

    expanded_changed = Signal(bool)  # compat (sempre false)

    def __init__(self, queue: "TransferQueue", parent=None) -> None:
        super().__init__(parent)
        self.queue = queue
        self.setMaximumHeight(28)
        self.setMinimumHeight(24)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(10)

        self.lbl = QLabel("Transferências: ocioso")
        self.lbl.setObjectName("mutedLabel")
        self.progress = QProgressBar()
        self.progress.setMaximumHeight(12)
        self.progress.setMaximumWidth(180)
        self.progress.setTextVisible(False)
        self.progress.setValue(0)

        layout.addWidget(self.lbl, 1)
        layout.addWidget(self.progress)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(500)

    def is_expanded(self) -> bool:
        return False

    def expand(self) -> None:
        pass

    def collapse(self) -> None:
        pass

    def refresh(self) -> None:
        items = self.queue.list_items()
        if not items:
            self.lbl.setText("Transferências: ocioso")
            self.progress.setValue(0)
            return

        active = [
            i
            for i in items
            if i.status
            in (TransferStatus.RUNNING, TransferStatus.QUEUED, TransferStatus.PAUSED)
        ]
        done = sum(1 for i in items if i.status == TransferStatus.COMPLETED)
        failed = sum(1 for i in items if i.status == TransferStatus.FAILED)
        transferred, total = self.queue.total_progress

        if total > 0:
            self.progress.setValue(int(transferred * 100 / total))
        elif active:
            self.progress.setValue(0)
        else:
            self.progress.setValue(100 if done and not failed else 0)

        last = items[-1].display_name
        parts = []
        if active:
            parts.append(f"{len(active)} em andamento")
        if done:
            parts.append(f"{done} ok")
        if failed:
            parts.append(f"{failed} falha")
        parts.append(last)
        if total > 0:
            parts.append(f"{format_size(transferred)}/{format_size(total)}")
        self.lbl.setText(" · ".join(parts))
