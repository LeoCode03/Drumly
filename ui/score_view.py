"""
score_view.py — Lienzo de partitura de bateria para seguir en tiempo real.

Pentagrama de 5 lineas donde el eje X es el TIEMPO (segundos reales del audio).
Cada golpe es una cabeza de nota en su carril (bombo/redoblante/hi-hat/tom/plato).
Un cursor vertical marca la posicion actual, resalta las notas que suenan y el
lienzo se auto-desplaza para mantener el cursor a la vista.

- Responsive: el pentagrama se centra y escala con el alto de la ventana.
- Barras de compas reales a partir de BPM + negras/compas.
- Clic (o arrastre) sobre el lienzo -> seek (retroceder/avanzar) via callback.

Como notas y cursor usan la misma funcion tiempo->X, la sincronia es exacta.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

import customtkinter as ctk

# Orden vertical (de arriba a abajo) y estilo de cada carril.
# 'x' = aspa (platos/hi-hat), 'o' = cabeza rellena (tambores).
_LANE_ORDER = ["cymbal", "hihat", "tom", "snare", "kick"]
_LANE_STYLE = {"cymbal": "x", "hihat": "x", "tom": "o", "snare": "o", "kick": "o"}

_PX_PER_SEC = 120     # ancho temporal (mas grande = notas mas separadas)
_MARGIN_L = 60        # espacio para la clave

_COL_STAFF = "#8a8a8a"
_COL_NOTE = "#e8e8e8"
_COL_NOTE_HL = "#1db954"
_COL_CURSOR = "#1db954"
_COL_BAR = "#5a5a5a"
_COL_BG = "#0f0f0f"


class ScoreCanvas(ctk.CTkFrame):
    """Pentagrama desplazable, responsive, con cursor sincronizado al tiempo."""

    def __init__(self, master, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self._canvas = ctk.CTkCanvas(
            self, highlightthickness=0, bg=_COL_BG
        )
        self._canvas.pack(fill="both", expand=True)

        self._events: List[Tuple[float, str]] = []
        self._duration = 0.0
        self._bar_seconds = 0.0        # duracion de un compas (fallback constante)
        self._bar_offset = 0.0         # instante del primer tiempo (s)
        self._bar_times: List[float] = []  # barras en tiempos REALES (prioridad)
        self._width = _MARGIN_L
        self._note_items: List[Tuple[int, float]] = []
        self._cursor = None
        self._hl_state: Dict[int, bool] = {}
        self._cursor_seconds = 0.0
        self._on_seek: Optional[Callable[[float], None]] = None

        # Geometria del pentagrama (se recalcula segun el alto)
        self._lines: List[float] = []
        self._lane_y: Dict[str, float] = {}
        self._note_r = 6
        # Relleno lateral = media pantalla: permite centrar EXACTAMENTE cualquier
        # instante (incluido el 0) -> el cursor queda clavado en el medio y la
        # partitura se desplaza por debajo.
        self._pad = 0

        self._canvas.bind("<Configure>", lambda e: self._redraw())
        self._canvas.bind("<Button-1>", self._on_click)
        self._canvas.bind("<B1-Motion>", self._on_click)

    # ------------------------------------------------------------------ datos
    def set_events(
        self, events: List[Tuple[float, str]], duration: float,
        bpm: Optional[int] = None, beats_per_bar: int = 4,
        beat_offset: float = 0.0,
    ) -> None:
        self._events = events
        self._duration = max(duration, (events[-1][0] if events else 0.0) + 1.0)
        self._width = int(_MARGIN_L + self._duration * _PX_PER_SEC + 80)
        self._bar_offset = max(0.0, beat_offset)
        if bpm and bpm > 0:
            self._bar_seconds = beats_per_bar * 60.0 / bpm
        else:
            self._bar_seconds = 0.0
        self._redraw()

    def set_grid(
        self, bpm: Optional[int], beats_per_bar: int, beat_offset: float = 0.0
    ) -> None:
        """
        Barras de compas con rejilla CONSTANTE (BPM fijo), ancladas en
        `beat_offset`. Anula las barras por beats reales (set_bars) hasta que se
        vuelvan a establecer.
        """
        self._bar_times = []
        self._bar_seconds = (beats_per_bar * 60.0 / bpm) if (bpm and bpm > 0) else 0.0
        self._bar_offset = max(0.0, beat_offset)
        self._redraw()

    def set_bars(self, bar_times: List[float]) -> None:
        """
        Coloca las barras de compas en tiempos REALES (beat tracking). Tiene
        prioridad sobre la rejilla constante de set_grid: si el tempo de la
        cancion fluctua (en vivo), cada compas cae donde de verdad empieza.
        """
        self._bar_times = sorted(t for t in bar_times if t >= 0.0)
        self._redraw()

    def set_seek_callback(self, cb: Callable[[float], None]) -> None:
        self._on_seek = cb

    def _x(self, seconds: float) -> float:
        return self._pad + _MARGIN_L + seconds * _PX_PER_SEC

    def _seconds_at(self, x_content: float) -> float:
        return max(0.0, (x_content - self._pad - _MARGIN_L) / _PX_PER_SEC)

    # -------------------------------------------------------------- geometria
    def _recompute_staff(self) -> None:
        h = max(self._canvas.winfo_height(), 80)
        # gap entre lineas proporcional al alto (staff centrado verticalmente)
        gap = max(12, min(34, h / 9))
        top = h / 2 - 2 * gap
        self._lines = [top + i * gap for i in range(5)]
        self._lane_y = {
            "cymbal": top - gap * 0.9,
            "hihat": top,
            "tom": top + gap * 1.5,
            "snare": top + gap * 2,
            "kick": top + gap * 4,
        }
        self._note_r = int(max(4, gap / 2.4))

    # ----------------------------------------------------------------- dibujo
    def _redraw(self) -> None:
        c = self._canvas
        if c.winfo_height() <= 1:
            return
        self._recompute_staff()
        c.delete("all")
        self._note_items.clear()
        self._hl_state.clear()
        view_w = max(c.winfo_width(), 1)
        self._pad = view_w // 2
        total_w = self._width + 2 * self._pad
        c.configure(scrollregion=(0, 0, total_w, c.winfo_height()))

        lines, r = self._lines, self._note_r
        y0, y1 = lines[0], lines[-1]
        x_start = self._pad + _MARGIN_L
        x_end = self._pad + self._width

        for y in lines:
            c.create_line(x_start, y, x_end, y, fill=_COL_STAFF)

        # Clave de percusion (dos barras gruesas)
        c.create_line(x_start - 18, y0, x_start - 18, y1, fill=_COL_STAFF, width=4)
        c.create_line(x_start - 10, y0, x_start - 10, y1, fill=_COL_STAFF, width=4)

        # Barras de compas: en beats reales si los hay; si no, rejilla constante
        if self._bar_times:
            for t in self._bar_times:
                if 0.05 <= t < self._duration:
                    x = self._x(t)
                    c.create_line(x, y0 - 8, x, y1 + 8, fill=_COL_BAR)
        elif self._bar_seconds > 0.05:
            # Fase anclada en _bar_offset pero cubriendo TODA la cancion
            # (tambien los compases anteriores a la marca).
            t = self._bar_offset % self._bar_seconds
            if t < 0.05:  # no dibujar una barra pegada a la clave
                t += self._bar_seconds
            while t < self._duration:
                x = self._x(t)
                c.create_line(x, y0 - 8, x, y1 + 8, fill=_COL_BAR)
                t += self._bar_seconds

        # Cabezas de nota
        for seconds, category in self._events:
            y = self._lane_y.get(category, lines[2])
            style = _LANE_STYLE.get(category, "o")
            x = self._x(seconds)
            if style == "x":
                item = c.create_text(x, y, text="✕", fill=_COL_NOTE,
                                     font=("Arial", int(r * 2.2), "bold"))
            else:
                item = c.create_oval(x - r, y - r, x + r, y + r,
                                     fill=_COL_NOTE, outline="")
            self._note_items.append((item, seconds))
            self._hl_state[item] = False

        self._cursor = c.create_line(
            _MARGIN_L, y0 - 18, _MARGIN_L, y1 + 18, fill=_COL_CURSOR, width=3
        )
        self.set_cursor_seconds(self._cursor_seconds)

    # ----------------------------------------------------------------- cursor
    def set_cursor_seconds(self, seconds: float) -> None:
        self._cursor_seconds = seconds
        if self._cursor is None or not self._lines:
            return
        c = self._canvas
        x = self._x(seconds)
        c.coords(self._cursor, x, self._lines[0] - 18, x, self._lines[-1] + 18)

        for item, sec in self._note_items:
            on = abs(sec - seconds) <= 0.06
            if on != self._hl_state.get(item, False):
                self._hl_state[item] = on
                c.itemconfigure(item, fill=_COL_NOTE_HL if on else _COL_NOTE)

        # Cursor clavado en el centro: gracias al relleno lateral, CUALQUIER
        # instante (incluido el inicio) puede quedar exactamente en el medio.
        view_w = c.winfo_width()
        total_w = self._width + 2 * self._pad
        if view_w > 1 and total_w > view_w:
            target = (x - view_w / 2) / total_w
            c.xview_moveto(min(max(target, 0.0), 1.0))

    def reset_cursor(self) -> None:
        self.set_cursor_seconds(0.0)

    # ------------------------------------------------------------------ seek
    def _on_click(self, event) -> None:
        if self._on_seek is None or self._duration <= 0:
            return
        x_content = self._canvas.canvasx(event.x)
        seconds = min(self._seconds_at(x_content), self._duration)
        # Iman a la nota: si el clic cae cerca de un punto, saltar EXACTAMENTE
        # a su centro (asi el cursor y las barras de compas lo atraviesan).
        if self._events:
            nearest = min((sec for sec, _ in self._events),
                          key=lambda s: abs(s - seconds))
            if abs(nearest - seconds) * _PX_PER_SEC <= 18:  # radio del iman (px)
                seconds = nearest
        self._on_seek(seconds)
