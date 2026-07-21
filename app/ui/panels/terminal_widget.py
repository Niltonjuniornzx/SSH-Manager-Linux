"""Terminal interativo embutido (PTY + emulação VT100 com pyte).

Comportamento de terminal real:
- Digite direto na área do terminal (sem campo separado)
- Cores ANSI, cursor, redimensionamento de PTY
- Copiar/colar, Ctrl+C/Z, scrollback
"""

from __future__ import annotations

import logging
from typing import Optional

import pyte
from pyte.screens import HistoryScreen
from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QApplication, QSizePolicy, QWidget

logger = logging.getLogger(__name__)

# Cores estilo xterm / GitHub dark
_FG = {
    "black": "#0d1117",
    "red": "#ff7b72",
    "green": "#3fb950",
    "brown": "#d29922",
    "yellow": "#d29922",
    "blue": "#58a6ff",
    "magenta": "#bc8cff",
    "cyan": "#39c5cf",
    "white": "#c9d1d9",
    "default": "#c9d1d9",
}
_BG = {
    "black": "#0d1117",
    "red": "#490202",
    "green": "#0a2f1a",
    "brown": "#3d2e00",
    "yellow": "#3d2e00",
    "blue": "#0c2d6b",
    "magenta": "#2d1b4e",
    "cyan": "#0a3a3d",
    "white": "#30363d",
    "default": "#0d1117",
}
_BRIGHT_FG = {
    "black": "#484f58",
    "red": "#ffa198",
    "green": "#56d364",
    "brown": "#e3b341",
    "yellow": "#e3b341",
    "blue": "#79c0ff",
    "magenta": "#d2a8ff",
    "cyan": "#56d4dd",
    "white": "#f0f6fc",
    "default": "#f0f6fc",
}


def _color(name: Optional[str], *, bg: bool = False, bold: bool = False) -> QColor:
    key = (name or "default").lower()
    # pyte may use "brightblack" etc.
    if key.startswith("bright"):
        base = key[6:] or "default"
        palette = _BRIGHT_FG if not bg else _BG
        return QColor(palette.get(base, palette["default"]))
    if bold and not bg:
        return QColor(_BRIGHT_FG.get(key, _BRIGHT_FG["default"]))
    palette = _BG if bg else _FG
    return QColor(palette.get(key, palette["default"]))


