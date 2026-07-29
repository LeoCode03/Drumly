"""
practice.py — Ventana "Practicar": reproduce la bateria (y opcionalmente el resto
de la mezcla) y sigue la partitura en tiempo real con un cursor, al BPM/compas que
elijas.

Modo A+B:
  - BPM y compas detectados se muestran y se pueden cambiar.
  - Al cambiar el BPM, las pistas se estiran al nuevo tempo SIN cambiar el tono
    (librosa.effects.time_stretch) y el cursor las sigue sincronizado.
  - Se mezclan DOS pistas con volumen independiente en vivo: Bateria y "Otros"
    (sin bateria), para poder guiarse con voces/instrumentos. Los volumenes
    iniciales vienen del mezclador del panel principal.
  - Retroceder/avanzar en tiempo real: barra de progreso + clic en la partitura.
  - Metronomo opcional (pista de click aparte).

Layout: la partitura ocupa el centro; controles abajo, simetricos.

Sincronia: el lienzo dibuja las notas por segundos reales del audio original; el
cursor se calcula desde la posicion reproducida -> siempre caen juntos. La fraccion
de avance es invariante al tempo (se conserva al re-estirar).
"""

from __future__ import annotations

import threading
from typing import Callable, List, Optional

import customtkinter as ctk
import numpy as np

from pipeline.score import extract_drum_events
from ui import theme
from ui.player import MixPlayer
from ui.score_view import ScoreCanvas

ACCENT = theme.ACCENT
ACCENT_HOVER = theme.ACCENT_HOVER
_PRACTICE_SR = 22050
_METERS = ["2/4", "3/4", "4/4"]
_BPM_MIN = 40
_BPM_MAX = 220
_VOL_MIN = 1
_VOL_MAX = 150

# Indices de pista en el MixPlayer
_T_DRUMS, _T_OTHERS, _T_CLICK = 0, 1, 2


def _fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _click_wave(sr: int, freq: float, gain: float) -> np.ndarray:
    click_len = int(sr * 0.03)
    t = np.linspace(0, 0.03, click_len, endpoint=False)
    return (gain * np.sin(2 * np.pi * freq * t) * np.exp(-t * 60)).astype("float32")


def _make_click_track(
    n_frames: int, sr: int, bpm: float, beats_per_bar: int = 4,
    accent: bool = False, offset_seconds: float = 0.0,
    click_times: Optional[List[float]] = None,
) -> np.ndarray:
    """
    Click de metronomo (mono).

    `click_times`: si se pasa, cada click cae EXACTAMENTE en esos instantes (los
    beats reales de la cancion, ya estirados al tempo elegido). Asi el metronomo
    sigue a la banda aunque el tempo fluctue (en vivo). El primer instante de la
    lista se toma como tiempo 1 del compas.

    Sin `click_times`: rejilla constante cada 60/bpm s desde `offset_seconds`
    (instante del primer tiempo).

    Si `accent` es True, el primer tiempo de cada compas suena mas fuerte y mas
    agudo, como guia del inicio de compas.
    """
    track = np.zeros(n_frames, dtype="float32")
    if n_frames <= 0:
        return track

    click_normal = _click_wave(sr, 1200, 0.5)
    click_accent = _click_wave(sr, 1800, 0.9) if accent else click_normal

    if click_times:
        starts = [int(t * sr) for t in click_times if 0.0 <= t * sr < n_frames]
    else:
        if bpm <= 0:
            return track
        interval = int(sr * 60.0 / bpm)
        if interval <= 0:
            return track
        first = max(0, int(offset_seconds * sr))
        starts = list(range(first, n_frames, interval))

    for beat, start in enumerate(starts):
        click = click_accent if (accent and beat % beats_per_bar == 0) else click_normal
        end = min(start + len(click), n_frames)
        track[start:end] += click[: end - start]
    return track


def _stretch(y: np.ndarray, rate: float) -> np.ndarray:
    if abs(rate - 1.0) < 1e-3:
        return y.copy()
    import librosa
    return librosa.effects.time_stretch(y, rate=rate).astype("float32")


