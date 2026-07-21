"""Diálogo para gerenciar grupos de servidores."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.database.db import Database
from app.models.server import ServerGroup
from app.ui.icons import ui_icon
from app.ui.title_bar import apply_dialog_chrome


class GroupEditDialog(QDialog):
    """Criar ou editar um único grupo."""

    def __init__(
        self,
        parent=None,
        *,
        group: Optional[ServerGroup] = None,
        existing_names: Optional[list[str]] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Editar grupo" if group else "Novo grupo")
        self.setMinimumWidth(380)
        self._group = group
        self._existing = {n.lower() for n in (existing_names or [])}
        if group and group.name:
            self._existing.discard(group.name.lower())
        self._color = (group.color if group else "#2dd4bf") or "#2dd4bf"

        root = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Ex: Produção, Homologação, Casa…")
        if group:
            self.name_edit.setText(group.name)
        form.addRow("Nome *", self.name_edit)

        self.color_btn = QPushButton()
        self.color_btn.clicked.connect(self._pick_color)
        self._update_color_btn()
        form.addRow("Cor", self.color_btn)
        root.addLayout(form)

        tip = QLabel("Use grupos para organizar hosts na barra lateral.")
        tip.setObjectName("mutedLabel")
        tip.setWordWrap(True)
        root.addWidget(tip)

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
        apply_dialog_chrome(self)

    def _update_color_btn(self) -> None:
        self.color_btn.setText(self._color)
        self.color_btn.setStyleSheet(
            f"QPushButton {{ background-color: {self._color}; color: #0b0d12; "
            f"font-weight: 700; border-radius: 10px; min-height: 32px; }}"
        )

    def _pick_color(self) -> None:
        c = QColorDialog.getColor(QColor(self._color), self, "Cor do grupo")
        if c.isValid():
            self._color = c.name()
            self._update_color_btn()

    def _on_accept(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Grupo", "Informe o nome do grupo.")
            return
        if name.lower() in self._existing:
            QMessageBox.warning(self, "Grupo", f"Já existe um grupo chamado “{name}”.")
            return
        self.accept()

    def get_group(self) -> ServerGroup:
        base = self._group or ServerGroup()
        base.name = self.name_edit.text().strip()
        base.color = self._color
        return base


class GroupsDialog(QDialog):
    """Lista e gerencia todos os grupos."""

    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Grupos de servidores")
        self.setWindowIcon(ui_icon("folder-group", 32))
        self.setMinimumSize(440, 420)
        self._changed = False

        root = QVBoxLayout(self)
        title_row = QHBoxLayout()
        icon_lbl = QLabel()
        icon_lbl.setPixmap(ui_icon("folder-group", 28).pixmap(28, 28))
        title_row.addWidget(icon_lbl)
        head = QLabel("Organize seus hosts em grupos (Produção, Casa, Clientes…)")
        head.setObjectName("mutedLabel")
        head.setWordWrap(True)
        title_row.addWidget(head, 1)
        root.addLayout(title_row)

        self.list = QListWidget()
        self.list.setAlternatingRowColors(True)
        self.list.itemDoubleClicked.connect(lambda *_: self._edit())
        root.addWidget(self.list, 1)

        row = QHBoxLayout()
        btn_add = QPushButton("＋  Novo grupo")
        btn_add.setObjectName("primaryBtn")
        btn_add.clicked.connect(self._add)
        btn_edit = QPushButton("Editar")
        btn_edit.clicked.connect(self._edit)
        btn_del = QPushButton("Excluir")
        btn_del.setObjectName("dangerBtn")
        btn_del.clicked.connect(self._delete)
        row.addWidget(btn_add)
        row.addWidget(btn_edit)
        row.addWidget(btn_del)
        row.addStretch()
        root.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_btn:
            close_btn.setText("Fechar")
            close_btn.clicked.connect(self.accept)
        buttons.rejected.connect(self.accept)
        root.addWidget(buttons)

        self._reload()
        apply_dialog_chrome(self)

    @property
    def changed(self) -> bool:
        return self._changed

    def _reload(self) -> None:
        self.list.clear()
        for g in self.db.list_groups():
            # contagem de servidores
            count = sum(1 for s in self.db.list_servers() if s.group_id == g.id)
            item = QListWidgetItem(f"  {g.name}   ·   {count} host(s)")
            item.setData(Qt.ItemDataRole.UserRole, g.id)
            item.setForeground(QColor(g.color or "#2dd4bf"))
            item.setToolTip(f"Cor: {g.color}\nOrdem: {g.sort_order}")
            self.list.addItem(item)

    def _selected_group(self) -> Optional[ServerGroup]:
        items = self.list.selectedItems()
        if not items:
            return None
        gid = items[0].data(Qt.ItemDataRole.UserRole)
        if gid is None:
            return None
        return self.db.get_group(int(gid))

    def _names(self) -> list[str]:
        return [g.name for g in self.db.list_groups()]

    def _add(self) -> None:
        dlg = GroupEditDialog(self, existing_names=self._names())
        if not dlg.exec():
            return
        group = dlg.get_group()
        # sort_order no final
        groups = self.db.list_groups()
        group.sort_order = (max((g.sort_order for g in groups), default=-1) + 1)
        self.db.save_group(group)
        self._changed = True
        self._reload()

    def _edit(self) -> None:
        g = self._selected_group()
        if not g:
            QMessageBox.information(self, "Grupos", "Selecione um grupo.")
            return
        dlg = GroupEditDialog(self, group=g, existing_names=self._names())
        if not dlg.exec():
            return
        updated = dlg.get_group()
        self.db.save_group(updated)
        self._changed = True
        self._reload()

    def _delete(self) -> None:
        g = self._selected_group()
        if not g or g.id is None:
            QMessageBox.information(self, "Grupos", "Selecione um grupo.")
            return
        count = sum(1 for s in self.db.list_servers() if s.group_id == g.id)
        msg = f"Excluir o grupo “{g.name}”?"
        if count:
            msg += f"\n\n{count} host(s) ficarão sem grupo."
        reply = QMessageBox.question(
            self,
            "Excluir grupo",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.db.delete_group(g.id)
        self._changed = True
        self._reload()


def quick_create_group(db: Database, parent: Optional[QWidget] = None) -> Optional[ServerGroup]:
    """Atalho: cria um grupo e devolve o objeto salvo (ou None)."""
    names = [g.name for g in db.list_groups()]
    dlg = GroupEditDialog(parent, existing_names=names)
    if not dlg.exec():
        return None
    group = dlg.get_group()
    groups = db.list_groups()
    group.sort_order = max((g.sort_order for g in groups), default=-1) + 1
    return db.save_group(group)
