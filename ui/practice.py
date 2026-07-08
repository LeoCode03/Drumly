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
from typing import List, Optional

import customtkinter as ctk
import numpy as np

from pipeline.score import extract_drum_events
from ui.player import MixPlayer
from ui.score_view import ScoreCanvas

ACCENT = "#1db954"
ACCENT_HOVER = "#17a347"
_PRACTICE_SR = 22050
_METERS = ["2/4", "3/4", "4/4"]

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
    n_frames: int, sr: int, bpm: float, beats_per_bar: int = 4, accent: bool = False,
) -> np.ndarray:
    """
    Click de metronomo (mono) cada negra al tempo `bpm`.

    Si `accent` es True, el primer tiempo de cada compas (negras/compas =
    `beats_per_bar`) suena mas fuerte y con un tono distinto (mas agudo), como
    guia del inicio de cada compas.
    """
    track = np.zeros(n_frames, dtype="float32")
    if bpm <= 0 or n_frames <= 0:
        return track
    interval = int(sr * 60.0 / bpm)
    if interval <= 0:
        return track

    click_normal = _click_wave(sr, 1200, 0.5)
    click_accent = _click_wave(sr, 1800, 0.9) if accent else click_normal

    beat = 0
    for start in range(0, n_frames, interval):
        click = click_accent if (accent and beat % beats_per_bar == 0) else click_normal
        end = min(start + len(click), n_frames)
        track[start:end] += click[: end - start]
        beat += 1
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
                 drums_gain: float = 1.0, no_drums_gain: float = 1.0) -> None:
        super().__init__(master)
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

        self.gain_drums = float(drums_gain)
        self.gain_others = float(no_drums_gain)

        self._orig_drums: Optional[np.ndarray] = None
        self._orig_others: Optional[np.ndarray] = None
        self._orig_sr = _PRACTICE_SR
        self._orig_duration = 0.0
        self._metronome = ctk.BooleanVar(value=False)
        self._metronome_accent = ctk.BooleanVar(value=True)
        self._busy = False
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
        ctk.CTkLabel(
            header, text="Clic en la partitura o arrastra la barra para retroceder",
            text_color="gray60",
        ).pack(side="right")

        self.score = ScoreCanvas(self, fg_color="transparent")
        self.score.grid(row=1, column=0, sticky="nsew", padx=16, pady=6)
        self.score.set_seek_callback(self._seek_seconds)

        # --- Volumen de pistas (mezcla) ---
        vol = ctk.CTkFrame(self, fg_color="transparent")
        vol.grid(row=2, column=0, sticky="ew", padx=16, pady=(2, 0))
        vol.grid_columnconfigure(0, weight=1, uniform="vol")
        vol.grid_columnconfigure(1, weight=1, uniform="vol")
        self._build_vol_slider(vol, 0, "🥁 Bateria", self.gain_drums, self._on_vol_drums)
        self._build_vol_slider(vol, 1, "🎵 Otros", self.gain_others, self._on_vol_others)

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
        ctk.CTkLabel(row1, text="⏱ Tempo", text_color="gray80").pack(side="left")
        self.bpm_value = ctk.CTkLabel(
            row1, text=f"{int(self.bpm0)} BPM", font=ctk.CTkFont(size=15, weight="bold")
        )
        self.bpm_value.pack(side="right")
        self.bpm_slider = ctk.CTkSlider(
            left, from_=40, to=220, number_of_steps=180, command=self._on_bpm_slide
        )
        self.bpm_slider.set(self.bpm0)
        self.bpm_slider.pack(fill="x", pady=(4, 4))
        ctk.CTkButton(left, text="Reset tempo", height=26, command=self._reset_bpm).pack()

        self.play_btn = ctk.CTkButton(
            controls, text="▶", width=72, height=72, corner_radius=36,
            command=self._on_play_pause, font=ctk.CTkFont(size=26),
            fg_color=ACCENT, hover_color=ACCENT_HOVER, state="disabled",
        )
        self.play_btn.grid(row=0, column=1, padx=18)

        right = ctk.CTkFrame(controls, fg_color="transparent")
        right.grid(row=0, column=2, sticky="ew", padx=(12, 0))
        mrow = ctk.CTkFrame(right, fg_color="transparent")
        mrow.pack(fill="x")
        ctk.CTkLabel(mrow, text="Compas", text_color="gray80").pack(side="left")
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

        self.status = ctk.CTkLabel(self, text="", text_color="gray60")
        self.status.grid(row=5, column=0, pady=(0, 8))

    def _build_vol_slider(self, parent, col, name, gain, command) -> None:
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.grid(row=0, column=col, sticky="ew", padx=6)
        ctk.CTkLabel(box, text=name, width=90, anchor="w", text_color="gray80").pack(
            side="left"
        )
        slider = ctk.CTkSlider(box, from_=0, to=150, number_of_steps=150, command=command)
        slider.set(gain * 100)
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
        self.score.set_events(
            events, self._orig_duration, bpm=int(self.bpm0),
            beats_per_bar=self.beats_per_bar,
        )
        self.time_total.configure(text=_fmt_time(self._orig_duration))
        self._render_buffer(keep_fraction=0.0)
        self.play_btn.configure(state="normal")
        self._set_status("" if self.player.available else "Sin dispositivo de audio.")

    # --------------------------------------------------------- tempo / buffer
    def _current_gains(self) -> List[float]:
        return [self.gain_drums, self.gain_others,
                1.0 if self._metronome.get() else 0.0]

    def _render_buffer(self, keep_fraction: float) -> None:
        assert self._orig_drums is not None and self._orig_others is not None
        rate = self.target_bpm / self.bpm0
        drums = _stretch(self._orig_drums, rate)
        others = _stretch(self._orig_others, rate)
        n = max(len(drums), len(others))
        click = _make_click_track(
            n, self._orig_sr, self.target_bpm,
            beats_per_bar=self.beats_per_bar, accent=self._metronome_accent.get(),
        )
        self.player.set_tracks(
            [drums, others, click], self._orig_sr,
            gains=self._current_gains(), keep_fraction=keep_fraction,
        )
        # A partir de ahora el audio suena a este tempo: el cursor debe usarlo.
        self.rendered_bpm = self.target_bpm

    def _apply_tempo_async(self) -> None:
        if self._orig_drums is None or self._busy:
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
        # Si el usuario siguio moviendo el slider durante el re-render, aplicamos
        # el ultimo tempo pedido.
        if abs(self.target_bpm - self.rendered_bpm) >= 1.0:
            self._bpm_after = self.after(80, self._apply_tempo_async)

    # ----------------------------------------------------------------- eventos
    def _on_vol_drums(self, value: float) -> None:
        self.gain_drums = value / 100.0
        self.player.set_gain(_T_DRUMS, self.gain_drums)

    def _on_vol_others(self, value: float) -> None:
        self.gain_others = value / 100.0
        self.player.set_gain(_T_OTHERS, self.gain_others)

    def _on_bpm_slide(self, value: float) -> None:
        self.target_bpm = float(value)
        self.bpm_value.configure(text=f"{int(value)} BPM")
        # Re-render con debounce: al dejar de mover el slider, estira el audio.
        if self._bpm_after is not None:
            self.after_cancel(self._bpm_after)
        self._bpm_after = self.after(350, self._apply_tempo_async)

    def _reset_bpm(self) -> None:
        self.target_bpm = self.bpm0
        self.bpm_slider.set(self.bpm0)
        self.bpm_value.configure(text=f"{int(self.bpm0)} BPM")
        self._apply_tempo_async()

    def _on_meter_change(self, value: str) -> None:
        self.beats_per_bar = int(value.split("/")[0])
        self.score.set_grid(int(self.bpm0), self.beats_per_bar)
        # El patron de acento del click depende del compas: regenerarlo.
        self._apply_tempo_async()

    def _on_metronome_toggle(self) -> None:
        # El click ya esta como pista aparte: solo cambiamos su volumen en vivo.
        self.player.set_gain(_T_CLICK, 1.0 if self._metronome.get() else 0.0)

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
            # El cursor sigue el tempo REAL del audio (rendered_bpm), no el del
            # slider, para que nunca se desincronice mientras se re-renderiza.
            orig_sec = self.player.position() * (self.rendered_bpm / self.bpm0)
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