class PracticeWindow(ctk.CTkToplevel):
    def __init__(self, master, midi_path: str, drums_wav: str,
                 bpm: Optional[int], song_name: str, beats_per_bar: int = 4,
                 no_drums_wav: Optional[str] = None,
                 drums_gain: float = 1.0, no_drums_gain: float = 1.0,
                 beat_offset: float = 0.0,
                 beat_times: Optional[List[float]] = None,
                 on_apply: Optional[Callable] = None) -> None:
        super().__init__(master, fg_color=theme.SURFACE1)
        self.title(f"Practicar — {song_name}")
        self.geometry("1100x700")
        self.minsize(820, 560)

        self._midi_path = midi_path
        self._drums_wav = drums_wav
        self._no_drums_wav = no_drums_wav
        self.bpm0 = float(bpm) if bpm else 120.0
        self.target_bpm = self.bpm0     # tempo pedido por el slider
        self.rendered_bpm = self.bpm0   # tempo al que esta ESTIRADO el audio actual
        self._bpm_after = None          # id del re-render con debounce
        self.beats_per_bar = beats_per_bar if beats_per_bar in (2, 3, 4) else 4
        self.beat_offset = max(0.0, float(beat_offset))  # inicio del compas 1 (s)
        # Pulsos reales de la cancion (beat tracking); si estan, el metronomo y
        # las barras de compas siguen el tempo REAL aunque fluctue (en vivo).
        self.beat_times: List[float] = sorted(beat_times) if beat_times else []
        # Callback para aplicar los ajustes manuales (inicio de compas, compas)
        # a la partitura PDF: on_apply(beat_offset, beats_per_bar, status_cb).
        self._on_apply = on_apply

        self.gain_drums = float(drums_gain)
        self.gain_others = float(no_drums_gain)
        self.gain_click = 1.0   # volumen del metronomo (cuando esta activado)

        # Pulso del metronomo: "cancion" = beats reales detectados; "manual" =
        # BPM fijo elegido por el usuario (el click suena a ese ritmo constante).
        self._pulse_mode = "cancion"
        self.custom_bpm = float(int(self.bpm0))

        self._orig_drums: Optional[np.ndarray] = None
        self._orig_others: Optional[np.ndarray] = None
        self._orig_sr = _PRACTICE_SR
        self._orig_duration = 0.0
        self._events_sec: List[float] = []  # onsets de las notas dibujadas (s)
        self._metronome = ctk.BooleanVar(value=False)
        self._metronome_accent = ctk.BooleanVar(value=True)
        self._busy = False
        self._pending_render = False  # cambio recibido mientras _busy
        self._user_seeking = False

        self.player = MixPlayer()

        self._build_widgets()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._set_status("Cargando audio...")
        threading.Thread(target=self._load_worker, daemon=True).start()
        self.after(33, self._tick)

    # ---------------------------------------------------------------- widgets
    def _build_widgets(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)  # la partitura se estira

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 4))
        ctk.CTkLabel(
            header, text="🥁 Practicar en tiempo real",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(side="left")

        # Pulso del metronomo: beats reales de la cancion o BPM fijo manual.
        pulse_box = ctk.CTkFrame(header, fg_color="transparent")
        pulse_box.pack(side="left", padx=(18, 0))
        ctk.CTkLabel(pulse_box, text="Pulso", text_color=theme.TEXT_MUTED).pack(
            side="left", padx=(0, 6)
        )
        self.pulse_seg = ctk.CTkSegmentedButton(
            pulse_box, values=["Cancion", "Manual"], command=self._on_pulse_mode,
            height=28,
        )
        self.pulse_seg.set("Cancion")
        self.pulse_seg.pack(side="left", padx=(0, 6))
        self.pulse_entry = ctk.CTkEntry(pulse_box, width=52, height=28,
                                        justify="center")
        self.pulse_entry.insert(0, str(int(self.custom_bpm)))
        self.pulse_entry.pack(side="left")
        self.pulse_entry.bind("<Return>", self._on_custom_bpm_commit)
        self.pulse_entry.bind("<FocusOut>", self._on_custom_bpm_commit)
        ctk.CTkLabel(pulse_box, text="BPM", text_color=theme.TEXT_FAINT).pack(
            side="left", padx=(4, 0)
        )

        # Anclaje manual: pausa donde empieza el compas 1 y marcalo; luego
        # aplica ese ajuste (y el compas elegido) a la partitura PDF.
        self.apply_btn = ctk.CTkButton(
            header, text="📄 Aplicar a la partitura", height=30,
            command=self._on_apply_score,
            fg_color=theme.SURFACE3, hover_color=theme.SURFACE4, state="disabled",
        )
        self.apply_btn.pack(side="right", padx=(8, 0))
        self.mark_btn = ctk.CTkButton(
            header, text="📍 Marcar aqui el inicio del compas 1", height=30,
            command=self._on_mark_start,
            fg_color=theme.SURFACE3, hover_color=theme.SURFACE4, state="disabled",
        )
        self.mark_btn.pack(side="right")

        self.score = ScoreCanvas(self, fg_color="transparent")
        self.score.grid(row=1, column=0, sticky="nsew", padx=16, pady=6)
        self.score.set_seek_callback(self._seek_seconds)

        # --- Volumen de pistas (mezcla) ---
        vol = ctk.CTkFrame(self, fg_color="transparent")
        vol.grid(row=2, column=0, sticky="ew", padx=16, pady=(2, 0))
        vol.grid_columnconfigure(0, weight=1, uniform="vol")
        vol.grid_columnconfigure(1, weight=1, uniform="vol")
        vol.grid_columnconfigure(2, weight=1, uniform="vol")
        self._build_vol_slider(vol, 0, "🥁 Bateria", self.gain_drums, self._on_vol_drums)
        self._build_vol_slider(vol, 1, "🎵 Otros", self.gain_others, self._on_vol_others)
        self._build_vol_slider(vol, 2, "⏱ Metronomo", self.gain_click, self._on_vol_click)

        # --- Barra de progreso + tiempos ---
        seekbox = ctk.CTkFrame(self, fg_color="transparent")
        seekbox.grid(row=3, column=0, sticky="ew", padx=16, pady=(6, 0))
        seekbox.grid_columnconfigure(1, weight=1)
        self.time_cur = ctk.CTkLabel(seekbox, text="00:00", text_color="gray70", width=52)
        self.time_cur.grid(row=0, column=0)
        self.seek = ctk.CTkSlider(seekbox, from_=0, to=1, command=self._on_seek_slider)
        self.seek.set(0)
        self.seek.grid(row=0, column=1, sticky="ew", padx=8)
        self.seek.bind("<ButtonPress-1>", lambda e: setattr(self, "_user_seeking", True))
        self.seek.bind("<ButtonRelease-1>", self._on_seek_release)
        self.time_total = ctk.CTkLabel(seekbox, text="00:00", text_color="gray70", width=52)
        self.time_total.grid(row=0, column=2)

        # --- Controles (abajo, simetricos: BPM | Play | Compas/Metronomo) ---
        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.grid(row=4, column=0, sticky="ew", padx=16, pady=(8, 12))
        controls.grid_columnconfigure(0, weight=1, uniform="ctl")
        controls.grid_columnconfigure(1, weight=0)
        controls.grid_columnconfigure(2, weight=1, uniform="ctl")

        left = ctk.CTkFrame(controls, fg_color="transparent")
        left.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        row1 = ctk.CTkFrame(left, fg_color="transparent")
        row1.pack(fill="x")
        ctk.CTkLabel(row1, text="⏱ Tempo", text_color=theme.TEXT_MUTED).pack(side="left")
        self.bpm_value = ctk.CTkLabel(
            row1, text=f"{int(self.bpm0)} BPM", font=ctk.CTkFont(size=15, weight="bold")
        )
        self.bpm_value.pack(side="right")
        self.bpm_slider = ctk.CTkSlider(
            left, from_=_BPM_MIN, to=_BPM_MAX,
            number_of_steps=_BPM_MAX - _BPM_MIN, command=self._on_bpm_slide,
        )
        self.bpm_slider.set(min(max(self.bpm0, _BPM_MIN), _BPM_MAX))
        self.bpm_slider.pack(fill="x", pady=(4, 4))
        ctk.CTkButton(left, text="Reset tempo", height=26, command=self._reset_bpm).pack()

        center = ctk.CTkFrame(controls, fg_color="transparent")
        center.grid(row=0, column=1, padx=18)
        self.restart_btn = ctk.CTkButton(
            center, text="⏮", width=44, height=44, corner_radius=22,
            command=self._on_restart, font=ctk.CTkFont(size=17),
            fg_color=theme.SURFACE3, hover_color=theme.SURFACE4, state="disabled",
        )
        self.restart_btn.pack(side="left", padx=(0, 8))
        self.back5_btn = ctk.CTkButton(
            center, text="⏪ 5s", width=56, height=44, corner_radius=22,
            command=self._on_back5, font=ctk.CTkFont(size=14),
            fg_color=theme.SURFACE3, hover_color=theme.SURFACE4, state="disabled",
        )
        self.back5_btn.pack(side="left", padx=(0, 12))
        self.play_btn = ctk.CTkButton(
            center, text="▶", width=72, height=72, corner_radius=36,
            command=self._on_play_pause, font=ctk.CTkFont(size=26),
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color=theme.ON_ACCENT, state="disabled",
        )
        self.play_btn.pack(side="left")

        right = ctk.CTkFrame(controls, fg_color="transparent")
        right.grid(row=0, column=2, sticky="ew", padx=(12, 0))
        mrow = ctk.CTkFrame(right, fg_color="transparent")
        mrow.pack(fill="x")
        ctk.CTkLabel(mrow, text="Compas", text_color=theme.TEXT_MUTED).pack(side="left")
        self.meter_menu = ctk.CTkOptionMenu(
            mrow, values=_METERS, width=80, command=self._on_meter_change
        )
        self.meter_menu.set(f"{self.beats_per_bar}/4")
        self.meter_menu.pack(side="right")
        ctk.CTkCheckBox(
            right, text="Metronomo", variable=self._metronome,
            command=self._on_metronome_toggle,
        ).pack(anchor="e", pady=(10, 0))
        ctk.CTkCheckBox(
            right, text="Acentuar 1er tiempo", variable=self._metronome_accent,
            command=self._on_metronome_accent_toggle,
        ).pack(anchor="e", pady=(4, 0))

        self.status = ctk.CTkLabel(self, text="", text_color=theme.TEXT_FAINT)
        self.status.grid(row=5, column=0, pady=(0, 8))

    def _build_vol_slider(self, parent, col, name, gain, command) -> None:
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.grid(row=0, column=col, sticky="ew", padx=6)
        ctk.CTkLabel(box, text=name, width=90, anchor="w", text_color=theme.TEXT_MUTED).pack(
            side="left"
        )
        slider = ctk.CTkSlider(
            box, from_=_VOL_MIN, to=_VOL_MAX,
            number_of_steps=_VOL_MAX - _VOL_MIN, command=command,
        )
        slider.set(min(max(gain * 100, _VOL_MIN), _VOL_MAX))
        slider.pack(side="left", fill="x", expand=True, padx=(8, 0))

    # ------------------------------------------------------------------ carga
    def _load_worker(self) -> None:
        try:
            import librosa

            events, _dur = extract_drum_events(self._midi_path)
            drums, sr = librosa.load(self._drums_wav, sr=_PRACTICE_SR, mono=True)
            others = np.zeros_like(drums)
            if self._no_drums_wav:
                try:
                    others, _ = librosa.load(self._no_drums_wav, sr=_PRACTICE_SR, mono=True)
                except Exception:  # noqa: BLE001
                    others = np.zeros_like(drums)
            self._orig_drums = drums.astype("float32")
            self._orig_others = others.astype("float32")
            self._orig_sr = sr
            self._orig_duration = len(drums) / sr
            self.after(0, lambda: self._on_loaded(events))
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            self.after(0, lambda: self._set_status(f"Error al cargar: {msg}"))

    def _on_loaded(self, events) -> None:
        self._events_sec = sorted(sec for sec, _ in events)
        self.score.set_events(
            events, self._orig_duration, bpm=int(self.bpm0),
            beats_per_bar=self.beats_per_bar, beat_offset=self.beat_offset,
        )
        self._update_bars()
        self.time_total.configure(text=_fmt_time(self._orig_duration))
        self._render_buffer(keep_fraction=0.0)
        self.play_btn.configure(state="normal")
        self.restart_btn.configure(state="normal")
        self.back5_btn.configure(state="normal")
        self.mark_btn.configure(state="normal")
        if self._on_apply is not None:
            self.apply_btn.configure(state="normal")
        self._set_status("" if self.player.available else "Sin dispositivo de audio.")

    # ------------------------------------------------- compases / anclaje manual
    def _anchor_index(self) -> int:
        """Indice del beat real mas cercano al inicio marcado del compas 1."""
        if not self.beat_times:
            return 0
        return min(
            range(len(self.beat_times)),
            key=lambda i: abs(self.beat_times[i] - self.beat_offset),
        )

    def _update_bars(self) -> None:
        """
        Redibuja las barras de compas segun el modo de pulso:
        - Manual: rejilla CONSTANTE al BPM elegido, anclada en la marca (misma
          rejilla que el click del metronomo, la que el usuario valido de oido).
        - Cancion: beats reales, desplazados para que la barra del compas 1
          atraviese EXACTAMENTE el punto marcado (el beat detectado puede estar
          unas centesimas al costado de la nota real).
        """
        if self._pulse_mode == "manual":
            self.score.set_grid(int(self.custom_bpm), self.beats_per_bar,
                                self.beat_offset)
        elif self.beat_times:
            a = self._anchor_index()
            delta = self.beat_offset - self.beat_times[a]
            idxs = range(a % self.beats_per_bar, len(self.beat_times), self.beats_per_bar)
            self.score.set_bars([self.beat_times[i] + delta for i in idxs])
        else:
            self.score.set_grid(int(self.bpm0), self.beats_per_bar, self.beat_offset)

    # --------------------------------------------------------- tempo / buffer
    def _current_gains(self) -> List[float]:
        return [self.gain_drums, self.gain_others,
                self.gain_click if self._metronome.get() else 0.0]

    def _render_buffer(self, keep_fraction: float) -> None:
        assert self._orig_drums is not None and self._orig_others is not None
        # Capturar el tempo pedido UNA sola vez. El estirado tarda segundos y
        # corre en un hilo: si el usuario sigue moviendo el slider mientras
        # tanto, leer self.target_bpm varias veces dejaria audio, click y
        # rendered_bpm a tempos DISTINTOS (partitura a otra velocidad que la
        # musica, sin auto-correccion posible).
        tempo = self.target_bpm
        rate = tempo / self.bpm0
        drums = _stretch(self._orig_drums, rate)
        others = _stretch(self._orig_others, rate)
        n = max(len(drums), len(others))
        # Click del metronomo segun el modo de pulso:
        #  - "manual": BPM fijo elegido por el usuario (ritmo constante).
        #  - "cancion": beats REALES (siguen a la banda aunque el tempo fluctue),
        #    estirados igual que el audio; fallback a rejilla constante.
        click_times: Optional[List[float]] = None
        click_bpm = tempo
        if self._pulse_mode == "manual":
            click_bpm = self.custom_bpm
        elif self.beat_times:
            # Mismo desplazamiento que las barras: el click del "1" cae
            # exactamente sobre el punto marcado como inicio del compas.
            a = self._anchor_index()
            delta = self.beat_offset - self.beat_times[a]
            first = a % self.beats_per_bar
            click_times = [(t + delta) / rate for t in self.beat_times[first:]]
        click = _make_click_track(
            n, self._orig_sr, click_bpm,
            beats_per_bar=self.beats_per_bar, accent=self._metronome_accent.get(),
            # El primer tiempo tambien se estira con el audio.
            offset_seconds=self.beat_offset / rate,
            click_times=click_times,
        )
        self.player.set_tracks(
            [drums, others, click], self._orig_sr,
            gains=self._current_gains(), keep_fraction=keep_fraction,
        )
        # A partir de ahora el audio suena a este tempo: el cursor debe usarlo.
        self.rendered_bpm = tempo

    def _apply_tempo_async(self) -> None:
        if self._orig_drums is None:
            return
        if self._busy:
            # Ya hay un estirado en curso: recordar que quedo un cambio
            # pendiente (tempo, compas o acento) para re-aplicarlo al terminar.
            self._pending_render = True
            return
        self._busy = True
        was_playing = self.player.is_playing
        frac = self.player.fraction()
        self.player.pause()
        self._set_status("Ajustando tempo...")

        def work() -> None:
            try:
                self._render_buffer(keep_fraction=frac)
                self.after(0, lambda: self._after_tempo(was_playing))
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                self.after(0, lambda: (self._set_status(f"Error: {msg}"),
                                       setattr(self, "_busy", False)))

        threading.Thread(target=work, daemon=True).start()

    def _after_tempo(self, resume: bool) -> None:
        self._busy = False
        self._set_status("")
        if resume:
            self.player.play()
            self.play_btn.configure(text="⏸")
        # Si el usuario cambio algo durante el re-render (siguio moviendo el
        # slider, o cambio compas/acento), re-aplicamos el ultimo estado pedido.
        if self._pending_render or abs(self.target_bpm - self.rendered_bpm) >= 1.0:
            self._pending_render = False
            self._bpm_after = self.after(80, self._apply_tempo_async)

    # ----------------------------------------------------------------- eventos
    def _on_vol_drums(self, value: float) -> None:
        self.gain_drums = value / 100.0
        self.player.set_gain(_T_DRUMS, self.gain_drums)

    def _on_vol_others(self, value: float) -> None:
        self.gain_others = value / 100.0
        self.player.set_gain(_T_OTHERS, self.gain_others)

    def _on_vol_click(self, value: float) -> None:
        self.gain_click = value / 100.0
        # Solo suena si el metronomo esta activado.
        if self._metronome.get():
            self.player.set_gain(_T_CLICK, self.gain_click)

    def _on_bpm_slide(self, value: float) -> None:
        self.target_bpm = float(value)
        self.bpm_value.configure(text=f"{int(value)} BPM")
        # Re-render con debounce: al dejar de mover el slider, estira el audio.
        if self._bpm_after is not None:
            self.after_cancel(self._bpm_after)
        self._bpm_after = self.after(350, self._apply_tempo_async)

    def _reset_bpm(self) -> None:
        self.target_bpm = self.bpm0
        # El "reset" vuelve al tempo REAL de la cancion aunque supere el rango
        # del slider (1-150); el slider solo se clampea visualmente.
        self.bpm_slider.set(min(max(self.bpm0, _BPM_MIN), _BPM_MAX))
        self.bpm_value.configure(text=f"{int(self.bpm0)} BPM")
        self._apply_tempo_async()

    def _on_meter_change(self, value: str) -> None:
        self.beats_per_bar = int(value.split("/")[0])
        self._update_bars()
        # El patron de acento del click depende del compas: regenerarlo.
        self._apply_tempo_async()

    def _on_mark_start(self) -> None:
        """📍 Marca la posicion actual del cursor como inicio del compas 1."""
        if self._orig_duration <= 0:
            return
        cur = self.player.fraction() * self._orig_duration
        # Prioridad: la NOTA mas cercana (el punto que el usuario ve y clico);
        # la barra del compas debe atravesar SU centro. Si no hay nota cerca,
        # ajustar al beat detectado mas cercano.
        note = min(self._events_sec, key=lambda t: abs(t - cur)) \
            if self._events_sec else None
        if note is not None and abs(note - cur) <= 0.15:
            cur = note
        elif self.beat_times:
            cur = min(self.beat_times, key=lambda t: abs(t - cur))
        self.beat_offset = max(0.0, cur)
        self._update_bars()
        self._apply_tempo_async()  # re-anclar el acento del metronomo
        self._set_status(
            f"Compas 1 marcado en {_fmt_time(self.beat_offset)} "
            f"({self.beat_offset:.2f}s). Usa '📄 Aplicar a la partitura' para "
            "regenerar el PDF con este inicio."
        )

    def _on_apply_score(self) -> None:
        """
        📄 Regenera la partitura PDF con el inicio de compas y compas elegidos.
        Si el pulso esta en Manual, la partitura se cuantiza con ESA rejilla
        (el BPM fijo que el usuario valido de oido), no con los beats detectados.
        """
        if self._on_apply is None:
            return
        self.apply_btn.configure(state="disabled")
        self._set_status("Regenerando partitura...")

        def status_cb(msg: str) -> None:
            if self.winfo_exists():
                self._set_status(msg)
                self.apply_btn.configure(state="normal")

        manual_bpm = int(self.custom_bpm) if self._pulse_mode == "manual" else None
        self._on_apply(self.beat_offset, self.beats_per_bar, status_cb, manual_bpm)

    def _on_metronome_toggle(self) -> None:
        # El click ya esta como pista aparte: solo cambiamos su volumen en vivo.
        self.player.set_gain(_T_CLICK, self.gain_click if self._metronome.get() else 0.0)

    def _on_pulse_mode(self, value: str) -> None:
        self._pulse_mode = "manual" if value == "Manual" else "cancion"
        self._update_bars()          # las barras siguen el pulso elegido
        self._apply_tempo_async()    # regenerar la pista de click

    def _on_custom_bpm_commit(self, _event=None) -> None:
        """Lee el BPM manual del cuadro de texto (20-300) y regenera el click."""
        text = self.pulse_entry.get().strip().replace(",", ".")
        try:
            value = float(text)
        except ValueError:
            value = self.custom_bpm  # entrada invalida: restaurar
        value = min(max(value, 20.0), 300.0)
        self.custom_bpm = value
        self.pulse_entry.delete(0, "end")
        self.pulse_entry.insert(0, str(int(value)))
        if self._pulse_mode == "manual":
            self._update_bars()
            self._apply_tempo_async()

    def _on_metronome_accent_toggle(self) -> None:
        self._apply_tempo_async()

    def _on_play_pause(self) -> None:
        if not self.player.loaded:
            return
        if self.player.is_playing:
            self.player.pause()
            self.play_btn.configure(text="▶")
        else:
            try:
                self.player.play()
                self.play_btn.configure(text="⏸")
            except Exception as exc:  # noqa: BLE001
                self._set_status(f"No se pudo reproducir: {exc}")

    def _on_restart(self) -> None:
        """⏮ Vuelve al inicio (sigue reproduciendo si estaba sonando)."""
        self._seek_seconds(0.0)

    def _on_back5(self) -> None:
        """⏪ Retrocede 5 segundos (en tiempo de la cancion original)."""
        if self._orig_duration <= 0:
            return
        cur = self.player.fraction() * self._orig_duration
        self._seek_seconds(max(0.0, cur - 5.0))

    # --- seek ---
    def _seek_seconds(self, original_seconds: float) -> None:
        if self._orig_duration <= 0:
            return
        self.player.seek_fraction(original_seconds / self._orig_duration)
        self.score.set_cursor_seconds(original_seconds)

    def _on_seek_slider(self, value: float) -> None:
        if self.player.loaded:
            self.player.seek_fraction(float(value))
            self.score.set_cursor_seconds(float(value) * self._orig_duration)

    def _on_seek_release(self, _event) -> None:
        self._user_seeking = False

    def _tick(self) -> None:
        if self.player.loaded:
            # Posicion que realmente SUENA = enviado al buffer menos la latencia
            # de salida (asi el cursor no va adelantado respecto al audio).
            # En PAUSA no hay audio "en vuelo": la posicion es exacta y restar
            # la latencia arrastraria el cursor fuera del punto clicado.
            lat = self.player.latency if self.player.is_playing else 0.0
            played = max(0.0, self.player.position() - lat)
            # El cursor sigue el tempo REAL del audio (rendered_bpm), no el del
            # slider, para que nunca se desincronice mientras se re-renderiza.
            orig_sec = played * (self.rendered_bpm / self.bpm0)
            self.score.set_cursor_seconds(orig_sec)
            self.time_cur.configure(text=_fmt_time(orig_sec))
            if not self._user_seeking:
                self.seek.set(self.player.fraction())
            if self.player.finished and not self.player.is_playing:
                self.play_btn.configure(text="▶")
        self.after(33, self._tick)

    # ----------------------------------------------------------------- helpers
    def _set_status(self, text: str) -> None:
        self.status.configure(text=text)

    def _on_close(self) -> None:
        self.player.close()
        self.destroy()
