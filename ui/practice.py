"""
practice.py — Ventana "Practicar": reproduce la bateria y sigue la partitura en
tiempo real con un cursor, al BPM (y compas) que elijas.

Modo A+B:
  - BPM y compas detectados se muestran y se pueden cambiar.
  - Al cambiar el BPM, la bateria se estira al nuevo tempo SIN cambiar el tono
    (librosa.effects.time_stretch) y el cursor la sigue sincronizado.
  - Se puede retroceder/avanzar en tiempo real: barra de progreso + clic sobre la
    partitura.
  - Metronomo opcional.

Layout: la partitura ocupa casi toda la ventana; los controles van abajo,
distribuidos de forma simetrica (BPM a la izquierda, Play al centro, compas y
metronomo a la derecha).

Sincronia: el lienzo dibuja las notas por segundos reales del audio original; el
cursor se calcula desde la posicion del audio estirado -> siempre caen juntos.
La fraccion de avance es invariante al tempo (se conserva al re-estirar).
"""

from __future__ import annotations

import threading
from typing import Optional

import customtkinter as ctk
import numpy as np

from pipeline.score import extract_drum_events
from ui.player import SingleTrackPlayer
from ui.score_view import ScoreCanvas

ACCENT = "#1db954"
ACCENT_HOVER = "#17a347"
_PRACTICE_SR = 22050
_METERS = ["2/4", "3/4", "4/4"]


def _fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _make_click_track(n_frames: int, sr: int, bpm: float) -> np.ndarray:
    """Click de metronomo (mono) cada negra al tempo `bpm`."""
    track = np.zeros(n_frames, dtype="float32")
    if bpm <= 0:
        return track
    interval = int(sr * 60.0 / bpm)
    if interval <= 0:
        return track
    click_len = int(sr * 0.03)
    t = np.linspace(0, 0.03, click_len, endpoint=False)
    click = (0.35 * np.sin(2 * np.pi * 1200 * t) * np.exp(-t * 60)).astype("float32")
    for start in range(0, n_frames, interval):
        end = min(start + click_len, n_frames)
        track[start:end] += click[: end - start]
    return track


class PracticeWindow(ctk.CTkToplevel):
    def __init__(self, master, midi_path: str, drums_wav: str,
                 bpm: Optional[int], song_name: str, beats_per_bar: int = 4) -> None:
        super().__init__(master)
        self.title(f"Practicar — {song_name}")
        self.geometry("1100x680")
        self.minsize(820, 540)

        self._midi_path = midi_path
        self._drums_wav = drums_wav
        self.bpm0 = float(bpm) if bpm else 120.0
        self.target_bpm = self.bpm0
        self.beats_per_bar = beats_per_bar if beats_per_bar in (2, 3, 4) else 4

        self._orig: Optional[np.ndarray] = None
        self._orig_sr = _PRACTICE_SR
        self._orig_duration = 0.0
        self._metronome = ctk.BooleanVar(value=False)
        self._busy = False
        self._user_seeking = False

        self.player = SingleTrackPlayer()

        self._build_widgets()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._set_status("Cargando audio...")
        threading.Thread(target=self._load_worker, daemon=True).start()
        self.after(33, self._tick)

    # ---------------------------------------------------------------- widgets
    def _build_widgets(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)  # la partitura se estira

        # --- Encabezado ---
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

        # --- Partitura (ocupa el espacio central) ---
        self.score = ScoreCanvas(self, fg_color="transparent")
        self.score.grid(row=1, column=0, sticky="nsew", padx=16, pady=6)
        self.score.set_seek_callback(self._seek_seconds)

        # --- Barra de progreso + tiempos ---
        seekbox = ctk.CTkFrame(self, fg_color="transparent")
        seekbox.grid(row=2, column=0, sticky="ew", padx=16, pady=(4, 0))
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
        controls.grid(row=3, column=0, sticky="ew", padx=16, pady=(8, 14))
        controls.grid_columnconfigure(0, weight=1, uniform="ctl")
        controls.grid_columnconfigure(1, weight=0)
        controls.grid_columnconfigure(2, weight=1, uniform="ctl")

        # Izquierda: BPM
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

        # Centro: Play
        self.play_btn = ctk.CTkButton(
            controls, text="▶", width=72, height=72, corner_radius=36,
            command=self._on_play_pause, font=ctk.CTkFont(size=26),
            fg_color=ACCENT, hover_color=ACCENT_HOVER, state="disabled",
        )
        self.play_btn.grid(row=0, column=1, padx=18)

        # Derecha: Compas + Metronomo
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

        self.status = ctk.CTkLabel(self, text="", text_color="gray60")
        self.status.grid(row=4, column=0, pady=(0, 8))

    # ------------------------------------------------------------------ carga
    def _load_worker(self) -> None:
        try:
            import librosa

            events, _dur = extract_drum_events(self._midi_path)
            y, sr = librosa.load(self._drums_wav, sr=_PRACTICE_SR, mono=True)
            self._orig = y.astype("float32")
            self._orig_sr = sr
            self._orig_duration = len(y) / sr
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
    def _render_buffer(self, keep_fraction: float) -> None:
        assert self._orig is not None
        rate = self.target_bpm / self.bpm0
        if abs(rate - 1.0) < 1e-3:
            buf = self._orig.copy()
        else:
            import librosa
            buf = librosa.effects.time_stretch(self._orig, rate=rate).astype("float32")
        if self._metronome.get():
            buf = buf + _make_click_track(len(buf), self._orig_sr, self.target_bpm)
            peak = float(np.max(np.abs(buf))) if buf.size else 0.0
            if peak > 1.0:
                buf = buf / peak
        self.player.set_buffer(buf, self._orig_sr, keep_fraction=keep_fraction)

    def _apply_tempo_async(self) -> None:
        if self._orig is None or self._busy:
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

    # ----------------------------------------------------------------- eventos
    def _on_bpm_slide(self, value: float) -> None:
        self.target_bpm = float(value)
        self.bpm_value.configure(text=f"{int(value)} BPM")

    def _on_bpm_release(self, _event) -> None:
        self._apply_tempo_async()

    def _reset_bpm(self) -> None:
        self.target_bpm = self.bpm0
        self.bpm_slider.set(self.bpm0)
        self.bpm_value.configure(text=f"{int(self.bpm0)} BPM")
        self._apply_tempo_async()

    def _on_meter_change(self, value: str) -> None:
        self.beats_per_bar = int(value.split("/")[0])
        self.score.set_grid(int(self.bpm0), self.beats_per_bar)

    def _on_metronome_toggle(self) -> None:
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

    # --- seek (retroceder/avanzar) ---
    def _seek_seconds(self, original_seconds: float) -> None:
        """Seek desde un clic en la partitura (segundos del audio original)."""
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
            orig_sec = self.player.position() * (self.target_bpm / self.bpm0)
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
