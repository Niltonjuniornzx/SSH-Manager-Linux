"""Barra de título e redimensionamento para janela sem borda do sistema."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QMouseEvent, QPainterPath, QPixmap, QRegion
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

_WINDOW_RADIUS = 14

_MARGIN = 6  # pixels de borda para redimensionar


def _find_app_icon() -> Optional[Path]:
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "assets" / "icons" / "ssh-manager-linux-32.png",
        here.parents[2] / "assets" / "icons" / "ssh-manager-linux-48.png",
        Path.home()
        / ".local"
        / "share"
        / "ssh-manager-linux"
        / "assets"
        / "icons"
        / "ssh-manager-linux-32.png",
        Path.home()
        / ".local"
        / "share"
        / "icons"
        / "hicolor"
        / "32x32"
        / "apps"
        / "ssh-manager-linux.png",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


class TitleBar(QWidget):
    """Barra customizada: ícone, título, minimizar / maximizar / fechar."""

    def __init__(self, window: QMainWindow) -> None:
        super().__init__(window)
        self._window = window
        self._drag_pos: Optional[QPoint] = None
        self._restore_on_drag = False
        self.setObjectName("titleBar")
        self.setFixedHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 8, 0)
        lay.setSpacing(6)

        # Menu ☰ — substitui a barra Arquivo/Editar/… (libera 1 linha)
        self.btn_menu = QPushButton("☰")
        self.btn_menu.setObjectName("titleBtnMenu")
        self.btn_menu.setFixedSize(36, 28)
        from app.i18n import tr

        self.btn_menu.setToolTip(tr("Menu (Arquivo, Servidor, …)"))
        self.btn_menu.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_menu.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_menu.clicked.connect(self._show_app_menu)
        lay.addWidget(self.btn_menu)

        self._icon = QLabel()
        self._icon.setObjectName("titleBarIcon")
        self._icon.setFixedSize(18, 18)
        icon_path = _find_app_icon()
        if icon_path:
            pm = QPixmap(str(icon_path)).scaled(
                18,
                18,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._icon.setPixmap(pm)
        lay.addWidget(self._icon)

        self._title = QLabel(window.windowTitle())
        self._title.setObjectName("titleBarLabel")
        lay.addWidget(self._title, 1)

        self.btn_min = QPushButton("–")
        self.btn_max = QPushButton("□")
        self.btn_close = QPushButton("×")
        for btn, name, tip in (
            (self.btn_min, "titleBtnMin", tr("Minimizar")),
            (self.btn_max, "titleBtnMax", tr("Maximizar")),
            (self.btn_close, "titleBtnClose", tr("Fechar")),
        ):
            btn.setObjectName(name)
            btn.setFixedSize(40, 28)
            btn.setToolTip(tip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            lay.addWidget(btn)

        self.btn_min.clicked.connect(window.showMinimized)
        self.btn_max.clicked.connect(self._toggle_max)
        self.btn_close.clicked.connect(window.close)

        window.windowTitleChanged.connect(self._title.setText)

    def _show_app_menu(self) -> None:
        menu = getattr(self._window, "_app_menu", None)
        if menu is None:
            return
        # Abre logo abaixo do botão ☰
        pos = self.btn_menu.mapToGlobal(self.btn_menu.rect().bottomLeft())
        menu.exec(pos)

    def _toggle_max(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()
        self.sync_max_button()

    def sync_max_button(self) -> None:
        if self._window.isMaximized():
            self.btn_max.setText("❐")
            self.btn_max.setToolTip("Restaurar")
        else:
            self.btn_max.setText("□")
            self.btn_max.setToolTip("Maximizar")

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(event.position().toPoint())
            if isinstance(child, QPushButton):
                super().mousePressEvent(event)
                return
            if self._window.isMaximized():
                self._drag_pos = event.globalPosition().toPoint()
                self._restore_on_drag = True
            else:
                self._drag_pos = (
                    event.globalPosition().toPoint()
                    - self._window.frameGeometry().topLeft()
                )
                self._restore_on_drag = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_pos is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        global_pos = event.globalPosition().toPoint()
        if self._restore_on_drag and self._window.isMaximized():
            ratio = event.position().x() / max(1, self.width())
            self._window.showNormal()
            self.sync_max_button()
            w = self._window.width()
            new_x = global_pos.x() - int(w * ratio)
            new_y = global_pos.y() - 12
            self._window.move(new_x, new_y)
            self._drag_pos = global_pos - self._window.frameGeometry().topLeft()
            self._restore_on_drag = False
        else:
            self._window.move(global_pos - self._drag_pos)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._drag_pos = None
        self._restore_on_drag = False
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_max()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class WindowEdgeResize(QObject):
    """Redimensiona a janela sem borda pelas bordas (event filter)."""

    def __init__(self, window: QMainWindow) -> None:
        super().__init__(window)
        self._window = window
        self._edges: Qt.Edges = Qt.Edge(0)
        self._press_global: Optional[QPoint] = None
        self._press_geo: Optional[QRect] = None
        window.setMouseTracking(True)
        window.installEventFilter(self)

    def attach(self, widget: QWidget) -> None:
        widget.setMouseTracking(True)
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):  # noqa: N802
        et = event.type()
        if et == QEvent.Type.MouseMove and isinstance(event, QMouseEvent):
            if self._press_geo is not None and self._edges:
                self._do_resize(event.globalPosition().toPoint())
                return True
            if not (event.buttons() & Qt.MouseButton.LeftButton):
                self._update_cursor(event.globalPosition().toPoint())
        elif et == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
            if event.button() == Qt.MouseButton.LeftButton and not self._window.isMaximized():
                self._update_cursor(event.globalPosition().toPoint())
                if self._edges:
                    self._press_global = event.globalPosition().toPoint()
                    self._press_geo = QRect(self._window.geometry())
                    return True
        elif et == QEvent.Type.MouseButtonRelease and isinstance(event, QMouseEvent):
            if event.button() == Qt.MouseButton.LeftButton:
                self._press_global = None
                self._press_geo = None
        elif et == QEvent.Type.Leave:
            if self._press_geo is None:
                self._window.unsetCursor()
                self._edges = Qt.Edge(0)
        return False

    def _hit_edges(self, global_pos: QPoint) -> Qt.Edges:
        if self._window.isMaximized() or self._window.isFullScreen():
            return Qt.Edge(0)
        geo = self._window.frameGeometry()
        x, y = global_pos.x(), global_pos.y()
        edges = Qt.Edge(0)
        if x <= geo.left() + _MARGIN:
            edges |= Qt.Edge.LeftEdge
        if x >= geo.right() - _MARGIN:
            edges |= Qt.Edge.RightEdge
        if y <= geo.top() + _MARGIN:
            edges |= Qt.Edge.TopEdge
        if y >= geo.bottom() - _MARGIN:
            edges |= Qt.Edge.BottomEdge
        return edges

    def _update_cursor(self, global_pos: QPoint) -> None:
        edges = self._hit_edges(global_pos)
        self._edges = edges
        left = bool(edges & Qt.Edge.LeftEdge)
        right = bool(edges & Qt.Edge.RightEdge)
        top = bool(edges & Qt.Edge.TopEdge)
        bottom = bool(edges & Qt.Edge.BottomEdge)
        if (left and top) or (right and bottom):
            self._window.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif (right and top) or (left and bottom):
            self._window.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif left or right:
            self._window.setCursor(Qt.CursorShape.SizeHorCursor)
        elif top or bottom:
            self._window.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self._window.unsetCursor()

    def _do_resize(self, global_pos: QPoint) -> None:
        assert self._press_geo is not None and self._press_global is not None
        delta = global_pos - self._press_global
        geo = QRect(self._press_geo)
        min_w = max(self._window.minimumWidth(), 400)
        min_h = max(self._window.minimumHeight(), 300)

        if self._edges & Qt.Edge.LeftEdge:
            new_left = geo.left() + delta.x()
            if geo.right() - new_left + 1 >= min_w:
                geo.setLeft(new_left)
        if self._edges & Qt.Edge.RightEdge:
            new_right = geo.right() + delta.x()
            if new_right - geo.left() + 1 >= min_w:
                geo.setRight(new_right)
        if self._edges & Qt.Edge.TopEdge:
            new_top = geo.top() + delta.y()
            if geo.bottom() - new_top + 1 >= min_h:
                geo.setTop(new_top)
        if self._edges & Qt.Edge.BottomEdge:
            new_bottom = geo.bottom() + delta.y()
            if new_bottom - geo.top() + 1 >= min_h:
                geo.setBottom(new_bottom)

        screen = QGuiApplication.screenAt(global_pos) or QGuiApplication.primaryScreen()
        if screen:
            ag = screen.availableGeometry()
            if geo.width() > ag.width():
                geo.setWidth(ag.width())
            if geo.height() > ag.height():
                geo.setHeight(ag.height())

        self._window.setGeometry(geo)


def _apply_rounded_mask(window: QWidget, radius: int = _WINDOW_RADIUS) -> None:
    """Corta cantos da janela frameless (sem isso o QSS não arredonda o frame)."""
    if isinstance(window, QMainWindow) and (window.isMaximized() or window.isFullScreen()):
        window.clearMask()
        return
    rect = window.rect()
    if rect.width() <= 0 or rect.height() <= 0:
        return
    path = QPainterPath()
    path.addRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    poly = path.toFillPolygon().toPolygon()
    window.setMask(QRegion(poly))


class _RoundCornersFilter(QObject):
    """Atualiza a máscara arredondada em resize / maximizar."""

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self._window = window

    def eventFilter(self, obj, event):  # noqa: N802
        et = event.type()
        if et in (
            QEvent.Type.Resize,
            QEvent.Type.Show,
            QEvent.Type.WindowStateChange,
        ):
            _apply_rounded_mask(self._window)
        return False


class DialogTitleBar(QWidget):
    """Barra de título do app para QDialog (ícone + título + fechar)."""

    def __init__(self, dialog: QDialog) -> None:
        super().__init__(dialog)
        self._window = dialog
        self._drag_pos: Optional[QPoint] = None
        self.setObjectName("titleBar")
        self.setFixedHeight(38)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        from app.i18n import tr

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 6, 0)
        lay.setSpacing(8)

        self._icon = QLabel()
        self._icon.setObjectName("titleBarIcon")
        self._icon.setFixedSize(18, 18)
        icon_path = _find_app_icon()
        if icon_path:
            pm = QPixmap(str(icon_path)).scaled(
                18,
                18,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._icon.setPixmap(pm)
        else:
            app = QApplication.instance()
            if app is not None and not app.windowIcon().isNull():
                self._icon.setPixmap(app.windowIcon().pixmap(18, 18))
        lay.addWidget(self._icon)

        self._title = QLabel(dialog.windowTitle())
        self._title.setObjectName("titleBarLabel")
        lay.addWidget(self._title, 1)

        self.btn_close = QPushButton("×")
        self.btn_close.setObjectName("titleBtnClose")
        self.btn_close.setFixedSize(36, 28)
        self.btn_close.setToolTip(tr("Fechar"))
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_close.clicked.connect(dialog.reject)
        lay.addWidget(self.btn_close)

        dialog.windowTitleChanged.connect(self._title.setText)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(event.position().toPoint())
            if isinstance(child, QPushButton):
                super().mousePressEvent(event)
                return
            self._drag_pos = (
                event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_pos is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self._window.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._drag_pos = None
        super().mouseReleaseEvent(event)


def apply_dialog_chrome(dialog: QDialog) -> None:
    """Aplica chrome do app (sem moldura do DE) a um QDialog já montado."""
    # Ícone do app
    app = QApplication.instance()
    if app is not None and not app.windowIcon().isNull():
        dialog.setWindowIcon(app.windowIcon())
    else:
        icon_path = _find_app_icon()
        if icon_path:
            from PySide6.QtGui import QIcon

            dialog.setWindowIcon(QIcon(str(icon_path)))

    dialog.setObjectName("appDialog")
    dialog.setWindowFlags(
        Qt.WindowType.Dialog
        | Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.WindowSystemMenuHint
    )
    # Reempacota layout existente sob a title bar do app
    old = dialog.layout()
    body = QWidget(dialog)
    if old is not None:
        body.setLayout(old)
    else:
        QVBoxLayout(body)

    root = QVBoxLayout(dialog)
    root.setContentsMargins(1, 1, 1, 1)
    root.setSpacing(0)
    title = DialogTitleBar(dialog)
    root.addWidget(title)
    root.addWidget(body, 1)

    dialog._dialog_title_bar = title  # type: ignore[attr-defined]
    rounder = _RoundCornersFilter(dialog)  # type: ignore[arg-type]
    dialog.installEventFilter(rounder)
    dialog._round_filter = rounder  # type: ignore[attr-defined]
    _apply_rounded_mask(dialog)  # type: ignore[arg-type]


def enable_custom_chrome(window: QMainWindow) -> TitleBar:
    """Ativa janela sem borda do DE + barra e borda próprias do app."""
    window.setWindowFlags(
        Qt.WindowType.Window
        | Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.WindowSystemMenuHint
        | Qt.WindowType.WindowMinMaxButtonsHint
    )
    window.setObjectName("mainWindow")

    chrome = QWidget(window)
    chrome.setObjectName("windowChrome")
    chrome_lay = QVBoxLayout(chrome)
    chrome_lay.setContentsMargins(0, 0, 0, 0)
    chrome_lay.setSpacing(0)

    title = TitleBar(window)
    chrome_lay.addWidget(title)
    # Sem QMenuBar — menu fica no botão ☰ da title bar (mais espaço)

    window.setMenuWidget(chrome)

    resizer = WindowEdgeResize(window)
    resizer.attach(chrome)
    resizer.attach(title)
    window._edge_resizer = resizer  # type: ignore[attr-defined]
    window._title_bar = title  # type: ignore[attr-defined]

    # Cantos arredondados da janela inteira
    rounder = _RoundCornersFilter(window)
    window.installEventFilter(rounder)
    window._round_filter = rounder  # type: ignore[attr-defined]
    _apply_rounded_mask(window)
    return title
