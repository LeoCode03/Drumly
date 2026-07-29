"""
score_view.py — Lienzo de partitura de bateria para seguir en tiempo real.

Pentagrama de 5 lineas donde el eje X es el TIEMPO (segundos reales del audio) y
los carriles verticales siguen la NOTACION REAL de bateria (misma posicion que
en el PDF): platillo y hi-hat con aspa encima del pentagrama, tom en el 1er
espacio, caja en el 2do espacio, bombo en el espacio inferior. Separacion entre
carriles >= 1 gap, con el gap escalando con el alto de la ventana: caja y tom
son distinguibles a distancia. El tom ademas usa cabeza hueca (forma, no solo
posicion). Una leyenda fija a la izquierda nombra cada carril.

- Cursor clavado en el centro (relleno lateral de media pantalla).
- Zoom horizontal (zoom_in/zoom_out/set_px): redobles legibles.
- Barras de compas en beats reales (set_bars) o rejilla constante (set_grid).
- Clic con iman a la nota mas cercana -> seek exacto via callback.

Como notas y cursor usan la misma funcion tiempo->X, la sincronia es exacta.
"""

from __future__ import annotations

import bisect
from typing import Callable, Dict, List, Optional, Set, Tuple

import customtkinter as ctk

from ui import theme

# Estilo de cabeza por carril: 'x' = aspa (platillos/hi-hat),
# 'o' = cabeza rellena (tambores), 'o2' = cabeza hueca (tom).
_LANE_STYLE = {"cymbal": "x", "hihat": "x", "tom": "o2", "snare": "o", "kick": "o"}
_LANE_LABEL = {
    "cymbal": "Platillo", "hihat": "Hi-hat", "tom": "Tom",
    "snare": "Caja", "kick": "Bombo",
}
# Posicion vertical en "gaps" respecto a la linea superior del pentagrama
# (notacion real de bateria; separacion minima entre carriles = 1 gap).
_LANE_GAPS = {
    "cymbal": -1.5,   # encima del pentagrama
    "hihat": -0.5,    # justo sobre la linea superior
    "tom": 0.5,       # 1er espacio
    "snare": 1.5,     # 2do espacio
    "kick": 3.5,      # espacio inferior
}

_MARGIN_L = 84        # espacio para clave + leyenda
_PX_DEFAULT = 200     # ancho temporal por defecto (px por segundo)
_PX_MIN, _PX_MAX = 60, 480

