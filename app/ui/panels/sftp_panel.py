"""Gerenciador SFTP dual-pane estilo Bitvise.

- Painel local | painel remoto
- Navegação: voltar, avançar, subir, endereço, atualizar
- Arrastar e soltar entre painéis (upload/download)
- Barra inferior de transferências com Upload/Download
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDrag
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.transfer import ConflictPolicy, TransferDirection, TransferItem
from app.sftp.client import SFTPBrowser, format_size
from app.utils.paths import app_cache_dir, ensure_secure_dir

if TYPE_CHECKING:
    from app.models.server import ServerProfile
    from app.ssh.client import SSHClient
    from app.transfers.queue import TransferQueue

logger = logging.getLogger(__name__)

MIME_SFTP = "application/x-ssh-manager-linux-sftp-items"


class FileTree(QTreeWidget):
    """Árvore com drag-and-drop entre painéis — colunas redimensionáveis."""

    items_dropped = Signal(list, bool)  # paths [(path, is_dir)], from_remote
    drop_from_other = Signal(object)  # mime data from other pane

    def __init__(self, *, is_remote: bool, parent=None) -> None:
        super().__init__(parent)
        self.is_remote = is_remote
        self.setObjectName("sftpTree")
        self.setHeaderLabels(["Nome", "Tamanho", "Tipo", "Modificado", "Atributos"])
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setIndentation(8)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)

        # Fonte densa: mais linhas cabem na tela
        font = self.font()
        font.setPointSize(10)
        font.setFamilies(["Inter", "Segoe UI", "Ubuntu", "Noto Sans", "Sans Serif"])
        self.setFont(font)
        header_font = self.header().font()
        header_font.setPointSize(9)
        header_font.setBold(True)
        self.header().setFont(header_font)
        self.header().setFixedHeight(22)

        # Linhas bem compactas
        self.setStyleSheet(
            """
            QTreeWidget#sftpTree {
                font-size: 10px;
                padding: 0px;
            }
            QTreeWidget#sftpTree::item {
                padding: 1px 4px;
                min-height: 18px;
                border-radius: 3px;
            }
            QHeaderView::section {
                padding: 3px 6px;
                font-size: 9px;
                min-height: 20px;
            }
            """
        )

        # Colunas redimensionáveis pelo usuário (arrastar bordas do cabeçalho)
        hdr = self.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionsMovable(True)
        hdr.setMinimumSectionSize(40)
        hdr.setDefaultSectionSize(72)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Nome ocupa o resto
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        # Nome flexível; resto compacto — Atributos oculto por padrão (mais espaço)
        self.setColumnWidth(0, 240)   # Nome (stretch)
        self.setColumnWidth(1, 64)    # Tamanho
        self.setColumnWidth(2, 56)    # Tipo
        self.setColumnWidth(3, 108)   # Modificado
        self.setColumnWidth(4, 72)    # Atributos
        self.setColumnHidden(4, True)
        # Clique duplo no divisor = auto-ajuste da coluna
        hdr.sectionDoubleClicked.connect(self._auto_fit_column)

    def _auto_fit_column(self, index: int) -> None:
        self.resizeColumnToContents(index)
        # Nome com um mínimo confortável
        if index == 0 and self.columnWidth(0) < 160:
            self.setColumnWidth(0, 160)

    def selected_entries(self) -> list[tuple[str, bool]]:
        out: list[tuple[str, bool]] = []
        for item in self.selectedItems():
            path = item.data(0, Qt.ItemDataRole.UserRole)
            is_dir = item.data(0, Qt.ItemDataRole.UserRole + 1)
            if path:
                out.append((str(path), bool(is_dir)))
        return out

    def startDrag(self, supportedActions) -> None:  # noqa: N802
        entries = self.selected_entries()
        if not entries:
            return
        mime = QMimeData()
        payload = "\n".join(
            f"{'D' if d else 'F'}:{p}" for p, d in entries
        )
        mime.setData(MIME_SFTP, payload.encode("utf-8"))
        mime.setText(payload)
        # Também URLs locais para integração com o SO
        if not self.is_remote:
            urls = [QUrl.fromLocalFile(p) for p, _ in entries]
            mime.setUrls(urls)
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(MIME_SFTP) or event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(MIME_SFTP) or event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        mime = event.mimeData()
        # Drop de arquivos do sistema no painel remoto ou local
        if mime.hasUrls() and not mime.hasFormat(MIME_SFTP):
            paths = []
            for url in mime.urls():
                if url.isLocalFile():
                    p = url.toLocalFile()
                    paths.append((p, Path(p).is_dir()))
            if paths:
                # URLs locais caindo em qualquer painel
                self.drop_from_other.emit(
                    {"source": "system", "paths": paths, "target_remote": self.is_remote}
                )
                event.acceptProposedAction()
                return

        if not mime.hasFormat(MIME_SFTP):
            event.ignore()
            return

        # Evitar drop no mesmo painel (origem)
        src = event.source()
        if src is self:
            event.ignore()
            return

        raw = bytes(mime.data(MIME_SFTP)).decode("utf-8", errors="replace")
        entries: list[tuple[str, bool]] = []
        for line in raw.splitlines():
            if ":" not in line:
                continue
            kind, path = line.split(":", 1)
            entries.append((path, kind == "D"))
        if not entries:
            event.ignore()
            return

        from_remote = bool(getattr(src, "is_remote", False)) if src else False
        self.drop_from_other.emit(
            {
                "source": "pane",
                "paths": entries,
                "from_remote": from_remote,
                "target_remote": self.is_remote,
            }
        )
        event.acceptProposedAction()


class FilePane(QWidget):
    """Um painel estilo Bitvise: título, nav, toolbar, lista."""

    path_changed = Signal(str)
    refresh_requested = Signal()
    home_requested = Signal()
    activated = Signal(str, bool)
    selection_changed = Signal()
    drop_received = Signal(object)
    request_upload = Signal()
    request_download = Signal()
    action_mkdir = Signal()
    action_newfile = Signal()
    action_rename = Signal()
    action_delete = Signal()
    action_chmod = Signal()
    action_edit = Signal()

    def __init__(self, title: str, *, is_remote: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.is_remote = is_remote
        self.current_path = ""
        self.home_path = str(Path.home()) if not is_remote else ""
        self._history: list[str] = []
        self._hist_idx = -1
        self._navigating_history = False
        self._build_ui(title)

    def _tool_btn(self, text: str, tip: str) -> QToolButton:
        b = QToolButton()
        b.setText(text)
        b.setToolTip(tip)
        b.setAutoRaise(True)
        b.setFixedSize(26, 24)
        b.setStyleSheet("font-size: 11px;")
        return b

    def _build_ui(self, title: str) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 2)
        root.setSpacing(2)

        # Título compacto
        head = QHBoxLayout()
        head.setContentsMargins(2, 0, 2, 0)
        self.title_lbl = QLabel(title)
        self.title_lbl.setObjectName("titleLabel")
        self.title_lbl.setStyleSheet("font-size: 12px; font-weight: 700;")
        self.count_lbl = QLabel("")
        self.count_lbl.setObjectName("mutedLabel")
        self.count_lbl.setStyleSheet("font-size: 10px;")
        head.addWidget(self.title_lbl)
        head.addStretch()
        head.addWidget(self.count_lbl)
        root.addLayout(head)

        # Navegação
        nav = QHBoxLayout()
        nav.setSpacing(2)
        nav.setContentsMargins(0, 0, 0, 0)
        self.btn_back = self._tool_btn("◀", "Voltar")
        self.btn_fwd = self._tool_btn("▶", "Avançar")
        self.btn_up = self._tool_btn("⬆", "Subir uma pasta")
        self.btn_home = self._tool_btn("🏠", "Pasta inicial do usuário (home)")
        self.btn_refresh = self._tool_btn("↻", "Atualizar lista")
        self.btn_browse = self._tool_btn("…", "Procurar pasta")
        self.btn_browse.setVisible(not self.is_remote)

        self.address = QLineEdit()
        self.address.setPlaceholderText("Caminho…")
        self.address.setMinimumHeight(26)
        self.address.setMaximumHeight(28)
        self.address.setStyleSheet("font-size: 11px; padding: 3px 8px;")
        self.address.returnPressed.connect(self._on_address)

        for b in (
            self.btn_back,
            self.btn_fwd,
            self.btn_up,
            self.btn_home,
            self.btn_refresh,
        ):
            nav.addWidget(b)
        nav.addWidget(self.address, 1)
        if not self.is_remote:
            nav.addWidget(self.btn_browse)
        root.addLayout(nav)

        # Lista (ações ficam no menu de contexto e nos botões Up/Down do centro)
        self.tree = FileTree(is_remote=self.is_remote)
        self.tree.itemDoubleClicked.connect(self._on_double)
        self.tree.itemSelectionChanged.connect(self.selection_changed.emit)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.drop_from_other.connect(self.drop_received.emit)
        root.addWidget(self.tree, 1)

        # Status do painel
        self.status = QLabel("Pronto")
        self.status.setObjectName("mutedLabel")
        root.addWidget(self.status)

        # Conexões nav
        self.btn_back.clicked.connect(lambda: self._hist_nav(-1))
        self.btn_fwd.clicked.connect(lambda: self._hist_nav(1))
        self.btn_up.clicked.connect(self._go_up)
        self.btn_home.clicked.connect(self._go_home)
        self.btn_refresh.clicked.connect(self._refresh)
        self.btn_browse.clicked.connect(self._browse)
    def _on_address(self) -> None:
        text = self.address.text().strip()
        if text:
            self.path_changed.emit(text)

    def _on_double(self, item: QTreeWidgetItem, _col: int) -> None:
        path = item.data(0, Qt.ItemDataRole.UserRole)
        is_dir = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if path is not None:
            self.activated.emit(str(path), bool(is_dir))

    def _go_up(self) -> None:
        path = self.current_path or self.address.text().strip()
        if not path:
            return
        parent = str(Path(path).parent)
        if parent == path and parent not in ("/",):
            return
        self.path_changed.emit(parent if parent else "/")

    def _go_home(self) -> None:
        """Pede ao painel pai ir para a home (local ou remota)."""
        self.home_requested.emit()

    def _refresh(self) -> None:
        """Pede ao painel pai atualizar a lista atual."""
        self.refresh_requested.emit()

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            "Selecionar pasta local",
            self.current_path or self.home_path or str(Path.home()),
        )
        if path:
            self.path_changed.emit(path)

    def _hist_nav(self, delta: int) -> None:
        ni = self._hist_idx + delta
        if 0 <= ni < len(self._history):
            self._hist_idx = ni
            self._navigating_history = True
            self.path_changed.emit(self._history[ni])

    def push_history(self, path: str) -> None:
        if self._hist_idx >= 0 and self._history and self._history[self._hist_idx] == path:
            return
        self._history = self._history[: self._hist_idx + 1]
        self._history.append(path)
        self._hist_idx = len(self._history) - 1
        if len(self._history) > 50:
            self._history = self._history[-50:]
            self._hist_idx = len(self._history) - 1

    def set_path(self, path: str, *, track: bool = True) -> None:
        self.current_path = path
        self.address.setText(path)
        if self._navigating_history:
            self._navigating_history = False
            return
        if track:
            self.push_history(path)

    def clear(self) -> None:
        self.tree.clear()

    def add_file_item(
        self,
        name: str,
        path: str,
        *,
        is_dir: bool,
        size: int = 0,
        type_label: str = "",
        perms: str = "",
        mtime: str = "",
    ) -> None:
        icon = "📁  " if is_dir else "📄  "
        display = f"{icon}{name}"
        item = QTreeWidgetItem(
            [
                display,
                "—" if is_dir else format_size(size),
                type_label or ("Pasta" if is_dir else "Arquivo"),
                mtime,
                perms,
            ]
        )
        item.setData(0, Qt.ItemDataRole.UserRole, path)
        item.setData(0, Qt.ItemDataRole.UserRole + 1, is_dir)
        item.setData(0, Qt.ItemDataRole.UserRole + 2, name)
        # Tooltip com nome completo (se a coluna estiver estreita)
        item.setToolTip(0, f"{name}\n{path}")
        item.setToolTip(1, format_size(size) if not is_dir else "pasta")
        font = item.font(0)
        font.setPointSize(11)
        if is_dir:
            font.setBold(True)
            item.setForeground(0, QColor("#5eead4"))
        item.setFont(0, font)
        muted = QColor("#8b93a7")
        for col in (1, 2, 3, 4):
            item.setForeground(col, muted)
            f2 = item.font(col)
            f2.setPointSize(10)
            item.setFont(col, f2)
        self.tree.addTopLevelItem(item)

    def set_count(self, n: int) -> None:
        self.count_lbl.setText(f"{n} item(ns)")

    def selected_paths(self) -> list[tuple[str, bool]]:
        return self.tree.selected_entries()

    def _context_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)
        if self.is_remote:
            menu.addAction("⬇ Download", self.request_download.emit)
            menu.addAction("Editar remoto", lambda: self.action_edit.emit())
            menu.addAction("chmod", lambda: self.action_chmod.emit())
        else:
            menu.addAction("⬆ Upload", self.request_upload.emit)
        menu.addSeparator()
        menu.addAction("Nova pasta", lambda: self.action_mkdir.emit())
        menu.addAction("Novo arquivo", lambda: self.action_newfile.emit())
        menu.addAction("Renomear", lambda: self.action_rename.emit())
        menu.addAction("Excluir", lambda: self.action_delete.emit())
        menu.addSeparator()
        menu.addAction("Copiar caminho", self._copy_path)
        menu.addAction("Atualizar", lambda: self.refresh_requested.emit())
        menu.addAction("Home", lambda: self.home_requested.emit())
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _copy_path(self) -> None:
        sel = self.selected_paths()
        if sel:
            QApplication.clipboard().setText(sel[0][0])


class SFTPPanel(QWidget):
    """Interface SFTP dual-pane semelhante ao Bitvise."""

    def __init__(
        self,
        profile: "ServerProfile",
        client: Optional["SSHClient"] = None,
        transfer_queue: Optional["TransferQueue"] = None,
        *,
        show_hidden: bool = False,
        conflict_policy: ConflictPolicy = ConflictPolicy.ASK,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.profile = profile
        self.client = client
        self.transfer_queue = transfer_queue
        self.show_hidden = show_hidden
        self.conflict_policy = conflict_policy
        self.browser: Optional[SFTPBrowser] = None
        self._remote_home: str = ""
        self._local_home: str = str(Path.home())
        self._build_ui()
        self.local_pane.home_path = self._local_home
        local = profile.local_path or self._local_home
        self._load_local(local)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        # Barra superior global (compacta)
        top = QHBoxLayout()
        top.setContentsMargins(2, 0, 2, 0)
        self.btn_hidden = QPushButton("Ocultos")
        self.btn_hidden.setCheckable(True)
        self.btn_hidden.setChecked(self.show_hidden)
        self.btn_hidden.setToolTip("Mostrar/ocultar arquivos ocultos")
        self.btn_hidden.toggled.connect(self._toggle_hidden)
        self.conn_lbl = QLabel("SFTP: não conectado")
        self.conn_lbl.setObjectName("mutedLabel")
        tip = QLabel("Arraste entre painéis para transferir")
        tip.setObjectName("mutedLabel")
        top.addWidget(self.conn_lbl)
        top.addStretch()
        top.addWidget(tip)
        top.addWidget(self.btn_hidden)
        layout.addLayout(top)

        # Splitter principal local | remoto
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.local_pane = FilePane("Arquivos locais", is_remote=False)
        self.remote_pane = FilePane("Arquivos remotos", is_remote=True)

        # Coluna central de transfer (mais estreita → mais lista)
        mid = QFrame()
        mid.setFixedWidth(48)
        mid_l = QVBoxLayout(mid)
        mid_l.setContentsMargins(2, 24, 2, 4)
        mid_l.setSpacing(8)
        mid_l.addStretch()
        self.btn_to_remote = QPushButton("↑")
        self.btn_to_remote.setToolTip("Upload (local → remoto)")
        self.btn_to_remote.setObjectName("primaryBtn")
        self.btn_to_remote.setFixedSize(36, 36)
        self.btn_to_remote.setStyleSheet(
            "QPushButton#primaryBtn { font-size: 16px; font-weight: 800; border-radius: 10px; }"
        )
        self.btn_to_local = QPushButton("↓")
        self.btn_to_local.setToolTip("Download (remoto → local)")
        self.btn_to_local.setFixedSize(36, 36)
        self.btn_to_local.setStyleSheet(
            "QPushButton { font-size: 16px; font-weight: 800; border-radius: 10px; }"
        )
        mid_l.addWidget(self.btn_to_remote, 0, Qt.AlignmentFlag.AlignHCenter)
        mid_l.addWidget(self.btn_to_local, 0, Qt.AlignmentFlag.AlignHCenter)
        mid_l.addStretch()

        splitter.addWidget(self.local_pane)
        splitter.addWidget(mid)
        splitter.addWidget(self.remote_pane)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([520, 48, 520])
        layout.addWidget(splitter, 1)

        # Conflito na mesma linha, bem baixo
        conflict_row = QHBoxLayout()
        conflict_row.setContentsMargins(2, 0, 2, 0)
        conflict_row.setSpacing(6)
        cl = QLabel("Se existir:")
        cl.setObjectName("mutedLabel")
        conflict_row.addWidget(cl)
        self.conflict = QComboBox()
        self.conflict.setMaximumWidth(140)
        for val, label in (
            ("overwrite", "Sobrescrever"),
            ("skip", "Ignorar"),
            ("rename", "Renomear auto"),
            ("ask", "Perguntar"),
        ):
            self.conflict.addItem(label, val)
        try:
            idx = self.conflict.findData(self.conflict_policy.value)
            if idx >= 0:
                self.conflict.setCurrentIndex(idx)
        except Exception:  # noqa: BLE001
            pass
        conflict_row.addWidget(self.conflict)
        conflict_row.addStretch()
        # Atalho para reexibir coluna Atributos
        self.btn_attrs = QPushButton("Atributos")
        self.btn_attrs.setCheckable(True)
        self.btn_attrs.setToolTip("Mostrar coluna de atributos (perms)")
        self.btn_attrs.toggled.connect(self._toggle_attrs_column)
        conflict_row.addWidget(self.btn_attrs)
        layout.addLayout(conflict_row)

        # Wire local
        self.local_pane.path_changed.connect(self._load_local)
        self.local_pane.home_requested.connect(self._local_home_click)
        self.local_pane.refresh_requested.connect(self._local_refresh)
        self.local_pane.activated.connect(self._local_activated)
        self.local_pane.request_upload.connect(self._upload)
        self.local_pane.drop_received.connect(self._on_drop)
        self.local_pane.action_mkdir.connect(lambda: self._mkdir(remote=False))
        self.local_pane.action_newfile.connect(lambda: self._newfile(remote=False))
        self.local_pane.action_rename.connect(lambda: self._rename(remote=False))
        self.local_pane.action_delete.connect(lambda: self._delete(remote=False))

        # Wire remote
        self.remote_pane.path_changed.connect(self._remote_goto)
        self.remote_pane.home_requested.connect(self._remote_home_click)
        self.remote_pane.refresh_requested.connect(self._remote_refresh)
        self.remote_pane.activated.connect(self._remote_activated)
        self.remote_pane.request_download.connect(self._download)
        self.remote_pane.drop_received.connect(self._on_drop)
        self.remote_pane.action_mkdir.connect(lambda: self._mkdir(remote=True))
        self.remote_pane.action_newfile.connect(lambda: self._newfile(remote=True))
        self.remote_pane.action_rename.connect(lambda: self._rename(remote=True))
        self.remote_pane.action_delete.connect(lambda: self._delete(remote=True))
        self.remote_pane.action_chmod.connect(self._chmod)
        self.remote_pane.action_edit.connect(self._edit_remote)

        self.btn_to_remote.clicked.connect(self._upload)
        self.btn_to_local.clicked.connect(self._download)

    # ── Conexão ─────────────────────────────────────────────

    def set_client(self, client: Optional["SSHClient"]) -> None:
        self.client = client
        if client and client.is_connected:
            from app.workers.async_bridge import schedule

            schedule(self._init_sftp(), name="sftp-init")
        else:
            self.browser = None
            self.conn_lbl.setText("SFTP: não conectado")
            self.remote_pane.status.setText("Desconectado")

    async def _init_sftp(self) -> None:
        try:
            sftp = await self.client.open_sftp()  # type: ignore[union-attr]
            self.browser = SFTPBrowser(sftp, username=self.profile.username or "")
            # getcwd() logo após o login SFTP = home real (ex.: /root)
            self._remote_home = await self.browser.resolve_home()
            self.remote_pane.home_path = self._remote_home

            path = (self.profile.remote_path or "~").strip()
            if path in ("~", "$HOME", ".", ""):
                path = self._remote_home
            else:
                try:
                    await self.browser.chdir(path)
                    path = self.browser.cwd
                except Exception:  # noqa: BLE001
                    path = self._remote_home
            # Sempre entrar no home resolvido e listar
            await self._load_remote(path, force=True)
            self.conn_lbl.setText(
                f"SFTP — {self.profile.username}@{self.profile.display_host()} · {self._remote_home}"
            )
            self.remote_pane.status.setText(f"Home: {self._remote_home}")
        except Exception as exc:  # noqa: BLE001
            self.conn_lbl.setText(f"SFTP: erro — {exc}")
            self.remote_pane.status.setText(str(exc))
            QMessageBox.warning(self, "SFTP", str(exc))

    def _toggle_hidden(self, checked: bool) -> None:
        self.show_hidden = checked
        self._local_refresh()
        self._remote_refresh()

    def _toggle_attrs_column(self, checked: bool) -> None:
        """Mostra/esconde coluna Atributos nos dois painéis (libera espaço na lista)."""
        self.local_pane.tree.setColumnHidden(4, not checked)
        self.remote_pane.tree.setColumnHidden(4, not checked)

    def _policy(self) -> ConflictPolicy:
        try:
            return ConflictPolicy(self.conflict.currentData())
        except ValueError:
            return ConflictPolicy.OVERWRITE

    # ── Local ───────────────────────────────────────────────

    def _local_home_click(self) -> None:
        self.local_pane.home_path = self._local_home
        self._load_local(self._local_home)

    def _local_refresh(self) -> None:
        path = (
            self.local_pane.current_path
            or self.local_pane.address.text().strip()
            or self._local_home
        )
        self._load_local(path)

    def _load_local(self, path: str) -> None:
        if not path:
            path = self._local_home
        # expandir ~
        if path.startswith("~"):
            path = str(Path(path).expanduser())
        try:
            p = Path(path).expanduser().resolve()
        except Exception:  # noqa: BLE001
            p = Path(path).expanduser()
        if not p.is_dir():
            self.local_pane.status.setText(f"Diretório inválido: {path}")
            return
        self.local_pane.clear()
        prev = self.local_pane.current_path
        self.local_pane.set_path(str(p), track=(str(p) != prev))
        try:
            entries = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        except PermissionError as exc:
            self.local_pane.status.setText(f"Permissão negada: {exc}")
            return
        n = 0
        for entry in entries:
            if not self.show_hidden and entry.name.startswith("."):
                continue
            try:
                st = entry.lstat()
                is_dir = entry.is_dir()
                mtime = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
                self.local_pane.add_file_item(
                    entry.name,
                    str(entry),
                    is_dir=is_dir,
                    size=st.st_size,
                    type_label="Pasta" if is_dir else (entry.suffix.lstrip(".").upper() or "Arquivo"),
                    perms=oct(st.st_mode)[-4:],
                    mtime=mtime,
                )
                n += 1
            except OSError:
                continue
        self.local_pane.set_count(n)
        self.local_pane.status.setText(str(p))

    def _local_activated(self, path: str, is_dir: bool) -> None:
        if is_dir:
            self._load_local(path)

    # ── Remote ──────────────────────────────────────────────

    def _remote_home_click(self) -> None:
        """Garante home remota resolvida e navega até ela."""
        if not self.browser:
            self.remote_pane.status.setText("SFTP não conectado")
            return
        from app.workers.async_bridge import schedule

        async def _go() -> None:
            assert self.browser is not None
            home = self._remote_home or await self.browser.resolve_home()
            self._remote_home = home
            self.remote_pane.home_path = home
            await self._load_remote(home)

        schedule(_go(), name="sftp-home")

    def _remote_refresh(self) -> None:
        if not self.browser:
            self.remote_pane.status.setText("SFTP não conectado")
            return
        path = (
            self.remote_pane.current_path
            or self.remote_pane.address.text().strip()
            or self.browser.cwd
            or self._remote_home
        )
        from app.workers.async_bridge import schedule

        schedule(self._load_remote(path, force=True), name="sftp-refresh")

    def _refresh_remote(self) -> None:
        self._remote_refresh()

    def _remote_goto(self, path: str) -> None:
        from app.workers.async_bridge import schedule

        # Home explícito
        if path in ("~", "$HOME"):
            self._remote_home_click()
            return
        schedule(self._load_remote(path), name="sftp-goto")

    async def _load_remote(self, path: str, *, force: bool = False) -> None:
        if not self.browser:
            self.remote_pane.status.setText("Não conectado")
            return
        try:
            raw = (path or "").strip()
            # Normalizar home / caminhos quebrados /root/~
            if raw in ("~", "$HOME", "") or raw.endswith("/~") or raw.endswith("~") and "/" in raw[:-1]:
                path = self._remote_home or await self.browser.resolve_home()
                self._remote_home = path
                self.remote_pane.home_path = path
            else:
                path = raw

            # Entrar no diretório
            try:
                if force or path != self.browser.cwd:
                    await self.browser.chdir(path)
            except Exception:
                # fallback: home se o caminho falhar
                home = self._remote_home or await self.browser.resolve_home()
                await self.browser.chdir(home)
                path = home
                self._remote_home = home
                self.remote_pane.home_path = home

            # Listar SEMPRE pelo cwd absoluto atual (evita readdir com path inválido)
            cwd = self.browser.cwd or path
            files = await self.browser.listdir(cwd, show_hidden=self.show_hidden)
            self.remote_pane.clear()
            prev = self.remote_pane.current_path
            self.remote_pane.set_path(cwd, track=(cwd != prev))
            for f in files:
                self.remote_pane.add_file_item(
                    f.name,
                    f.path,
                    is_dir=f.is_dir,
                    size=f.size,
                    type_label=f.type_label,
                    perms=f.permissions,
                    mtime=f.mtime_str,
                )
            self.remote_pane.set_count(len(files))
            self.remote_pane.status.setText(cwd)
            self.conn_lbl.setText(
                f"SFTP — {self.profile.username}@{self.profile.display_host()}  ·  {cwd}"
            )
        except Exception as exc:  # noqa: BLE001
            self.remote_pane.status.setText(str(exc))
            QMessageBox.warning(self, "SFTP", str(exc))

    def _remote_activated(self, path: str, is_dir: bool) -> None:
        if is_dir:
            self._remote_goto(path)

    # ── Drag & drop / transfer ──────────────────────────────

    def _on_drop(self, info: dict) -> None:
        """
        info: {
          source: 'pane'|'system',
          paths: [(path, is_dir), ...],
          from_remote?: bool,
          target_remote: bool,
        }
        """
        paths = info.get("paths") or []
        if not paths:
            return
        target_remote = bool(info.get("target_remote"))
        from_remote = bool(info.get("from_remote", False))

        if info.get("source") == "system":
            # Arquivos do SO → se alvo remoto = upload; se local = copiar local
            if target_remote:
                self._enqueue_upload(paths)
            else:
                # copiar para pasta local atual
                dest_dir = self.local_pane.current_path
                for src, is_dir in paths:
                    try:
                        dest = Path(dest_dir) / Path(src).name
                        if is_dir:
                            shutil.copytree(src, dest, dirs_exist_ok=True)
                        else:
                            shutil.copy2(src, dest)
                    except Exception as exc:  # noqa: BLE001
                        QMessageBox.warning(self, "Cópia local", str(exc))
                self._load_local(dest_dir)
            return

        # Entre painéis
        if from_remote and not target_remote:
            # remoto → local = download
            self._enqueue_download(paths)
        elif not from_remote and target_remote:
            # local → remoto = upload
            self._enqueue_upload(paths)
        # mesmo lado: ignorar

    def _upload(self) -> None:
        sel = self.local_pane.selected_paths()
        if not sel:
            QMessageBox.information(
                self,
                "Upload",
                "Selecione arquivos no painel local\nou arraste-os para o painel remoto.",
            )
            return
        self._enqueue_upload(sel)

    def _download(self) -> None:
        sel = self.remote_pane.selected_paths()
        if not sel:
            QMessageBox.information(
                self,
                "Download",
                "Selecione arquivos no painel remoto\nou arraste-os para o painel local.",
            )
            return
        self._enqueue_download(sel)

    def _enqueue_upload(self, entries: list[tuple[str, bool]]) -> None:
        if not self.transfer_queue or not self.profile.id:
            QMessageBox.information(self, "Upload", "Conecte-se ao servidor primeiro.")
            return
        if not self.browser:
            QMessageBox.information(self, "Upload", "SFTP não está conectado.")
            return
        remote_dir = self.remote_pane.current_path or "."
        policy = self._policy()
        from app.workers.async_bridge import schedule

        async def _do() -> None:
            for path, is_dir in entries:
                remote = str(Path(remote_dir) / Path(path).name)
                item = TransferItem(
                    server_id=self.profile.id,
                    direction=TransferDirection.UPLOAD,
                    local_path=path,
                    remote_path=remote,
                    is_directory=is_dir,
                    conflict_policy=policy,
                )
                await self.transfer_queue.enqueue(item)  # type: ignore[union-attr]
            self.remote_pane.status.setText(f"Upload enfileirado: {len(entries)} item(ns)")
            # atualizar remoto após um tempo
            await asyncio_sleep(0.5)

        schedule(_do(), name="sftp-upload")

    def _enqueue_download(self, entries: list[tuple[str, bool]]) -> None:
        if not self.transfer_queue or not self.profile.id:
            QMessageBox.information(self, "Download", "Conecte-se ao servidor primeiro.")
            return
        local_dir = self.local_pane.current_path or str(Path.home())
        policy = self._policy()
        from app.workers.async_bridge import schedule

        async def _do() -> None:
            for path, is_dir in entries:
                local = str(Path(local_dir) / Path(path).name)
                item = TransferItem(
                    server_id=self.profile.id,
                    direction=TransferDirection.DOWNLOAD,
                    local_path=local,
                    remote_path=path,
                    is_directory=is_dir,
                    conflict_policy=policy,
                )
                await self.transfer_queue.enqueue(item)  # type: ignore[union-attr]
            self.local_pane.status.setText(f"Download enfileirado: {len(entries)} item(ns)")

        schedule(_do(), name="sftp-download")

    # ── Operações de arquivo ────────────────────────────────

    def _mkdir(self, *, remote: bool) -> None:
        name, ok = QInputDialog.getText(self, "Nova pasta", "Nome da pasta:")
        if not ok or not name.strip():
            return
        name = name.strip()
        if remote:
            if not self.browser:
                return
            path = str(Path(self.remote_pane.current_path or ".") / name)
            from app.workers.async_bridge import schedule

            async def _do() -> None:
                await self.browser.mkdir(path)  # type: ignore[union-attr]
                await self._load_remote(self.remote_pane.current_path)

            schedule(_do(), name="sftp-mkdir")
        else:
            path = Path(self.local_pane.current_path) / name
            path.mkdir(exist_ok=True)
            self._load_local(self.local_pane.current_path)

    def _newfile(self, *, remote: bool) -> None:
        name, ok = QInputDialog.getText(self, "Novo arquivo", "Nome do arquivo:")
        if not ok or not name.strip():
            return
        name = name.strip()
        if remote:
            if not self.browser:
                return
            path = str(Path(self.remote_pane.current_path or ".") / name)
            from app.workers.async_bridge import schedule

            async def _do() -> None:
                await self.browser.create_empty_file(path)  # type: ignore[union-attr]
                await self._load_remote(self.remote_pane.current_path)

            schedule(_do(), name="sftp-newfile")
        else:
            path = Path(self.local_pane.current_path) / name
            path.touch()
            self._load_local(self.local_pane.current_path)

    def _delete(self, *, remote: bool) -> None:
        sel = self.remote_pane.selected_paths() if remote else self.local_pane.selected_paths()
        if not sel:
            return
        names = ", ".join(Path(p).name for p, _ in sel[:5])
        reply = QMessageBox.question(
            self,
            "Excluir",
            f"Excluir {len(sel)} item(ns)?\n{names}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if remote and self.browser:
            from app.workers.async_bridge import schedule

            async def _do() -> None:
                for path, is_dir in sel:
                    await self.browser.remove(path, is_dir=is_dir)  # type: ignore[union-attr]
                await self._load_remote(self.remote_pane.current_path)

            schedule(_do(), name="sftp-del")
        else:
            for path, is_dir in sel:
                p = Path(path)
                if is_dir:
                    shutil.rmtree(p)
                else:
                    p.unlink()
            self._load_local(self.local_pane.current_path)

    def _rename(self, *, remote: bool) -> None:
        sel = self.remote_pane.selected_paths() if remote else self.local_pane.selected_paths()
        if not sel:
            return
        old_path, _ = sel[0]
        name, ok = QInputDialog.getText(
            self, "Renomear", "Novo nome:", text=Path(old_path).name
        )
        if not ok or not name.strip():
            return
        new_path = str(Path(old_path).parent / name.strip())
        if remote and self.browser:
            from app.workers.async_bridge import schedule

            async def _do() -> None:
                await self.browser.rename(old_path, new_path)  # type: ignore[union-attr]
                await self._load_remote(self.remote_pane.current_path)

            schedule(_do(), name="sftp-rename")
        else:
            Path(old_path).rename(new_path)
            self._load_local(self.local_pane.current_path)

    def _chmod(self) -> None:
        sel = self.remote_pane.selected_paths()
        if not sel or not self.browser:
            return
        mode_str, ok = QInputDialog.getText(self, "chmod", "Modo octal (ex: 755):", text="644")
        if not ok or not mode_str.strip():
            return
        try:
            mode = int(mode_str.strip(), 8)
        except ValueError:
            QMessageBox.warning(self, "chmod", "Modo inválido.")
            return
        from app.workers.async_bridge import schedule

        async def _do() -> None:
            for path, _ in sel:
                await self.browser.chmod(path, mode)  # type: ignore[union-attr]
            await self._load_remote(self.remote_pane.current_path)

        schedule(_do(), name="sftp-chmod")

    def _edit_remote(self) -> None:
        sel = self.remote_pane.selected_paths()
        if not sel or not self.browser:
            return
        path, is_dir = sel[0]
        if is_dir:
            QMessageBox.information(self, "Editar", "Selecione um arquivo.")
            return
        from app.workers.async_bridge import schedule

        schedule(self._edit_remote_async(path), name="sftp-edit")

    async def _edit_remote_async(self, remote_path: str) -> None:
        assert self.browser
        try:
            data = await self.browser.read_file(remote_path)
            attrs = await self.browser.stat(remote_path)
            mode = int(attrs.permissions or 0o644)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Editar", str(exc))
            return

        tmp_dir = ensure_secure_dir(app_cache_dir() / "editor")
        local = tmp_dir / Path(remote_path).name
        local.write_bytes(data)
        local.chmod(0o600)
        mtime_before = local.stat().st_mtime

        from app.utils.process import ProcessError, find_executable, start_process

        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
        candidates = [c for c in [editor, "kate", "gedit", "mousepad", "xdg-open", "nano"] if c]
        exe = find_executable(candidates)
        if not exe:
            QMessageBox.warning(self, "Editar", "Nenhum editor encontrado.")
            return
        try:
            start_process([exe, str(local)])
        except ProcessError as exc:
            QMessageBox.warning(self, "Editar", str(exc))
            return

        reply = QMessageBox.question(
            self,
            "Reenviar arquivo",
            f"Após salvar o arquivo no editor, confirme para reenviar:\n{remote_path}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            try:
                local.unlink(missing_ok=True)
            except OSError:
                pass
            return
        if not local.exists():
            QMessageBox.warning(self, "Editar", "Arquivo temporário não encontrado.")
            return
        try:
            new_data = local.read_bytes()
            await self.browser.write_file(remote_path, new_data)
            if mode:
                try:
                    await self.browser.chmod(remote_path, mode)
                except Exception:  # noqa: BLE001
                    pass
            QMessageBox.information(self, "Editar", "Arquivo reenviado.")
            await self._load_remote(self.remote_pane.current_path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Editar", f"Falha ao reenviar: {exc}")
        finally:
            try:
                local.unlink(missing_ok=True)
            except OSError:
                pass

    def cleanup(self) -> None:
        self.browser = None


async def asyncio_sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)
