"""
score_view.py — Lienzo de partitura de bateria para seguir en tiempo real.

Dibuja un pentagrama de 5 lineas donde el eje X es el TIEMPO (segundos reales del
audio). Cada golpe es una cabeza de nota en su carril (bombo/redoblante/hi-hat/
tom/plato). Un cursor vertical marca la posicion actual, resalta las notas que
suenan y el lienzo se auto-desplaza para mantener el cursor a la vista.

Como notas y cursor usan la misma funcion tiempo->X, la sincronia es exacta.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import customtkinter as ctk

# Carril vertical (y en pixeles) y estilo de cabeza por categoria.
# 'x' = aspa (platos/hi-hat), 'o' = cabeza rellena (tambores).
_STAFF_TOP = 34
_STAFF_GAP = 15  # separacion entre lineas
_LINES = [_STAFF_TOP + i * _STAFF_GAP for i in range(5)]  # 5 lineas

LANES: Dict[str, Tuple[float, str]] = {
    "cymbal": (_STAFF_TOP - 12, "x"),          # encima del pentagrama
    "hihat": (_STAFF_TOP - 2, "x"),            # linea superior
    "tom": (_STAFF_TOP + _STAFF_GAP * 1.5, "o"),
    "snare": (_STAFF_TOP + _STAFF_GAP * 2, "o"),  # linea central
    "kick": (_STAFF_TOP + _STAFF_GAP * 4, "o"),   # linea inferior
}

_MARGIN_L = 48        # espacio para la clave
_PX_PER_SEC = 90      # ancho temporal
_NOTE_R = 5           # radio de la cabeza
_HL_WINDOW = 0.06     # ventana de resaltado (segundos) alrededor del cursor

_COL_STAFF = "#8a8a8a"
_COL_NOTE = "#e8e8e8"
_COL_NOTE_HL = "#1db954"   # verde al sonar
_COL_CURSOR = "#1db954"
_COL_BAR = "#4a4a4a"
_COL_BG = "#0f0f0f"


class ScoreCanvas(ctk.CTkFrame):
    """Pentagrama desplazable con cursor sincronizado al tiempo."""

    def __init__(self, master, height: int = 150, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self._canvas = ctk.CTkCanvas(
            self, height=height, highlightthickness=0, bg=_COL_BG
        )
        self._canvas.pack(fill="both", expand=True)

        self._events: List[Tuple[float, str]] = []
        self._duration = 0.0
        self._width = _MARGIN_L
        self._note_items: List[Tuple[int, float]] = []  # (item_id, segundos)
        self._cursor = None
        self._hl_state: Dict[int, bool] = {}

    # ------------------------------------------------------------------ datos
    def set_events(self, events: List[Tuple[float, str]], duration: float) -> None:
        self._events = events
        self._duration = max(duration, (events[-1][0] if events else 0.0) + 1.0)
        self._width = int(_MARGIN_L + self._duration * _PX_PER_SEC + 60)
        self._redraw()

    def _x(self, seconds: float) -> float:
        return _MARGIN_L + seconds * _PX_PER_SEC

    # ----------------------------------------------------------------- dibujo
    def _redraw(self) -> None:
        c = self._canvas
        c.delete("all")
        self._note_items.clear()
        self._hl_state.clear()

        c.configure(scrollregion=(0, 0, self._width, int(c["height"])))

        # Lineas del pentagrama
        for y in _LINES:
            c.create_line(_MARGIN_L, y, self._width, y, fill=_COL_STAFF)

        # Clave de percusion (dos barras)
        c.create_line(_MARGIN_L - 14, _LINES[0], _MARGIN_L - 14, _LINES[-1],
                      fill=_COL_STAFF, width=3)
        c.create_line(_MARGIN_L - 8, _LINES[0], _MARGIN_L - 8, _LINES[-1],
                      fill=_COL_STAFF, width=3)

        # Barras de compas (cada 4 negras estimadas por la duracion no las tenemos
        # aqui; usamos una rejilla ligera cada 1 s como guia visual)
        t = 1.0
        while t < self._duration:
            x = self._x(t)
            c.create_line(x, _LINES[0] - 6, x, _LINES[-1] + 6, fill=_COL_BAR)
            t += 1.0

        # Cabezas de nota
        for seconds, category in self._events:
            y, style = LANES.get(category, (_LINES[2], "o"))
            x = self._x(seconds)
            if style == "x":
                item = c.create_text(x, y, text="✕", fill=_COL_NOTE,
                                     font=("Arial", 11, "bold"))
            else:
                item = c.create_oval(x - _NOTE_R, y - _NOTE_R, x + _NOTE_R, y + _NOTE_R,
                                     fill=_COL_NOTE, outline="")
            self._note_items.append((item, seconds))
            self._hl_state[item] = False

        # Cursor
        self._cursor = c.create_line(
            _MARGIN_L, _LINES[0] - 14, _MARGIN_L, _LINES[-1] + 14,
            fill=_COL_CURSOR, width=2,
        )

    # ----------------------------------------------------------------- cursor
    def set_cursor_seconds(self, seconds: float) -> None:
        if self._cursor is None:
            return
        c = self._canvas
        x = self._x(seconds)
        c.coords(self._cursor, x, _LINES[0] - 14, x, _LINES[-1] + 14)

        # Resaltar notas cercanas al cursor (solo las que cambian de estado)
        for item, sec in self._note_items:
            on = abs(sec - seconds) <= _HL_WINDOW
            if on != self._hl_state.get(item, False):
                self._hl_state[item] = on
                color = _COL_NOTE_HL if on else _COL_NOTE
                if c.type(item) == "text":
                    c.itemconfigure(item, fill=color)
                else:
                    c.itemconfigure(item, fill=color)

        # Auto-scroll para mantener el cursor visible/centrado
        view_w = c.winfo_width()
        if view_w > 1 and self._width > view_w:
            target = (x - view_w / 2) / self._width
            c.xview_moveto(min(max(target, 0.0), 1.0))

    def reset_cursor(self) -> None:
        self.set_cursor_seconds(0.0)