_COL_STAFF = theme.STAFF
_COL_NOTE = theme.NOTE
_COL_NOTE_HL = theme.NOTE_HL
_COL_CURSOR = theme.CURSOR
_COL_BAR = theme.BARLINE
_COL_BG = theme.SURFACE0


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
        self._px = _PX_DEFAULT         # zoom horizontal (px por segundo)
        self._width = _MARGIN_L
        self._note_items: List[Tuple[int, float]] = []  # ordenados por tiempo
        self._note_secs: List[float] = []               # paralelo, para bisect
        self._cursor = None
        self._hl_on: Set[int] = set()   # indices de notas resaltadas ahora
        self._cursor_seconds = 0.0
        self._cursor_drawn = -1.0       # ultimo instante dibujado (early-return)
        self._on_seek: Optional[Callable[[float], None]] = None

        # Geometria del pentagrama (se recalcula segun el alto)
        self._lines: List[float] = []
        self._lane_y: Dict[str, float] = {}
        self._note_r = 6
        # Relleno lateral = media pantalla: permite centrar EXACTAMENTE cualquier
        # instante (incluido el 0) -> el cursor queda clavado en el medio y la
        # partitura se desplaza por debajo.
        self._pad = 0

        # Leyenda de carriles (labels fijos sobre el lienzo, no se desplazan)
        self._legend: Dict[str, ctk.CTkLabel] = {}
        for lane, name in _LANE_LABEL.items():
            self._legend[lane] = ctk.CTkLabel(
                self, text=name, text_color=theme.TEXT_FAINT,
                font=theme.font(12), fg_color=_COL_BG, height=14,
            )

        self._resize_after = None
        self._canvas.bind("<Configure>", self._on_configure)
        self._canvas.bind("<Button-1>", self._on_click)
        self._canvas.bind("<B1-Motion>", self._on_click)

    def _on_configure(self, _event) -> None:
        # Debounce: al redimensionar llegan rafagas de eventos; reconstruir el
        # lienzo completo una sola vez, 80 ms despues del ultimo.
        if self._resize_after is not None:
            self.after_cancel(self._resize_after)
        self._resize_after = self.after(80, self._redraw)

    # ------------------------------------------------------------------ datos
    def set_events(
        self, events: List[Tuple[float, str]], duration: float,
        bpm: Optional[int] = None, beats_per_bar: int = 4,
        beat_offset: float = 0.0,
    ) -> None:
        self._events = events
        self._duration = max(duration, (events[-1][0] if events else 0.0) + 1.0)
        self._bar_offset = max(0.0, beat_offset)
        if bpm and bpm > 0:
            self._bar_seconds = beats_per_bar * 60.0 / bpm
        else:
            self._bar_seconds = 0.0
        self._recompute_width()
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

    # ------------------------------------------------------------------- zoom
    @property
    def px_per_sec(self) -> float:
        return self._px

    def set_px(self, px: float) -> None:
        """Fija el zoom horizontal (px por segundo) y redibuja centrado."""
        px = min(max(px, _PX_MIN), _PX_MAX)
        if abs(px - self._px) < 0.5:
            return
        self._px = px
        self._recompute_width()
        self._redraw()

    def zoom_in(self) -> None:
        self.set_px(self._px * 1.25)

    def zoom_out(self) -> None:
        self.set_px(self._px / 1.25)

    def _recompute_width(self) -> None:
        self._width = int(_MARGIN_L + self._duration * self._px + 80)

    # ------------------------------------------------------------- geometria
    def _x(self, seconds: float) -> float:
        return self._pad + _MARGIN_L + seconds * self._px

    def _seconds_at(self, x_content: float) -> float:
        return max(0.0, (x_content - self._pad - _MARGIN_L) / self._px)

    def _recompute_staff(self) -> None:
        h = max(self._canvas.winfo_height(), 80)
        # Gap proporcional al alto: los carriles crecen con la ventana.
        # (El pentagrama ocupa de -1.5g a +4g -> 5.5 gaps + margenes.)
        gap = max(14, min(44, h / 7.5))
        top = h / 2 - 1.2 * gap  # centrado optico del rango usado
        self._lines = [top + i * gap for i in range(5)]
        self._lane_y = {lane: top + g * gap for lane, g in _LANE_GAPS.items()}
        # Diametro (2r ~ 0.78*gap) < separacion minima entre carriles (1*gap):
        # las cabezas de carriles vecinos ya no pueden solaparse.
        self._note_r = int(max(5, gap / 2.55))

    # ----------------------------------------------------------------- dibujo
    def _redraw(self) -> None:
        c = self._canvas
        if c.winfo_height() <= 1:
            return
        self._recompute_staff()
        c.delete("all")
        self._note_items.clear()
        self._note_secs.clear()
        self._hl_on.clear()
        self._cursor_drawn = -1.0
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
        top_ext = self._lane_y["cymbal"] - r - 4
        if self._bar_times:
            for t in self._bar_times:
                if 0.05 <= t < self._duration:
                    x = self._x(t)
                    c.create_line(x, top_ext, x, y1 + 8, fill=_COL_BAR)
        elif self._bar_seconds > 0.05:
            # Fase anclada en _bar_offset pero cubriendo TODA la cancion
            # (tambien los compases anteriores a la marca).
            t = self._bar_offset % self._bar_seconds
            if t < 0.05:  # no dibujar una barra pegada a la clave
                t += self._bar_seconds
            while t < self._duration:
                x = self._x(t)
                c.create_line(x, top_ext, x, y1 + 8, fill=_COL_BAR)
                t += self._bar_seconds

        # Cabezas de nota (aspa=platillos, hueca=tom, rellena=tambores)
        for seconds, category in self._events:
            y = self._lane_y.get(category, lines[2])
            style = _LANE_STYLE.get(category, "o")
            x = self._x(seconds)
            if style == "x":
                item = c.create_text(x, y, text="✕", fill=_COL_NOTE,
                                     font=("Arial", int(r * 2.1), "bold"))
            elif style == "o2":
                item = c.create_oval(x - r, y - r, x + r, y + r,
                                     outline=_COL_NOTE, width=2, fill=_COL_BG)
            else:
                item = c.create_oval(x - r, y - r, x + r, y + r,
                                     fill=_COL_NOTE, outline="")
            self._note_items.append((item, seconds))
            self._note_secs.append(seconds)

        self._cursor = c.create_line(
            _MARGIN_L, top_ext - 6, _MARGIN_L, y1 + 18, fill=_COL_CURSOR, width=3
        )
        self._place_legend()
        self.set_cursor_seconds(self._cursor_seconds)

    def _place_legend(self) -> None:
        """Etiquetas de carril fijas a la izquierda (no se desplazan con el scroll)."""
        for lane, label in self._legend.items():
            y = self._lane_y.get(lane)
            if y is None:
                continue
            label.place(x=4, y=y - 8)
            label.lift()

    # ----------------------------------------------------------------- cursor
    def set_cursor_seconds(self, seconds: float) -> None:
        self._cursor_seconds = seconds
        if self._cursor is None or not self._lines:
            return
        # Early-return: en pausa el tick manda el mismo instante 30 veces/s;
        # no hay nada que mover ni resaltar.
        if abs(seconds - self._cursor_drawn) < 1e-9:
            return
        self._cursor_drawn = seconds
        c = self._canvas
        x = self._x(seconds)
        top_ext = self._lane_y["cymbal"] - self._note_r - 10
        c.coords(self._cursor, x, top_ext, x, self._lines[-1] + 18)

        # Resaltado O(log n): solo la ventana [t-0.06, t+0.06] via bisect, mas
        # apagar las que salieron de ella (antes se recorrian TODAS las notas
        # en cada tick).
        lo = bisect.bisect_left(self._note_secs, seconds - 0.06)
        hi = bisect.bisect_right(self._note_secs, seconds + 0.06)
        new_on = set(range(lo, hi))
        for i in self._hl_on ^ new_on:  # las que cambian de estado
            item = self._note_items[i][0]
            color = _COL_NOTE_HL if i in new_on else _COL_NOTE
            if c.type(item) == "oval" and c.itemcget(item, "fill") in (_COL_BG, ""):
                c.itemconfigure(item, outline=color)  # tom hueco
            else:
                c.itemconfigure(item, fill=color)
        self._hl_on = new_on

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
            if abs(nearest - seconds) * self._px <= 18:  # radio del iman (px)
                seconds = nearest
        self._on_seek(seconds)
