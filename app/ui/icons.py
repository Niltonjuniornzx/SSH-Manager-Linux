"""Ícones da interface (SVG no tema teal do app)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer


def _icons_dir() -> Path:
    # app/ui/icons.py → repo root / assets/icons/ui
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "assets" / "icons" / "ui",
        Path.home() / ".local" / "share" / "ssh-manager-linux" / "assets" / "icons" / "ui",
    ]
    for p in candidates:
        if p.is_dir():
            return p
    return candidates[0]


@lru_cache(maxsize=32)
def ui_icon(name: str, size: int = 20) -> QIcon:
    """Carrega `assets/icons/ui/{name}.svg` como QIcon rasterizado."""
    path = _icons_dir() / f"{name}.svg"
    if not path.is_file():
        # fallback tema do sistema
        theme_map = {
            "groups": "object-group",
            "plus": "list-add",
            "folder-group": "folder",
        }
        return QIcon.fromTheme(theme_map.get(name, name))

    renderer = QSvgRenderer(str(path))
    if not renderer.isValid():
        return QIcon()

    dpr = 2  # nítido em HiDPI
    img = QImage(size * dpr, size * dpr, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size * dpr, size * dpr))
    painter.end()

    pix = QPixmap.fromImage(img)
    pix.setDevicePixelRatio(dpr)
    icon = QIcon()
    icon.addPixmap(pix)
    return icon


def set_button_icon(button, name: str, *, size: int = 18, tooltip: str | None = None) -> None:
    """Aplica ícone SVG a um QPushButton (sem texto)."""
    button.setText("")
    button.setIcon(ui_icon(name, size))
    button.setIconSize(QSize(size, size))
    if tooltip:
        button.setToolTip(tooltip)


def color_avatar_icon(color: str, letter: str = "", *, size: int = 22) -> QIcon:
    """Avatar arredondado com cor do perfil + inicial (substitui o quadradão)."""
    dpr = 2
    img = QImage(size * dpr, size * dpr, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(dpr, dpr)

    fill = QColor(color or "#2dd4bf")
    path = QPainterPath()
    path.addRoundedRect(0.5, 0.5, size - 1, size - 1, 6, 6)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(fill)
    p.drawPath(path)

    ch = (letter or "?").strip()[:1].upper() or "?"
    lum = 0.299 * fill.red() + 0.587 * fill.green() + 0.114 * fill.blue()
    p.setPen(QColor("#0b0d12") if lum > 160 else QColor("#ffffff"))
    font = QFont("Inter", max(9, size // 2 - 1))
    font.setBold(True)
    p.setFont(font)
    p.drawText(0, 0, size, size, int(Qt.AlignmentFlag.AlignCenter), ch)
    p.end()

    pix = QPixmap.fromImage(img)
    pix.setDevicePixelRatio(dpr)
    icon = QIcon()
    icon.addPixmap(pix)
    return icon


def status_square_icon(color: str, *, size: int = 14, filled: bool = True) -> QIcon:
    """Quadradinho de status (ícone fixo — não estica na linha)."""
    dpr = 2
    img = QImage(size * dpr, size * dpr, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(dpr, dpr)

    c = QColor(color or "#8b93a7")
    # margem interna para não colar nas bordas do item
    m = 1.5
    r = 3.5
    path = QPainterPath()
    path.addRoundedRect(m, m, size - 2 * m, size - 2 * m, r, r)
    if filled:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawPath(path)
    else:
        pen = QPen(c, 1.6)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
    p.end()

    pix = QPixmap.fromImage(img)
    pix.setDevicePixelRatio(dpr)
    icon = QIcon()
    icon.addPixmap(pix)
    return icon


def tab_close_icon(*, size: int = 14, hover: bool = False) -> QIcon:
    """X suave p/ fechar aba (cinza; hover com fundo redondo suave)."""
    dpr = 2
    img = QImage(size * dpr, size * dpr, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(dpr, dpr)

    if hover:
        # fundo circular suave (não “bola” vermelha dura)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(248, 113, 113, 55))
        p.drawEllipse(0.5, 0.5, size - 1, size - 1)
        pen_color = QColor("#fca5a5")
    else:
        pen_color = QColor("#6b7280")

    pen = QPen(pen_color, 1.35)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    # X um pouco menor e centrado
    m = size * 0.32
    p.drawLine(m, m, size - m, size - m)
    p.drawLine(size - m, m, m, size - m)
    p.end()

    pix = QPixmap.fromImage(img)
    pix.setDevicePixelRatio(dpr)
    icon = QIcon()
    icon.addPixmap(pix)
    return icon