class TerminalWidget(QWidget):
    """Widget de terminal tipo xterm — teclado vai direto ao PTY remoto."""

    data_out = Signal(str)  # bytes digitados (como str) para o canal SSH
    resized = Signal(int, int)  # cols, rows
    title_changed = Signal(str)

    def __init__(
        self,
        *,
        cols: int = 80,
        rows: int = 24,
        font_family: str = "Monospace",
        font_size: int = 12,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        # NÃO basear minimum/sizeHint nas cols×rows — isso estoura a janela maximizada
        self.setMinimumSize(120, 80)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        self._font = QFont(font_family, font_size)
        self._font.setStyleHint(QFont.StyleHint.Monospace)
        self._font.setFixedPitch(True)
        self.setFont(self._font)
        self._metrics = QFontMetrics(self._font)
        self._cw = max(1, self._metrics.horizontalAdvance("M"))
        self._ch = max(1, self._metrics.height())

        self._cols = cols
        self._rows = rows
        self._screen = HistoryScreen(cols, rows, history=5000)
        self._screen.set_mode(pyte.modes.LNM)
        self._stream = pyte.Stream(self._screen)

        self._encoding = "utf-8"
        self._connected = False
        self._blink = True
        self._selection_start: Optional[tuple[int, int]] = None  # (col, row)
        self._selection_end: Optional[tuple[int, int]] = None
        self._history_offset = 0  # linhas de scrollback visíveis

        self._cursor_timer = QTimer(self)
        self._cursor_timer.timeout.connect(self._toggle_blink)
        self._cursor_timer.start(530)

        self._paint_timer = QTimer(self)
        self._paint_timer.setSingleShot(True)
        self._paint_timer.timeout.connect(self.update)

        self._bg = QColor(_BG["default"])
        self._fg = QColor(_FG["default"])

    # ── API pública ─────────────────────────────────────────

    def set_encoding(self, encoding: str) -> None:
        self._encoding = encoding or "utf-8"

    def set_font_settings(self, family: str, size: int) -> None:
        self._font = QFont(family, size)
        self._font.setStyleHint(QFont.StyleHint.Monospace)
        self._font.setFixedPitch(True)
        self.setFont(self._font)
        self._metrics = QFontMetrics(self._font)
        self._cw = max(1, self._metrics.horizontalAdvance("M"))
        self._ch = max(1, self._metrics.height())
        self._recalc_size_from_widget()
        self.update()

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        if not connected:
            self.feed("\r\n\x1b[33m[desconectado]\x1b[0m\r\n")
        self.update()

    def feed(self, data: str | bytes) -> None:
        """Alimenta a saída do servidor (com códigos ANSI)."""
        if isinstance(data, bytes):
            text = data.decode(self._encoding, errors="replace")
        else:
            text = data
        try:
            self._stream.feed(text)
        except Exception as exc:  # noqa: BLE001
            logger.debug("pyte feed error: %s", exc)
        if self._screen.title:
            self.title_changed.emit(self._screen.title)
        self._schedule_paint()

    def clear_screen(self) -> None:
        self._stream.feed("\x1b[2J\x1b[H")
        self._history_offset = 0
        self.update()

    def reset(self) -> None:
        self._screen = HistoryScreen(self._cols, self._rows, history=5000)
        self._screen.set_mode(pyte.modes.LNM)
        self._stream = pyte.Stream(self._screen)
        self._history_offset = 0
        self.update()

    def term_size(self) -> tuple[int, int]:
        return self._cols, self._rows

    def write_keys(self, text: str) -> None:
        if self._connected and text:
            self.data_out.emit(text)

    # ── Layout / resize ─────────────────────────────────────

    def sizeHint(self) -> QSize:  # noqa: N802
        # Fixo e modesto — o layout preenche o espaço disponível
        return QSize(640, 400)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(120, 80)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self._recalc_size_from_widget)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._recalc_size_from_widget()

    def _recalc_size_from_widget(self) -> None:
        # Apenas ajusta o buffer PTY ao pixel size do widget (não mexe no sizeHint)
        w = max(1, self.width() - 4)
        h = max(1, self.height() - 4)
        cols = max(20, w // self._cw)
        rows = max(5, h // self._ch)
        # Limite de sanidade (evita buffers enormes se algo der errado)
        cols = min(cols, 500)
        rows = min(rows, 200)
        if cols != self._cols or rows != self._rows:
            self._cols = cols
            self._rows = rows
            try:
                self._screen.resize(rows, cols)
            except Exception:  # noqa: BLE001
                pass
            self.resized.emit(cols, rows)

    # ── Input ───────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if not self._connected:
            return

        mods = event.modifiers()
        key = event.key()
        text = event.text()

        # Ctrl+Shift+C / Ctrl+Shift+V — copiar/colar
        if mods & Qt.KeyboardModifier.ControlModifier and mods & Qt.KeyboardModifier.ShiftModifier:
            if key == Qt.Key.Key_C:
                self._copy_selection()
                return
            if key == Qt.Key.Key_V:
                self._paste()
                return

        seq = self._map_key(key, mods, text)
        if seq is not None:
            self.data_out.emit(seq)
            event.accept()
            return
        super().keyPressEvent(event)

    def _map_key(self, key: int, mods: Qt.KeyboardModifier, text: str) -> Optional[str]:
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)

        # Ctrl+letras
        if ctrl and not alt and not shift:
            if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
                return chr(key - Qt.Key.Key_A + 1)
            if key == Qt.Key.Key_Space:
                return "\x00"
            if key in (Qt.Key.Key_BracketLeft,):
                return "\x1b"
            if key == Qt.Key.Key_Backslash:
                return "\x1c"
            if key == Qt.Key.Key_BracketRight:
                return "\x1d"
            if key == Qt.Key.Key_AsciiCircum:
                return "\x1e"
            if key == Qt.Key.Key_Underscore:
                return "\x1f"

        special = {
            Qt.Key.Key_Return: "\r",
            Qt.Key.Key_Enter: "\r",
            Qt.Key.Key_Backspace: "\x7f",
            Qt.Key.Key_Tab: "\t",
            Qt.Key.Key_Escape: "\x1b",
            Qt.Key.Key_Delete: "\x1b[3~",
            Qt.Key.Key_Home: "\x1b[H",
            Qt.Key.Key_End: "\x1b[F",
            Qt.Key.Key_Insert: "\x1b[2~",
            Qt.Key.Key_PageUp: "\x1b[5~",
            Qt.Key.Key_PageDown: "\x1b[6~",
            Qt.Key.Key_Up: "\x1b[A",
            Qt.Key.Key_Down: "\x1b[B",
            Qt.Key.Key_Right: "\x1b[C",
            Qt.Key.Key_Left: "\x1b[D",
            Qt.Key.Key_F1: "\x1bOP",
            Qt.Key.Key_F2: "\x1bOQ",
            Qt.Key.Key_F3: "\x1bOR",
            Qt.Key.Key_F4: "\x1bOS",
            Qt.Key.Key_F5: "\x1b[15~",
            Qt.Key.Key_F6: "\x1b[17~",
            Qt.Key.Key_F7: "\x1b[18~",
            Qt.Key.Key_F8: "\x1b[19~",
            Qt.Key.Key_F9: "\x1b[20~",
            Qt.Key.Key_F10: "\x1b[21~",
            Qt.Key.Key_F11: "\x1b[23~",
            Qt.Key.Key_F12: "\x1b[24~",
        }
        if key in special:
            return special[key]

        if text:
            if alt:
                return "\x1b" + text
            return text
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.setFocus()
        if event.button() == Qt.MouseButton.LeftButton:
            col, row = self._pos_to_cell(event.position().toPoint())
            self._selection_start = (col, row)
            self._selection_end = (col, row)
            self.update()
        elif event.button() == Qt.MouseButton.MiddleButton:
            self._paste()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.buttons() & Qt.MouseButton.LeftButton and self._selection_start:
            col, row = self._pos_to_cell(event.position().toPoint())
            self._selection_end = (col, row)
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            text = self._selected_text()
            if text:
                QApplication.clipboard().setText(text, QApplication.clipboard().Mode.Selection)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        # copiar seleção se houver
        text = self._selected_text()
        if text:
            QApplication.clipboard().setText(text)
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        delta = event.angleDelta().y()
        step = 3 if abs(delta) < 120 else abs(delta) // 40
        if delta > 0:
            self._history_offset = min(
                self._history_offset + step,
                len(self._screen.history.top) if hasattr(self._screen, "history") else 0,
            )
        else:
            self._history_offset = max(0, self._history_offset - step)
        self.update()

    def _pos_to_cell(self, pos: QPoint) -> tuple[int, int]:
        col = max(0, min(self._cols - 1, (pos.x() - 2) // self._cw))
        row = max(0, min(self._rows - 1, (pos.y() - 2) // self._ch))
        return col, row

    def _copy_selection(self) -> None:
        text = self._selected_text()
        if text:
            QApplication.clipboard().setText(text)

    def _paste(self) -> None:
        text = QApplication.clipboard().text()
        if text and self._connected:
            # colar como está (CR se necessário)
            self.data_out.emit(text.replace("\n", "\r"))

    def _selected_text(self) -> str:
        if not self._selection_start or not self._selection_end:
            return ""
        (c1, r1), (c2, r2) = self._selection_start, self._selection_end
        if (r1, c1) > (r2, c2):
            c1, r1, c2, r2 = c2, r2, c1, r1
        lines: list[str] = []
        for r in range(r1, r2 + 1):
            line = self._line_text(r)
            if r == r1 and r == r2:
                lines.append(line[c1 : c2 + 1])
            elif r == r1:
                lines.append(line[c1:])
            elif r == r2:
                lines.append(line[: c2 + 1])
            else:
                lines.append(line)
        return "\n".join(lines).rstrip()

    def _line_text(self, row: int) -> str:
        # buffer do pyte: screen.buffer[y][x]
        chars = []
        for x in range(self._cols):
            try:
                cell = self._screen.buffer[row][x]
                chars.append(cell.data if cell.data else " ")
            except Exception:  # noqa: BLE001
                chars.append(" ")
        return "".join(chars).rstrip() + " " * 0

    # ── Paint ───────────────────────────────────────────────

    def _toggle_blink(self) -> None:
        self._blink = not self._blink
        self.update()

    def _schedule_paint(self) -> None:
        if not self._paint_timer.isActive():
            self._paint_timer.start(16)  # ~60fps coalesce

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._bg)
        painter.setFont(self._font)

        # Seleção
        sel = self._selection_rect_cells()

        for y in range(self._rows):
            for x in range(self._cols):
                try:
                    cell = self._screen.buffer[y][x]
                except Exception:  # noqa: BLE001
                    continue
                ch = cell.data if cell.data else " "
                bold = bool(getattr(cell, "bold", False))
                reverse = bool(getattr(cell, "reverse", False))
                fg = _color(getattr(cell, "fg", "default"), bold=bold)
                bg = _color(getattr(cell, "bg", "default"), bg=True)
                if reverse:
                    fg, bg = bg, fg
                if sel and self._in_selection(x, y, sel):
                    bg = QColor("#264f78")
                    fg = QColor("#ffffff")

                rect = QRect(2 + x * self._cw, 2 + y * self._ch, self._cw, self._ch)
                if bg != self._bg or (sel and self._in_selection(x, y, sel)):
                    painter.fillRect(rect, bg)
                painter.setPen(fg)
                if ch and ch != " ":
                    painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, ch)

        # Cursor
        if self._connected and self._blink and self._history_offset == 0:
            try:
                cx = int(self._screen.cursor.x)
                cy = int(self._screen.cursor.y)
                if 0 <= cx < self._cols and 0 <= cy < self._rows:
                    crect = QRect(
                        2 + cx * self._cw,
                        2 + cy * self._ch,
                        self._cw,
                        self._ch,
                    )
                    painter.fillRect(crect, QColor("#58a6ff"))
                    # caractere sob o cursor
                    try:
                        cell = self._screen.buffer[cy][cx]
                        ch = cell.data if cell.data else " "
                        if ch.strip():
                            painter.setPen(QColor("#0d1117"))
                            painter.drawText(
                                crect,
                                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                ch,
                            )
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001
                pass

        # Borda sutil se sem foco
        if not self.hasFocus():
            painter.setPen(QColor("#30363d"))
            painter.drawRect(0, 0, self.width() - 1, self.height() - 1)

    def _selection_rect_cells(
        self,
    ) -> Optional[tuple[int, int, int, int]]:
        if not self._selection_start or not self._selection_end:
            return None
        (c1, r1), (c2, r2) = self._selection_start, self._selection_end
        if (r1, c1) > (r2, c2):
            c1, r1, c2, r2 = c2, r2, c1, r1
        return c1, r1, c2, r2

    @staticmethod
    def _in_selection(x: int, y: int, sel: tuple[int, int, int, int]) -> bool:
        c1, r1, c2, r2 = sel
        if y < r1 or y > r2:
            return False
        if r1 == r2:
            return c1 <= x <= c2
        if y == r1:
            return x >= c1
        if y == r2:
            return x <= c2
        return True
