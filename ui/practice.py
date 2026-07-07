"""
practice.py — Ventana "Practicar": reproduce la bateria y sigue la partitura en
tiempo real con un cursor, al BPM que elijas.

Modo A+B:
  - El BPM detectado se muestra y se puede modificar con un slider.
  - Al cambiar el BPM, la bateria se estira al nuevo tempo SIN cambiar el tono
    (librosa.effects.time_stretch) y el cursor la sigue sincronizado.
  - Opcional: metronomo (click en cada negra) mezclado en el audio.

Sincronia: el lienzo dibuja las notas por segundos reales del audio original; el
cursor se calcula desde la posicion del audio estirado -> siempre caen juntos:
    segundos_originales = posicion_reproducida * (bpm_objetivo / bpm_detectado)
La fraccion de avance es invariante al tempo, asi que al re-estirar conservamos
la posicion musical simplemente conservando la fraccion.
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
_PRACTICE_SR = 22050  # mono, suficiente para bateria y mas rapido de estirar


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
                 bpm: Optional[int], song_name: str) -> None:
        super().__init__(master)
        self.title(f"Practicar — {song_name}")
        self.geometry("920x380")
        self.minsize(720, 340)

        self._midi_path = midi_path
        self._drums_wav = drums_wav
        self.bpm0 = float(bpm) if bpm else 120.0
        self.target_bpm = self.bpm0

        self._orig: Optional[np.ndarray] = None  # bateria mono original
        self._orig_sr = _PRACTICE_SR
        self._orig_duration = 0.0
        self._metronome = ctk.BooleanVar(value=False)
        self._busy = False

        self.player = SingleTrackPlayer()

        self._build_widgets()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Cargar audio + eventos en un hilo (no congelar la ventana).
        self._set_status("Cargando audio...")
        threading.Thread(target=self._load_worker, daemon=True).start()
        self.after(33, self._tick)

    # ---------------------------------------------------------------- widgets
    def _build_widgets(self) -> None:
        ctk.CTkLabel(
            self, text="🥁 Practicar en tiempo real",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(pady=(12, 6))

        self.score = ScoreCanvas(self, height=150, fg_color="transparent")
        self.score.pack(fill="x", padx=16, pady=(0, 6))

        times = ctk.CTkFrame(self, fg_color="transparent")
        times.pack(fill="x", padx=16)
        self.time_cur = ctk.CTkLabel(times, text="00:00", text_color="gray70")
        self.time_cur.pack(side="left")
        self.time_total = ctk.CTkLabel(times, text="00:00", text_color="gray70")
        self.time_total.pack(side="right")

        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.pack(fill="x", padx=16, pady=(10, 4))
        controls.grid_columnconfigure(1, weight=1)

        # Play
        self.play_btn = ctk.CTkButton(
            controls, text="▶", width=58, height=58, corner_radius=29,
            command=self._on_play_pause, font=ctk.CTkFont(size=20),
            fg_color="#2a2a2a", hover_color="#3a3a3a", state="disabled",
        )
        self.play_btn.grid(row=0, column=0, rowspan=2, padx=(0, 16))

        # BPM slider
        bpm_row = ctk.CTkFrame(controls, fg_color="transparent")
        bpm_row.grid(row=0, column=1, sticky="ew")
        ctk.CTkLabel(bpm_row, text="⏱ Tempo (BPM)", text_color="gray80").pack(side="left")
        self.bpm_value = ctk.CTkLabel(
            bpm_row, text=f"{int(self.bpm0)}", font=ctk.CTkFont(size=15, weight="bold")
        )
        self.bpm_value.pack(side="right")

        self.bpm_slider = ctk.CTkSlider(
            controls, from_=40, to=220, number_of_steps=180, command=self._on_bpm_slide
        )
        self.bpm_slider.set(self.bpm0)
        self.bpm_slider.grid(row=1, column=1, sticky="ew", pady=(2, 0))
        self.bpm_slider.bind("<ButtonRelease-1>", self._on_bpm_release)

        # Extras
        extras = ctk.CTkFrame(controls, fg_color="transparent")
        extras.grid(row=0, column=2, rowspan=2, padx=(16, 0))
        ctk.CTkButton(
            extras, text="Reset BPM", width=90, command=self._reset_bpm
        ).pack(pady=(0, 6))
        ctk.CTkCheckBox(
            extras, text="Metronomo", variable=self._metronome,
            command=self._on_metronome_toggle,
        ).pack()

        self.status = ctk.CTkLabel(self, text="", text_color="gray60")
        self.status.pack(pady=(4, 8))

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
        self.score.set_events(events, self._orig_duration)
        self.time_total.configure(text=_fmt_time(self._orig_duration))
        self._render_buffer(keep_fraction=0.0)
        self.play_btn.configure(state="normal")
        self._set_status(
            "" if self.player.available else "Sin dispositivo de audio."
        )

    # --------------------------------------------------------- tempo / buffer
    def _render_buffer(self, keep_fraction: float) -> None:
        """Genera el buffer al tempo actual (+metronomo) y lo carga en el player."""
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
        self.bpm_value.configure(text=f"{int(value)}")

    def _on_bpm_release(self, _event) -> None:
        self._apply_tempo_async()

    def _reset_bpm(self) -> None:
        self.target_bpm = self.bpm0
        self.bpm_slider.set(self.bpm0)
        self.bpm_value.configure(text=f"{int(self.bpm0)}")
        self._apply_tempo_async()

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

    def _tick(self) -> None:
        if self.player.loaded:
            orig_sec = self.player.position() * (self.target_bpm / self.bpm0)
            self.score.set_cursor_seconds(orig_sec)
            self.time_cur.configure(text=_fmt_time(orig_sec))
            if self.player.finished and not self.player.is_playing:
                self.play_btn.configure(text="▶")
        self.after(33, self._tick)

    # ----------------------------------------------------------------- helpers
    def _set_status(self, text: str) -> None:
        self.status.configure(text=text)

    def _on_close(self) -> None:
        self.player.close()
        self.destroy()
