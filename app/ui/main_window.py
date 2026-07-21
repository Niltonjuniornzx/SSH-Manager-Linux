"""Janela principal do SSH-Manager-Linux."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QColor, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTabBar,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import __app_name__, __version__
from app.database.db import Database
from app.models.server import AuthMethod, ConnectionStatus, ServerProfile
from app.models.settings import AppSettings
from app.models.transfer import ConflictPolicy
from app.security.credentials import CredentialStore
from app.security.hostkeys import HostKeyManager, HostKeyResult
from app.security.lock import AppLock
from app.ssh.client import SSHClient
from app.ssh.session_manager import SessionManager
from app.transfers.queue import TransferQueue
from app.ui.dialogs.credential_dialog import CredentialDialog, HostKeyDialog
from app.ui.dialogs.group_dialog import GroupsDialog
from app.ui.dialogs.server_dialog import ServerDialog
from app.ui.dialogs.settings_dialog import SettingsDialog
from app.ui.panels.sftp_panel import SFTPPanel
from app.ui.panels.terminal_panel import TerminalPanel
from app.ui.panels.transfers_panel import TransfersPanel
from app.i18n import set_language, tr
from app.ui.icons import set_button_icon, status_square_icon, tab_close_icon
from app.ui.styles import apply_theme
from app.ui.title_bar import enable_custom_chrome
from app.ui.widgets import SearchBar
from app.utils.export_import import export_summary, export_to_file, import_from_file
from app.utils.sanitize import sanitize_for_log
from app.workers.async_bridge import schedule

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(
        self,
        db: Database,
        credentials: CredentialStore,
        settings: AppSettings,
    ) -> None:
        super().__init__()
        self.db = db
        self.credentials = credentials
        self.settings = settings
        self.host_keys = HostKeyManager(db)
        self.sessions = SessionManager()
        self.sftp_clients: dict[int, object] = {}
        self.transfer_queue = TransferQueue(
            max_concurrent=settings.max_concurrent_transfers,
            speed_limit_bps=settings.speed_limit_bps,
            get_sftp=self._get_sftp_for_server,
            on_status=self._on_transfer_status,
        )
        self.app_lock = AppLock(
            timeout_minutes=settings.lock_timeout_minutes,
            master_password_hash=settings.master_password_hash or None,
            on_hash_upgraded=self._on_master_hash_upgraded,
        )
        self._session_tabs: dict[int, QTabWidget] = {}  # server_id -> tabs
        self._server_items: dict[int, QTreeWidgetItem] = {}

        self.setWindowTitle(f"{__app_name__} {__version__}")
        self.setMinimumSize(900, 560)
        # Borda / título próprios (sem moldura do Plasma/GNOME)
        self._title_bar = enable_custom_chrome(self)
        self._fit_to_screen()
        self._build_ui()
        self._build_menu()
        self._build_toolbar()
        self._build_statusbar()
        apply_theme(self, settings.theme)
        self.refresh_servers()

        self._lock_timer = QTimer(self)
        self._lock_timer.timeout.connect(self._check_lock)
        self._lock_timer.start(15_000)

        # Inicia workers asyncio após o loop qasync estar rodando
        QTimer.singleShot(0, self._start_async_services)
        self._log("INFO", "Aplicação iniciada", category="app")

    def _start_async_services(self) -> None:
        schedule(self._async_bootstrap(), name="bootstrap")

    async def _async_bootstrap(self) -> None:
        self.transfer_queue.start()

    def _fit_to_screen(self) -> None:
        """Tamanho inicial e limites baseados na área útil do monitor (não ultrapassa)."""
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(1100, 700)
            return
        geo = screen.availableGeometry()
        # margem para painéis do DE (painel, dock)
        w = min(1280, max(900, geo.width() - 48))
        h = min(800, max(560, geo.height() - 48))
        self.resize(w, h)
        # centralizar
        self.move(
            geo.x() + (geo.width() - w) // 2,
            geo.y() + (geo.height() - h) // 2,
        )

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # Garante que ao maximizar não haja minimumSize forçando overflow
        self.setMinimumSize(800, 500)

    def changeEvent(self, event) -> None:  # noqa: N802
        from PySide6.QtCore import QEvent

        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            if self.isMaximized():
                # maximizado: o Qt usa availableGeometry; zerar mínimos agressivos
                self.setMinimumSize(400, 300)
            elif self.isFullScreen():
                self.setMinimumSize(0, 0)
            title_bar = getattr(self, "_title_bar", None)
            if title_bar is not None:
                title_bar.sync_max_button()

    # ── UI construction ─────────────────────────────────────

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Sidebar estilo dashboard
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(260)
        sidebar.setMaximumWidth(380)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(14, 16, 14, 12)
        side_layout.setSpacing(10)

        head = QHBoxLayout()
        self._lbl_hosts = QLabel(tr("Servidores"))
        self._lbl_hosts.setObjectName("titleLabel")
        head.addWidget(self._lbl_hosts)
        head.addStretch()
        btn_groups = QPushButton()
        btn_groups.setObjectName("iconBtn")
        btn_groups.setFixedSize(36, 32)
        set_button_icon(
            btn_groups, "groups", size=18, tooltip=tr("Gerenciar grupos…") + " (Ctrl+G)"
        )
        btn_groups.clicked.connect(self.manage_groups)
        head.addWidget(btn_groups)
        btn_add = QPushButton()
        btn_add.setFixedSize(36, 32)
        btn_add.setObjectName("primaryBtn")
        btn_add.setStyleSheet(
            "QPushButton#primaryBtn { padding: 0; border-radius: 10px; min-height: 28px; }"
        )
        set_button_icon(btn_add, "plus", size=18, tooltip=tr("Novo servidor"))
        btn_add.clicked.connect(self.new_server)
        head.addWidget(btn_add)
        side_layout.addLayout(head)

        self._lbl_hosts_sub = QLabel(tr("Organize e conecte com um clique"))
        self._lbl_hosts_sub.setObjectName("mutedLabel")
        side_layout.addWidget(self._lbl_hosts_sub)

        self.search = SearchBar(tr("Buscar hosts…"))
        self.search.textChanged.connect(self.refresh_servers)
        side_layout.addWidget(self.search)

        self.tree = QTreeWidget()
        self.tree.setObjectName("hostTree")
        self.tree.setHeaderHidden(True)
        # Lista plana: sem filhos → sem “vão/quadrado vazio” da árvore.
        # Esconder grupo = setHidden nos hosts (clique no nome).
        self.tree.setRootIsDecorated(False)
        self.tree.setItemsExpandable(False)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.setIndentation(0)
        self.tree.setUniformRowHeights(True)
        self.tree.setAnimated(False)
        # Quadradinho de status dos hosts (tamanho fixo)
        self.tree.setIconSize(QSize(14, 14))
        self._group_expanded: dict[object, bool] = {}  # gid -> aberto?
        self._group_host_items: dict[object, list] = {}  # gid -> [items host]
        self.tree.itemSelectionChanged.connect(self._on_server_selected)
        self.tree.itemClicked.connect(self._on_host_tree_clicked)
        self.tree.itemDoubleClicked.connect(self._on_host_tree_double)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._server_context_menu)
        side_layout.addWidget(self.tree, 1)

        # Server detail mini card
        detail_frame = QFrame()
        detail_frame.setObjectName("card")
        df_lay = QVBoxLayout(detail_frame)
        df_lay.setContentsMargins(12, 10, 12, 10)
        self.detail = QLabel(tr("Selecione um servidor"))
        self.detail.setObjectName("mutedLabel")
        self.detail.setWordWrap(True)
        df_lay.addWidget(self.detail)
        side_layout.addWidget(detail_frame)

        splitter.addWidget(sidebar)

        # Center: sessions + bottom transfers
        center = QWidget()
        center_layout = QVBoxLayout(center)
        # Margens menores → mais área pro terminal/SFTP
        center_layout.setContentsMargins(6, 4, 6, 4)
        center_layout.setSpacing(4)

        self.session_area = QTabWidget()
        self.session_area.setObjectName("sessionTabs")
        self.session_area.setDocumentMode(True)
        self.session_area.setTabsClosable(True)
        self.session_area.tabCloseRequested.connect(self._close_session_tab)
        self._welcome = self._welcome_widget()
        self.session_area.addTab(self._welcome, tr("Início"))
        # Início não fecha
        self._set_tab_close_button(self.session_area, 0, enabled=False)
        center_layout.addWidget(self.session_area, 1)

        # Barra de transferências mínima (só texto + progresso)
        bottom = QFrame()
        bottom.setObjectName("bottomBar")
        bottom.setMaximumHeight(30)
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(0)
        self.transfers_panel = TransfersPanel(self.transfer_queue)
        bottom_layout.addWidget(self.transfers_panel)
        center_layout.addWidget(bottom, 0)

        splitter.addWidget(center)
        splitter.setSizes([280, 1000])
        root.addWidget(splitter)

    def _welcome_widget(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(32, 32, 32, 32)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card = QFrame()
        card.setObjectName("welcomeHero")
        card.setMaximumWidth(560)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(36, 40, 36, 36)
        lay.setSpacing(12)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # logo
        icon_path = Path(__file__).resolve().parents[2] / "assets" / "icons" / "ssh-manager-linux-128.png"
        if not icon_path.is_file():
            icon_path = Path(__file__).resolve().parents[2] / "assets" / "icon.png"
        if icon_path.is_file():
            from PySide6.QtGui import QPixmap

            logo = QLabel()
            pix = QPixmap(str(icon_path)).scaled(
                96, 96,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            logo.setPixmap(pix)
            logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(logo)

        brand = QLabel(__app_name__)
        brand.setObjectName("brandLabel")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(brand)

        self._welcome_sub = QLabel(
            tr(
                "Gerencie servidores SSH e arquivos SFTP com segurança.\n"
                "Selecione um host na barra lateral ou crie um novo perfil."
            )
        )
        self._welcome_sub.setObjectName("subtitleLabel")
        self._welcome_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._welcome_sub.setWordWrap(True)
        lay.addWidget(self._welcome_sub)

        btns = QHBoxLayout()
        btns.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._btn_welcome_new = QPushButton(tr("＋  Novo servidor"))
        self._btn_welcome_new.setObjectName("primaryBtn")
        self._btn_welcome_new.clicked.connect(self.new_server)
        self._btn_welcome_conn = QPushButton(tr("⚡  Conectar"))
        self._btn_welcome_conn.clicked.connect(self.connect_selected)
        btns.addWidget(self._btn_welcome_new)
        btns.addWidget(self._btn_welcome_conn)
        lay.addSpacing(8)
        lay.addLayout(btns)

        self._welcome_tips = QLabel(
            tr(
                "Dica: clique duplo no servidor para conectar · "
                "Ctrl+T terminal · Ctrl+F SFTP"
            )
        )
        self._welcome_tips.setObjectName("mutedLabel")
        self._welcome_tips.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addSpacing(8)
        lay.addWidget(self._welcome_tips)

        outer.addWidget(card)
        return w

    def _build_menu(self) -> None:
        """Menu compacto no botão ☰ da title bar (sem barra Arquivo/Editar)."""
        from PySide6.QtWidgets import QMenu

        root = QMenu(self)
        self._app_menu = root

        def add_act(
            menu: QMenu,
            text: str,
            slot,
            shortcut: str | QKeySequence | None = None,
        ) -> QAction:
            act = QAction(text, self)
            if shortcut is not None:
                act.setShortcut(shortcut)
            act.triggered.connect(slot)
            menu.addAction(act)
            # Atalhos funcionam sem menubar visível
            self.addAction(act)
            return act

        # Limpa ações antigas (atalhos) antes de recriar o menu
        for act in list(self.actions()):
            self.removeAction(act)

        file_menu = root.addMenu(tr("Arquivo"))
        add_act(file_menu, tr("Novo servidor"), self.new_server, QKeySequence.StandardKey.New)
        add_act(file_menu, tr("Exportar configuração…"), self.export_config)
        add_act(file_menu, tr("Importar configuração…"), self.import_config)
        file_menu.addSeparator()
        add_act(file_menu, tr("Sair"), self.close, QKeySequence.StandardKey.Quit)

        edit_menu = root.addMenu(tr("Editar"))
        add_act(edit_menu, tr("Gerenciar grupos…"), self.manage_groups, "Ctrl+G")
        add_act(edit_menu, tr("Configurações…"), self.open_settings)

        server_menu = root.addMenu(tr("Servidor"))
        for text, slot, shortcut in (
            (tr("Conectar"), self.connect_selected, "Ctrl+Return"),
            (tr("Terminal"), self.open_terminal, "Ctrl+T"),
            (tr("SFTP"), self.open_sftp, "Ctrl+F"),
            (tr("Desconectar"), self.disconnect_selected, None),
        ):
            add_act(server_menu, text, slot, shortcut)

        view_menu = root.addMenu(tr("Exibir"))
        add_act(
            view_menu,
            tr("Atualizar lista"),
            self.refresh_servers,
            QKeySequence.StandardKey.Refresh,
        )

        help_menu = root.addMenu(tr("Ajuda"))
        add_act(help_menu, tr("Sobre"), self._about)

    def _build_toolbar(self) -> None:
        # Toolbar removida: mais espaço pro terminal/SFTP.
        # Ações ficam no menu (Arquivo / Servidor) e na sidebar (+ / grupos).
        return

    def _build_statusbar(self) -> None:
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.status_conn = QLabel(tr("Pronto"))
        self.status_conn.setObjectName("statusDisconnected")
        self.status_xfer = QLabel("")
        sb.addWidget(self.status_conn, 1)
        sb.addPermanentWidget(self.status_xfer)

    # ── Servers list ────────────────────────────────────────

    def refresh_servers(self, _search: str = "") -> None:
        search = self.search.text().strip()
        servers = self.db.list_servers(search)
        groups = {g.id: g for g in self.db.list_groups()}
        self.tree.clear()
        self._server_items.clear()
        self._group_host_items.clear()

        # group by group_id
        by_group: dict[Optional[int], list[ServerProfile]] = {}
        for s in servers:
            by_group.setdefault(s.group_id, []).append(s)

        # Todos os grupos (mesmo vazios) + “Sem grupo” se houver hosts órfãos
        ordered_gids = [g.id for g in self.db.list_groups()]
        for gid in list(by_group.keys()):
            if gid not in ordered_gids and gid is not None:
                ordered_gids.append(gid)
        if None in by_group and None not in ordered_gids:
            ordered_gids.append(None)

        for gid in ordered_gids:
            hosts = by_group.get(gid, [])
            # Esconde grupos vazios (e na busca os sem resultado)
            if not hosts:
                continue
            if gid and gid in groups:
                gname = groups[gid].name
            else:
                gname = tr("Sem grupo")
            count = len(hosts)

            # Nome do grupo como definido; seta no texto
            expanded = self._group_expanded.get(gid, True)

            gitem = QTreeWidgetItem([self._group_label(gname, expanded)])
            gitem.setData(0, Qt.ItemDataRole.UserRole, None)  # não é host
            gitem.setData(0, Qt.ItemDataRole.UserRole + 1, gid)  # marca grupo
            gitem.setData(0, Qt.ItemDataRole.UserRole + 2, gname)  # nome base
            gitem.setData(0, Qt.ItemDataRole.UserRole + 3, count)
            gitem.setFlags(Qt.ItemFlag.ItemIsEnabled)  # clicável, sem selecionar
            font = gitem.font(0)
            font.setBold(True)
            font.setPointSize(max(9, font.pointSize() - 1))
            gitem.setFont(0, font)
            gitem.setForeground(0, QColor("#8b93a7"))
            gitem.setToolTip(
                0,
                f"{gname} — {count} VPS · clique para mostrar/ocultar",
            )
            self.tree.addTopLevelItem(gitem)

            host_items: list = []
            for s in hosts:
                status = self.sessions.status(s.id) if s.id else ConnectionStatus.DISCONNECTED
                latency = f"{s.last_latency_ms:.0f} ms" if s.last_latency_ms else "—"
                if status == ConnectionStatus.CONNECTED:
                    status_txt = tr("conectado")
                    status_color = QColor("#34d399")
                    sq_color, sq_filled = "#34d399", True
                elif status == ConnectionStatus.CONNECTING:
                    status_txt = tr("conectando…")
                    status_color = QColor("#fbbf24")
                    sq_color, sq_filled = "#fbbf24", True
                elif status == ConnectionStatus.ERROR:
                    status_txt = tr("erro")
                    status_color = QColor("#f87171")
                    sq_color, sq_filled = "#f87171", True
                else:
                    status_txt = tr("offline")
                    status_color = QColor("#6b7280")
                    sq_color, sq_filled = "#6b7280", False

                # Item de topo (sem pai) = sem vão vazio; só o quadradinho de status
                label = f"{s.name}  ·  {status_txt}"
                item = QTreeWidgetItem([label])
                item.setData(0, Qt.ItemDataRole.UserRole, s.id)
                item.setData(0, Qt.ItemDataRole.UserRole + 1, gid)  # grupo dono
                item.setIcon(0, status_square_icon(sq_color, size=14, filled=sq_filled))
                item.setForeground(0, status_color)
                item.setToolTip(
                    0,
                    f"{s.name}\n"
                    f"{status_txt}  ·  {s.username}@{s.display_host()}\n"
                    f"{s.auth_method.label_pt}  ·  latência {latency}",
                )
                item.setSizeHint(0, QSize(0, 28))
                item.setHidden(not expanded)
                self.tree.addTopLevelItem(item)
                host_items.append(item)
                if s.id is not None:
                    self._server_items[s.id] = item

            self._group_host_items[gid] = host_items

    @staticmethod
    def _group_label(gname: str, expanded: bool) -> str:
        """Seta à esquerda + nome do grupo (como cadastrado)."""
        arrow = "▾" if expanded else "▸"
        return f"{arrow}  {gname}"

    def _is_group_item(self, item: QTreeWidgetItem) -> bool:
        """True se o item é cabeçalho de grupo (não um host)."""
        if item is None:
            return False
        # grupo: UserRole (server id) é None e tem nome em UserRole+2
        return (
            item.data(0, Qt.ItemDataRole.UserRole) is None
            and item.data(0, Qt.ItemDataRole.UserRole + 2) is not None
        )

    def _update_group_label(self, gitem: QTreeWidgetItem, *, expanded: bool) -> None:
        gname = gitem.data(0, Qt.ItemDataRole.UserRole + 2) or "Grupo"
        gitem.setText(0, self._group_label(str(gname), expanded))

    def _on_host_tree_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        if item is None:
            return
        # Clique no nome do grupo → esconde/mostra hosts (setHidden, sem árvore)
        if self._is_group_item(item):
            gid = item.data(0, Qt.ItemDataRole.UserRole + 1)
            expanded = not self._group_expanded.get(gid, True)
            self._group_expanded[gid] = expanded
            for hi in self._group_host_items.get(gid, []):
                hi.setHidden(not expanded)
            self._update_group_label(item, expanded=expanded)

    def _on_host_tree_double(self, item: QTreeWidgetItem, _col: int) -> None:
        if item is None:
            return
        if self._is_group_item(item):
            self._on_host_tree_clicked(item, 0)
            return
        self.connect_selected()

    def selected_server(self) -> Optional[ServerProfile]:
        items = self.tree.selectedItems()
        if not items:
            return None
        sid = items[0].data(0, Qt.ItemDataRole.UserRole)
        if sid is None:
            return None
        return self.db.get_server(int(sid))

    def _on_server_selected(self) -> None:
        s = self.selected_server()
        if not s:
            self.detail.setText("Selecione um servidor")
            return
        status = self.sessions.status(s.id) if s.id else ConnectionStatus.DISCONNECTED
        last = s.last_connected_at or "nunca"
        jump_line = ""
        if s.jump_host_id:
            j = self.db.get_server(s.jump_host_id)
            if j:
                jump_line = f"<br>Jump: {j.name}"
        self.detail.setText(
            f"<b>{s.name}</b><br>"
            f"{s.username}@{s.display_host()}<br>"
            f"Grupo: {s.group_name or '—'}<br>"
            f"Auth: {s.auth_method.label_pt}<br>"
            f"Status: {status.label_pt}<br>"
            f"Última conexão: {last}"
            f"{jump_line}"
        )
        self.app_lock.touch()

    def _server_context_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        menu.addAction("Conectar", self.connect_selected)
        menu.addAction("Terminal", self.open_terminal)
        menu.addAction("SFTP", self.open_sftp)
        menu.addSeparator()
        menu.addAction("Editar", self.edit_server)
        menu.addAction("Duplicar", self.duplicate_server)
        menu.addAction("Excluir", self.delete_server)
        menu.addSeparator()
        menu.addAction("Gerenciar grupos…", self.manage_groups)
        menu.addAction("Desconectar", self.disconnect_selected)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # ── CRUD servers / groups ───────────────────────────────

    def manage_groups(self) -> None:
        dlg = GroupsDialog(self.db, self)
        dlg.exec()
        if dlg.changed:
            self.refresh_servers()
            self._log("INFO", "Grupos atualizados", category="app")

    def new_server(self) -> None:
        dlg = ServerDialog(
            self,
            groups=self.db.list_groups(),
            servers=self.db.list_servers(),
        )
        if dlg.exec():
            profile = dlg.get_profile()
            if self.db.detect_jump_loop(-1, profile.jump_host_id):
                QMessageBox.warning(self, "Jump host", "Loop de jump host detectado.")
                return
            self.db.save_server(profile)
            self._store_creds_from_dialog(dlg, profile)
            self._log("INFO", f"Servidor criado: {profile.name}", category="app", server_id=profile.id)
            self.refresh_servers()

    def edit_server(self) -> None:
        s = self.selected_server()
        if not s:
            return
        dlg = ServerDialog(
            self,
            server=s,
            groups=self.db.list_groups(),
            servers=self.db.list_servers(),
        )
        if dlg.exec():
            profile = dlg.get_profile()
            if s.id and self.db.detect_jump_loop(s.id, profile.jump_host_id):
                QMessageBox.warning(self, "Jump host", "Loop de jump host detectado.")
                return
            self.db.save_server(profile)
            self._store_creds_from_dialog(dlg, profile)
            self._log("INFO", f"Servidor atualizado: {profile.name}", category="app", server_id=profile.id)
            self.refresh_servers()

    def duplicate_server(self) -> None:
        s = self.selected_server()
        if not s:
            return
        copy = ServerProfile(
            name=f"{s.name} (cópia)",
            group_id=s.group_id,
            description=s.description,
            host=s.host,
            port=s.port,
            username=s.username,
            auth_method=s.auth_method,
            private_key_path=s.private_key_path,
            remote_path=s.remote_path,
            local_path=s.local_path,
            timeout=s.timeout,
            keepalive=s.keepalive,
            terminal_encoding=s.terminal_encoding,
            color=s.color,
            auto_reconnect=s.auto_reconnect,
            jump_host_id=s.jump_host_id,
            remember_credential=s.remember_credential,
        )
        self.db.save_server(copy)
        self.refresh_servers()

    def delete_server(self) -> None:
        s = self.selected_server()
        if not s or s.id is None:
            return
        if self.settings.confirm_delete:
            reply = QMessageBox.question(
                self,
                "Excluir servidor",
                f"Excluir '{s.name}'?\nCredenciais do keyring também serão removidas.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        schedule(self._delete_server_async(s), name="del-server")

    async def _delete_server_async(self, s: ServerProfile) -> None:
        assert s.id is not None
        await self.sessions.disconnect(s.id)
        key = s.credential_service_key()
        self.credentials.delete_server_credentials(key)
        self.db.delete_server(s.id)
        if s.id in self._session_tabs:
            idx = self.session_area.indexOf(self._session_tabs[s.id])
            if idx >= 0:
                self.session_area.removeTab(idx)
            del self._session_tabs[s.id]
        self._log("INFO", f"Servidor excluído: {s.name}", category="app")
        self.refresh_servers()

    def _store_creds_from_dialog(self, dlg: ServerDialog, profile: ServerProfile) -> None:
        key = profile.credential_service_key()
        if not profile.remember_credential:
            return
        if profile.auth_method == AuthMethod.PASSWORD:
            pwd = dlg.get_password()
            if pwd:
                try:
                    self.credentials.store_server_password(key, pwd)
                except RuntimeError as exc:
                    QMessageBox.warning(self, "Keyring", str(exc))
        elif profile.auth_method == AuthMethod.KEY_PASSPHRASE:
            pp = dlg.get_passphrase()
            if pp:
                try:
                    self.credentials.store_passphrase(key, pp)
                except RuntimeError as exc:
                    QMessageBox.warning(self, "Keyring", str(exc))

    # ── Connect / disconnect ────────────────────────────────

    def connect_selected(self) -> None:
        s = self.selected_server()
        if not s or s.id is None:
            QMessageBox.information(self, "Conectar", "Selecione um servidor.")
            return
        if self.sessions.is_connected(s.id):
            self._ensure_session_tab(s)
            return
        password, passphrase = self._prompt_credentials(s)
        if password is None and passphrase is None and s.auth_method in (
            AuthMethod.PASSWORD,
            AuthMethod.KEY_PASSPHRASE,
        ):
            # user cancelled or empty
            key = s.credential_service_key()
            if s.auth_method == AuthMethod.PASSWORD:
                password = self.credentials.get_server_password(key)
            else:
                passphrase = self.credentials.get_passphrase(key)
            if s.auth_method == AuthMethod.PASSWORD and not password:
                return
            if s.auth_method == AuthMethod.KEY_PASSPHRASE and not passphrase:
                return

        self.sessions.set_status(s.id, ConnectionStatus.CONNECTING)
        self.status_conn.setText(f"Conectando a {s.name}…")
        self.refresh_servers()
        schedule(
            self._connect_async(s, password, passphrase),
            name=f"connect-{s.id}",
        )

    def _prompt_credentials(
        self, s: ServerProfile
    ) -> tuple[Optional[str], Optional[str]]:
        key = s.credential_service_key()
        password = None
        passphrase = None
        if s.auth_method == AuthMethod.PASSWORD:
            password = self.credentials.get_server_password(key) if s.remember_credential else None
            if not password:
                dlg = CredentialDialog(s, self)
                if not dlg.exec():
                    return None, None
                password = dlg.get_secret()
                if dlg.should_remember() and password:
                    try:
                        self.credentials.store_server_password(key, password)
                        s.remember_credential = True
                        self.db.save_server(s)
                    except RuntimeError as exc:
                        QMessageBox.warning(self, "Keyring", str(exc))
        elif s.auth_method == AuthMethod.KEY_PASSPHRASE:
            passphrase = self.credentials.get_passphrase(key) if s.remember_credential else None
            if not passphrase:
                dlg = CredentialDialog(s, self, title="Passphrase")
                if not dlg.exec():
                    return None, None
                passphrase = dlg.get_secret()
                if dlg.should_remember() and passphrase:
                    try:
                        self.credentials.store_passphrase(key, passphrase)
                    except RuntimeError as exc:
                        QMessageBox.warning(self, "Keyring", str(exc))
        return password, passphrase

    def _host_key_prompt_sync(self, result: HostKeyResult) -> bool:
        """Diálogo de host key — deve rodar FORA de corrotinas AsyncSSH ativas."""
        if result.is_changed:
            QMessageBox.critical(self, "Host key alterada", result.message)
            self._log(
                "ERROR",
                f"Host key alterada: {result.hostname}:{result.port}",
                category="security",
            )
            return False
        dlg = HostKeyDialog(result.message, result.fingerprint_sha256, self)
        ok = dlg.exec() == dlg.DialogCode.Accepted
        if ok:
            self.host_keys.accept(
                result.hostname,
                result.port,
                result.key_type,
                result.fingerprint_sha256,
                result.public_key_b64,
            )
            self._log(
                "INFO",
                f"Host key aceita: {result.hostname} {result.fingerprint_sha256}",
                category="security",
            )
        return ok

    async def _connect_async(
        self,
        s: ServerProfile,
        password: Optional[str],
        passphrase: Optional[str],
    ) -> None:
        assert s.id is not None

        async def _attempt() -> tuple[SSHClient, object]:
            client = SSHClient(
                profile=s,
                credentials=self.credentials,
                host_keys=self.host_keys,
                password=password,
                passphrase=passphrase,
                resolve_server=lambda sid: self.db.get_server(sid),
            )
            result = await client.connect()
            return client, result

        # Ceder o loop antes de qualquer diálogo Qt (evita reentrância AsyncSSH)
        import asyncio

        await asyncio.sleep(0)

        client, result = await _attempt()

        # Host key nova: confirma na UI e reconecta (fora do connect)
        if (
            not result.success
            and result.error_code == "host_key_unknown"
            and result.host_key_result is not None
        ):
            await asyncio.sleep(0)
            if self._host_key_prompt_sync(result.host_key_result):
                await asyncio.sleep(0)
                client, result = await _attempt()
            else:
                self.sessions.set_status(s.id, ConnectionStatus.DISCONNECTED)
                self.status_conn.setText("Host key recusada")
                self.refresh_servers()
                return

        if not result.success:
            if result.error_code == "host_key_changed" and result.host_key_result:
                await asyncio.sleep(0)
                self._host_key_prompt_sync(result.host_key_result)
            else:
                await asyncio.sleep(0)
                QMessageBox.warning(self, "Conexão", result.message)
            self.sessions.set_status(s.id, ConnectionStatus.ERROR)
            self.status_conn.setText(f"Erro: {result.message}")
            self._log(
                "ERROR",
                f"Falha ao conectar {s.name}: {result.message}",
                category="ssh",
                server_id=s.id,
            )
            self.refresh_servers()
            return

        self.sessions.set(s.id, client)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self.db.update_server_connection_meta(
            s.id, last_connected_at=now, last_latency_ms=result.latency_ms
        )
        self.status_conn.setText(
            f"Conectado a {s.name} ({result.latency_ms} ms) {result.server_version}"
        )
        self.status_conn.setObjectName("statusConnected")
        self.status_conn.style().unpolish(self.status_conn)
        self.status_conn.style().polish(self.status_conn)
        self._log(
            "INFO",
            f"Conectado: {s.name} latência={result.latency_ms}ms",
            category="ssh",
            server_id=s.id,
        )

        self._ensure_session_tab(s)
        self.refresh_servers()

    def disconnect_selected(self) -> None:
        s = self.selected_server()
        if not s or s.id is None:
            return
        schedule(self._disconnect_async(s), name=f"disconnect-{s.id}")

    async def _disconnect_async(self, s: ServerProfile) -> None:
        assert s.id is not None
        self.sftp_clients.pop(s.id, None)
        await self.sessions.disconnect(s.id)
        self.status_conn.setText(f"Desconectado de {s.name}")
        self.status_conn.setObjectName("statusDisconnected")
        self._log("INFO", f"Desconectado: {s.name}", category="ssh", server_id=s.id)
        self.refresh_servers()

    # ── Session tabs ────────────────────────────────────────

    def _ensure_session_tab(self, s: ServerProfile) -> QTabWidget:
        assert s.id is not None
        if s.id in self._session_tabs:
            tabs = self._session_tabs[s.id]
            idx = self.session_area.indexOf(tabs)
            if idx >= 0:
                self.session_area.setCurrentIndex(idx)
            return tabs

        tabs = QTabWidget()
        client = self.sessions.get(s.id)

        term = TerminalPanel(
            s,
            client,
            external_terminal=self.settings.external_terminal,
            font_family=self.settings.terminal_font,
            font_size=self.settings.terminal_font_size,
        )
        if client:
            term.set_client(client)
        tabs.addTab(term, tr("Terminal"))

        policy = ConflictPolicy.ASK
        try:
            policy = ConflictPolicy(self.settings.conflict_policy)
        except ValueError:
            pass
        sftp = SFTPPanel(
            s,
            client,
            self.transfer_queue,
            show_hidden=self.settings.show_hidden_files,
            conflict_policy=policy,
        )
        if client:
            sftp.set_client(client)
        tabs.addTab(sftp, tr("Arquivos SFTP"))

        self._session_tabs[s.id] = tabs
        idx = self.session_area.addTab(tabs, s.name)
        self._set_tab_close_button(self.session_area, idx, enabled=True)
        self.session_area.setCurrentIndex(idx)
        return tabs

    def _set_tab_close_button(self, tabs: QTabWidget, index: int, *, enabled: bool) -> None:
        """Fecha bonito: sem X no Início; nos outros, botão custom."""
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QEnterEvent

        bar = tabs.tabBar()
        if not enabled:
            bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, None)
            bar.setTabButton(index, QTabBar.ButtonPosition.LeftSide, None)
            return

        class _CloseBtn(QToolButton):
            def enterEvent(self, event: QEnterEvent) -> None:  # noqa: N802
                self.setIcon(tab_close_icon(size=14, hover=True))
                super().enterEvent(event)

            def leaveEvent(self, event) -> None:  # noqa: N802
                self.setIcon(tab_close_icon(size=14, hover=False))
                super().leaveEvent(event)

        btn = _CloseBtn(tabs)
        btn.setObjectName("tabCloseBtn")
        btn.setAutoRaise(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setIcon(tab_close_icon(size=14, hover=False))
        btn.setIconSize(QSize(14, 14))
        btn.setFixedSize(20, 20)
        btn.setToolTip("Fechar sessão")

        def _on_close() -> None:
            for i in range(tabs.count()):
                if tabs.tabBar().tabButton(i, QTabBar.ButtonPosition.RightSide) is btn:
                    tabs.tabCloseRequested.emit(i)
                    break

        btn.clicked.connect(_on_close)
        bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, btn)

    def _close_session_tab(self, index: int) -> None:
        w = self.session_area.widget(index)
        if w is None:
            return
        # Início: nunca fecha
        if w is self.session_area.widget(0) and index == 0:
            # confere se é a welcome (não está em _session_tabs)
            if w not in self._session_tabs.values():
                return
        # find server_id
        sid = None
        for k, v in self._session_tabs.items():
            if v is w:
                sid = k
                break
        if sid is None:
            # welcome / aba auxiliar — não remove Início
            if self.session_area.tabText(index) == "Início":
                return
            self.session_area.removeTab(index)
            return
        s = self.db.get_server(sid)
        if s:
            schedule(self._disconnect_async(s), name=f"close-tab-{sid}")
        # cleanup panels
        for i in range(w.count()):
            panel = w.widget(i)
            if hasattr(panel, "cleanup"):
                try:
                    panel.cleanup()
                except Exception:  # noqa: BLE001
                    pass
        del self._session_tabs[sid]
        self.session_area.removeTab(index)

    def open_terminal(self) -> None:
        s = self.selected_server()
        if not s:
            return
        if s.id and not self.sessions.is_connected(s.id):
            self.connect_selected()
        if s.id and self.sessions.is_connected(s.id):
            tabs = self._ensure_session_tab(s)
            tabs.setCurrentIndex(0)

    def open_sftp(self) -> None:
        s = self.selected_server()
        if not s:
            return
        if s.id and not self.sessions.is_connected(s.id):
            self.connect_selected()
        if s.id:
            tabs = self._ensure_session_tab(s)
            tabs.setCurrentIndex(1)
            client = self.sessions.get(s.id)
            panel = tabs.widget(1)
            if isinstance(panel, SFTPPanel) and client:
                panel.set_client(client)

    # ── Settings / import-export ────────────────────────────

    def open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self, host_keys=self.host_keys)
        if dlg.exec():
            self.settings = dlg.get_settings()
            # força dark + idioma normalizado
            self.settings.theme = "dark"
            lang = (self.settings.language or "pt_BR").strip()
            self.settings.language = "en" if str(lang).lower().startswith("en") else "pt_BR"
            self.db.save_settings(self.settings)

            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is not None:
                apply_theme(app, "dark")
            apply_theme(self, "dark")

            set_language(self.settings.language)
            self._retranslate_ui()
            self.app_lock.set_timeout(self.settings.lock_timeout_minutes)
            self.app_lock.set_master_hash(self.settings.master_password_hash or None)
            self.transfer_queue.max_concurrent = self.settings.max_concurrent_transfers
            self.transfer_queue.speed_limit_bps = self.settings.speed_limit_bps
            self._log("INFO", tr("Configurações salvas"), category="app")
            QMessageBox.information(
                self,
                tr("Configurações"),
                tr("Configurações salvas"),
            )

    def _retranslate_ui(self) -> None:
        """Atualiza textos principais após troca de idioma/tema."""
        if hasattr(self, "_lbl_hosts"):
            self._lbl_hosts.setText(tr("Servidores"))
        if hasattr(self, "_lbl_hosts_sub"):
            self._lbl_hosts_sub.setText(tr("Organize e conecte com um clique"))
        if hasattr(self, "search"):
            self.search.edit.setPlaceholderText(f"  🔍  {tr('Buscar hosts…')}")
        if hasattr(self, "detail") and self.selected_server() is None:
            self.detail.setText(tr("Selecione um servidor"))
        if hasattr(self, "_welcome_sub"):
            self._welcome_sub.setText(
                tr(
                    "Gerencie servidores SSH e arquivos SFTP com segurança.\n"
                    "Selecione um host na barra lateral ou crie um novo perfil."
                )
            )
        if hasattr(self, "_btn_welcome_new"):
            self._btn_welcome_new.setText(tr("＋  Novo servidor"))
        if hasattr(self, "_btn_welcome_conn"):
            self._btn_welcome_conn.setText(tr("⚡  Conectar"))
        if hasattr(self, "_welcome_tips"):
            self._welcome_tips.setText(
                tr(
                    "Dica: clique duplo no servidor para conectar · "
                    "Ctrl+T terminal · Ctrl+F SFTP"
                )
            )
        # Aba Início
        if self.session_area.count() > 0:
            self.session_area.setTabText(0, tr("Início"))
        tb = getattr(self, "_title_bar", None)
        if tb is not None and hasattr(tb, "btn_menu"):
            tb.btn_menu.setToolTip(tr("Menu (Arquivo, Servidor, …)"))
        self._build_menu()
        self.refresh_servers()

    def export_config(self) -> None:
        data = self.db.export_config(include_key_paths=False)
        summary = export_summary(data)
        reply = QMessageBox.information(
            self,
            "Exportar configuração",
            summary + "\nContinuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar",
            str(Path.home() / "nzxs-export.json"),
            "JSON (*.json);;Backup criptografado (*.nzxs)",
        )
        if not path:
            return
        encrypt_pw = None
        if path.endswith(".nzxs"):
            encrypt_pw, ok = QInputDialog.getText(
                self, "Senha do backup", "Senha para criptografar o backup:"
            )
            if not ok or not encrypt_pw:
                return
        try:
            info = export_to_file(
                self.db, Path(path), encrypt_password=encrypt_pw or None
            )
            QMessageBox.information(
                self,
                "Exportar",
                f"Exportado para {info['path']}\n"
                f"Servidores: {info['servers']}\n"
                f"Credenciais: não incluídas",
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Exportar", str(exc))

    def import_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Importar",
            str(Path.home()),
            "JSON/Backup (*.json *.nzxs);;All (*)",
        )
        if not path:
            return
        encrypt_pw = None
        if path.endswith(".nzxs"):
            encrypt_pw, ok = QInputDialog.getText(
                self, "Senha do backup", "Senha do backup criptografado:"
            )
            if not ok:
                return
        try:
            stats = import_from_file(
                self.db, Path(path), encrypt_password=encrypt_pw or None
            )
            QMessageBox.information(
                self,
                "Importar",
                f"Importado:\n"
                f"  Grupos: {stats['groups']}\n"
                f"  Servidores: {stats['servers']}\n"
                f"  Ignorados (duplicados): {stats['skipped']}\n\n"
                "Credenciais não foram importadas — informe-as ao conectar.",
            )
            self.refresh_servers()
            self._log("INFO", f"Importação: {stats}", category="app")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Importar", str(exc))

    # ── Helpers ─────────────────────────────────────────────

    async def _get_sftp_for_server(self, server_id: int):
        if server_id in self.sftp_clients:
            return self.sftp_clients[server_id]
        client = self.sessions.get(server_id)
        if not client or not client.is_connected:
            return None
        sftp = await client.open_sftp()
        self.sftp_clients[server_id] = sftp
        return sftp

    def _get_ssh_connection(self, server_id: int):
        client = self.sessions.get(server_id)
        if client and client.is_connected:
            return client.connection
        return None

    def _on_transfer_status(self, item) -> None:
        self.status_xfer.setText(
            f"Transferência: {item.display_name} — {item.status.label_pt}"
        )
        # Auto-expandir só quando inicia algo novo (usuário vê feedback) — e recolher depois
        if item.status.value == "running" and not self.transfers_panel.is_expanded():
            # manter compacto; só atualizar status
            pass
        if item.status.value in ("completed", "failed"):
            try:
                self.db.add_transfer_history(item)
            except Exception:  # noqa: BLE001
                pass
            self._log(
                "INFO" if item.status.value == "completed" else "ERROR",
                f"Transferência {item.status.label_pt}: {item.display_name}",
                category="transfer",
                server_id=item.server_id,
            )

    def _log(
        self,
        level: str,
        message: str,
        *,
        category: str = "app",
        server_id: Optional[int] = None,
        details: str = "",
    ) -> None:
        safe = sanitize_for_log(message)
        try:
            self.db.add_log(level, safe, category=category, server_id=server_id, details=details)
        except Exception:  # noqa: BLE001
            pass
        getattr(logger, level.lower(), logger.info)(safe)

    def _check_lock(self) -> None:
        if self.app_lock.check():
            self._show_lock_screen()

    def _on_master_hash_upgraded(self, new_hash: str) -> None:
        """Persiste migração SHA-256 → Argon2id após desbloqueio correto."""
        self.settings.master_password_hash = new_hash
        try:
            self.db.save_settings(self.settings)
        except Exception as exc:  # noqa: BLE001
            logger.error(sanitize_for_log("Falha ao salvar hash migrado", error=str(exc)))

    def _show_lock_screen(self) -> None:
        from app.ui.widgets import PasswordLineEdit
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("Aplicativo bloqueado"))
        dlg.setModal(True)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(tr("O aplicativo foi bloqueado por inatividade.")))
        pw = None
        if self.settings.master_password_enabled and self.settings.master_password_hash:
            pw = PasswordLineEdit()
            layout.addWidget(QLabel(tr("Senha mestra:")))
            layout.addWidget(pw)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn:
            ok_btn.setText(tr("Desbloquear"))
        layout.addWidget(buttons)

        def unlock() -> None:
            secret = pw.text() if pw else None
            if self.app_lock.unlock(secret):
                if pw is not None:
                    pw.clear()
                secret = None
                dlg.accept()
            else:
                if pw is not None:
                    pw.clear()
                QMessageBox.warning(
                    dlg,
                    tr("Bloqueio"),
                    tr("Senha incorreta ou aguarde o atraso entre tentativas."),
                )

        buttons.accepted.connect(unlock)
        dlg.exec()

    def _about(self) -> None:
        QMessageBox.about(
            self,
            f"{tr('Sobre')} {__app_name__}",
            f"<h3>{__app_name__} {__version__}</h3>"
            f"<p>{tr('Gerenciador SSH e SFTP para Linux.')}</p>"
            f"<p>{tr('Perfis, terminal, arquivos e transferências.')}</p>"
            f"<p>{tr('Credenciais no keyring')} · SQLite · AsyncSSH · PySide6</p>"
            "<p>© 2026 · MIT License</p>",
        )

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        schedule(self._shutdown(), name="shutdown")
        # give a moment — run sync cleanup best-effort
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # schedule and accept close; tasks will clean up
                pass
            else:
                loop.run_until_complete(self._shutdown())
        except Exception:  # noqa: BLE001
            pass
        self._log("INFO", "Aplicação encerrada", category="app")
        event.accept()

    async def _shutdown(self) -> None:
        await self.transfer_queue.stop()
        await self.sessions.disconnect_all()
        self.db.close()
