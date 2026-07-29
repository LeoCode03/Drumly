"""
practice.py — Ventana "Practicar": reproduce la bateria (y la banda) y sigue la
partitura en tiempo real con un cursor, al tempo y compas que elijas.

Arquitectura espacial (jerarquia: partitura > transporte > ajustes):
  fila 0  Titulo | grupo COMPAS (selector + marcar compas 1 + aplicar al PDF)
  fila 1  PARTITURA (lienzo, se estira; leyenda de carriles; zoom +/-)
  fila 2  MEZCLA compacta (Bateria, Banda)
  fila 3  NAVEGACION: inicio / -5s / +5s / barra / tiempo grande
  fila 4  VELOCIDAD DE LA CANCION | play | METRONOMO (todo el click en UN panel)
  fila 5  status

Dos relojes, nunca confundidos (PRODUCT.md): el panel izquierdo estira el AUDIO
(porcentaje de la velocidad original); el panel derecho gobierna SOLO el click
del metronomo (encendido, volumen, pulso cancion/manual, subdivision, acento).

Sincronia: el lienzo dibuja las notas por segundos reales del audio original; el
cursor se calcula desde la posicion reproducida (menos la latencia de salida
cuando suena) -> siempre caen juntos. La fraccion de avance es invariante al
tempo (se conserva al re-estirar).
"""

from __future__ import annotations

import threading
from typing import Callable, List, Optional, Tuple

import customtkinter as ctk
import numpy as np

from pipeline.score import extract_drum_events
from ui import theme
from ui.player import MixPlayer
from ui.score_view import ScoreCanvas

_PRACTICE_SR = 22050
_METERS = ["2/4", "3/4", "4/4", "5/4", "6/4", "6/8"]
_BPM_MIN = 40
_BPM_MAX = 220
_VOL_MIN = 0
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
    subdivision: int = 1,
) -> np.ndarray:
    """
    Click de metronomo (mono) con tres intensidades: acento (1er tiempo del
    compas), pulso normal (negras) y subdivision suave (corcheas intercaladas).

    `click_times`: si se pasa, los pulsos caen EXACTAMENTE en esos instantes
    (beats reales estirados al tempo elegido); la subdivision se interpola entre
    pulsos consecutivos. Sin `click_times`: rejilla constante cada 60/bpm s
    desde `offset_seconds`.
    """
    track = np.zeros(n_frames, dtype="float32")
    if n_frames <= 0:
        return track

    wave_accent = _click_wave(sr, 1800, 0.9)
    wave_normal = _click_wave(sr, 1200, 0.5)
    wave_weak = _click_wave(sr, 1500, 0.28)

    # Construir (instante_s, tipo) — tipo: 0=acento, 1=normal, 2=suave
    events: List[Tuple[float, int]] = []
    if click_times:
        for i, t in enumerate(click_times):
            kind = 0 if (accent and i % beats_per_bar == 0) else 1
            events.append((t, kind))
            if subdivision >= 2 and i + 1 < len(click_times):
                nxt = click_times[i + 1]
                for k in range(1, subdivision):
                    events.append((t + (nxt - t) * k / subdivision, 2))
    else:
        if bpm <= 0:
            return track
        beat_len = 60.0 / bpm
        step = beat_len / max(1, subdivision)
        if step <= 0:
            return track
        t = max(0.0, offset_seconds)
        idx = 0
        while t * sr < n_frames:
            if idx % subdivision == 0:
                beat = idx // subdivision
                kind = 0 if (accent and beat % beats_per_bar == 0) else 1
            else:
                kind = 2
            events.append((t, kind))
            idx += 1
            t = max(0.0, offset_seconds) + idx * step

    waves = {0: wave_accent, 1: wave_normal, 2: wave_weak}
    for t, kind in events:
        start = int(t * sr)
        if not (0 <= start < n_frames):
            continue
        wave = waves[kind]
        end = min(start + len(wave), n_frames)
        track[start:end] += wave[: end - start]
    return track


def _stretch(y: np.ndarray, rate: float) -> np.ndarray:
    if abs(rate - 1.0) < 1e-3:
        # Sin copia: las pistas nunca se mutan (la mezcla se acumula en un
        # buffer nuevo del callback), asi que compartir memoria es seguro y
        # ahorra ~decenas de MB por re-render a tempo original.
        return y
    import librosa
    return librosa.effects.time_stretch(y, rate=rate).astype("float32")


class PracticeWindow(ctk.CTkToplevel):
    def __init__(self, master, midi_path: str, drums_wav: str,
                 bpm: Optional[int], song_name: str, beats_per_bar: int = 4,
                 no_drums_wav: Optional[str] = None,
                 drums_gain: float = 1.0, no_drums_gain: float = 1.0,
                 beat_offset: float = 0.0,
                 beat_times: Optional[List[float]] = None,
                 on_apply: Optional[Callable] = None,
                 meter_label: str = "") -> None:
        super().__init__(master, fg_color=theme.SURFACE1)
        self.title(f"Practicar — {song_name}")
        self.geometry("1150x760")
        self.minsize(900, 620)

        self._midi_path = midi_path
        self._drums_wav = drums_wav
        self._no_drums_wav = no_drums_wav
        self._song_name = song_name
        self.bpm0 = float(bpm) if bpm else 120.0
        self.target_bpm = self.bpm0     # tempo pedido por el slider
        self.rendered_bpm = self.bpm0   # tempo al que esta ESTIRADO el audio actual
        self._bpm_after = None          # id del re-render con debounce
        self.beats_per_bar = beats_per_bar if beats_per_bar in (2, 3, 4, 5, 6) else 4
        # Compas como texto (p. ej. "6/8"); beats_per_bar = NEGRAS por compas.
        self.meter_label = meter_label or f"{self.beats_per_bar}/4"
        self.beat_offset = max(0.0, float(beat_offset))  # inicio del compas 1 (s)
        # Pulsos reales de la cancion (beat tracking); si estan, el metronomo y
        # las barras de compas siguen el tempo REAL aunque fluctue (en vivo).
        self.beat_times: List[float] = sorted(beat_times) if beat_times else []
        # Callback para aplicar los ajustes manuales (inicio de compas, compas)
        # a la partitura PDF: on_apply(beat_offset, beats_per_bar, status_cb, manual_bpm).
        self._on_apply = on_apply

        self.gain_drums = float(drums_gain)
        self.gain_others = float(no_drums_gain)
        self.gain_click = 1.0   # volumen del metronomo (cuando esta activado)

        # Pulso del metronomo: "cancion" = beats reales detectados; "manual" =
        # BPM fijo elegido por el usuario (el click suena a ese ritmo constante).
        self._pulse_mode = "cancion"
        self.custom_bpm = float(int(self.bpm0))
        self.subdivision = 1    # 1 = negras, 2 = corcheas

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

        self._bind_keys()
        self._set_status("Cargando audio...")
        threading.Thread(target=self._load_worker, daemon=True).start()
        self.after(33, self._tick)

    # ---------------------------------------------------------------- widgets
    def _build_widgets(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)  # la partitura se estira

        # ---- fila 0: titulo + grupo COMPAS (calibracion de una sola vez) ----
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=theme.SP_MD,
                    pady=(theme.SP_MD, theme.SP_SM))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header, text=self._song_name, font=theme.f_title(),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        compass = ctk.CTkFrame(header, fg_color="transparent")
        compass.grid(row=0, column=1, sticky="e")
        ctk.CTkLabel(compass, text="Compas", text_color=theme.TEXT_MUTED,
                     font=theme.f_body()).pack(side="left", padx=(0, theme.SP_SM))
        self.meter_menu = ctk.CTkOptionMenu(
            compass, values=_METERS, width=78, command=self._on_meter_change,
            font=theme.f_body(),
        )
        self.meter_menu.set(self.meter_label if self.meter_label in _METERS
                            else f"{self.beats_per_bar}/4")
        self.meter_menu.pack(side="left", padx=(0, theme.SP_MD))
        self.mark_btn = ctk.CTkButton(
            compass, text="Marcar compas 1", height=32, width=140,
            command=self._on_mark_start, font=theme.f_body(),
            fg_color=theme.SURFACE3, hover_color=theme.SURFACE4, state="disabled",
        )
        self.mark_btn.pack(side="left", padx=(0, theme.SP_SM))
        self.apply_btn = ctk.CTkButton(
            compass, text="Aplicar al PDF", height=32, width=120,
            command=self._on_apply_score, font=theme.f_body(),
            fg_color=theme.SURFACE3, hover_color=theme.SURFACE4, state="disabled",
        )
        self.apply_btn.pack(side="left")

        # ---- fila 1: partitura + zoom flotante ----
        self.score = ScoreCanvas(self, fg_color="transparent")
        self.score.grid(row=1, column=0, sticky="nsew", padx=theme.SP_MD,
                        pady=(0, theme.SP_SM))
        self.score.set_seek_callback(self._seek_seconds)
        zoom = ctk.CTkFrame(self.score, fg_color=theme.SURFACE2,
                            corner_radius=theme.RAD_CONTROL)
        zoom.place(relx=1.0, y=6, x=-6, anchor="ne")
        ctk.CTkButton(zoom, text="−", width=30, height=26,
                      fg_color="transparent", hover_color=theme.SURFACE4,
                      font=theme.font(16, bold=True),
                      command=self.score.zoom_out).pack(side="left")
        ctk.CTkButton(zoom, text="+", width=30, height=26,
                      fg_color="transparent", hover_color=theme.SURFACE4,
                      font=theme.font(16, bold=True),
                      command=self.score.zoom_in).pack(side="left")

        # ---- fila 2: mezcla compacta (Bateria, Banda) ----
        mix = ctk.CTkFrame(self, fg_color="transparent")
        mix.grid(row=2, column=0, sticky="ew", padx=theme.SP_MD, pady=(0, 2))
        mix.grid_columnconfigure(1, weight=1)
        mix.grid_columnconfigure(3, weight=1)
        ctk.CTkLabel(mix, text="Bateria", text_color=theme.TEXT_MUTED,
                     font=theme.f_body(), width=70, anchor="w").grid(row=0, column=0)
        self.vol_drums = ctk.CTkSlider(
            mix, from_=_VOL_MIN, to=_VOL_MAX, number_of_steps=_VOL_MAX - _VOL_MIN,
            command=self._on_vol_drums)
        self.vol_drums.set(min(max(self.gain_drums * 100, _VOL_MIN), _VOL_MAX))
        self.vol_drums.grid(row=0, column=1, sticky="ew", padx=(4, theme.SP_LG))
        ctk.CTkLabel(mix, text="Banda", text_color=theme.TEXT_MUTED,
                     font=theme.f_body(), width=60, anchor="w").grid(row=0, column=2)
        self.vol_others = ctk.CTkSlider(
            mix, from_=_VOL_MIN, to=_VOL_MAX, number_of_steps=_VOL_MAX - _VOL_MIN,
            command=self._on_vol_others)
        self.vol_others.set(min(max(self.gain_others * 100, _VOL_MIN), _VOL_MAX))
        self.vol_others.grid(row=0, column=3, sticky="ew", padx=(4, 0))

        # ---- fila 3: navegacion temporal ----
        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.grid(row=3, column=0, sticky="ew", padx=theme.SP_MD,
                 pady=(theme.SP_SM, 0))
        nav.grid_columnconfigure(3, weight=1)
        self.restart_btn = ctk.CTkButton(
            nav, text="⏮", width=44, height=40, corner_radius=theme.RAD_CONTROL,
            command=self._on_restart, font=theme.font(16),
            fg_color=theme.SURFACE3, hover_color=theme.SURFACE4, state="disabled",
        )
        self.restart_btn.grid(row=0, column=0, padx=(0, theme.SP_XS))
        self.back5_btn = ctk.CTkButton(
            nav, text="⏪ 5s", width=64, height=40, corner_radius=theme.RAD_CONTROL,
            command=self._on_back5, font=theme.f_body(),
            fg_color=theme.SURFACE3, hover_color=theme.SURFACE4, state="disabled",
        )
        self.back5_btn.grid(row=0, column=1, padx=(0, theme.SP_XS))
        self.fwd5_btn = ctk.CTkButton(
            nav, text="5s ⏩", width=64, height=40, corner_radius=theme.RAD_CONTROL,
            command=self._on_forward5, font=theme.f_body(),
            fg_color=theme.SURFACE3, hover_color=theme.SURFACE4, state="disabled",
        )
        self.fwd5_btn.grid(row=0, column=2, padx=(0, theme.SP_MD))
        self.seek = ctk.CTkSlider(nav, from_=0, to=1, command=self._on_seek_slider)
        self.seek.set(0)
        self.seek.grid(row=0, column=3, sticky="ew", padx=(0, theme.SP_MD))
        self.seek.bind("<ButtonPress-1>", lambda e: setattr(self, "_user_seeking", True))
        self.seek.bind("<ButtonRelease-1>", self._on_seek_release)
        self.time_cur = ctk.CTkLabel(nav, text="00:00", font=theme.f_value())
        self.time_cur.grid(row=0, column=4)
        self.time_total = ctk.CTkLabel(nav, text=" / 00:00",
                                       text_color=theme.TEXT_MUTED,
                                       font=theme.f_small())
        self.time_total.grid(row=0, column=5)

        # ---- fila 4: VELOCIDAD | play | METRONOMO ----
        panels = ctk.CTkFrame(self, fg_color="transparent")
        panels.grid(row=4, column=0, sticky="ew", padx=theme.SP_MD,
                    pady=(theme.SP_SM, theme.SP_SM))
        panels.grid_columnconfigure(0, weight=1, uniform="pan")
        panels.grid_columnconfigure(1, weight=0)
        panels.grid_columnconfigure(2, weight=1, uniform="pan")

        # Panel izquierdo: velocidad del AUDIO (estira la cancion)
        speed = ctk.CTkFrame(panels, fg_color=theme.SURFACE2,
                             corner_radius=theme.RAD_PANEL)
        speed.grid(row=0, column=0, sticky="nsew", padx=(0, theme.SP_MD))
        ctk.CTkLabel(speed, text="VELOCIDAD DE LA CANCION",
                     text_color=theme.TEXT_MUTED, font=theme.f_section(),
                     ).pack(anchor="w", padx=theme.SP_MD, pady=(theme.SP_SM, 0))
        self.speed_value = ctk.CTkLabel(speed, text="100%  ·  -- BPM",
                                        font=theme.f_value())
        self.speed_value.pack(anchor="w", padx=theme.SP_MD)
        self.bpm_slider = ctk.CTkSlider(
            speed, from_=_BPM_MIN, to=_BPM_MAX,
            number_of_steps=_BPM_MAX - _BPM_MIN, command=self._on_bpm_slide,
        )
        self.bpm_slider.set(min(max(self.bpm0, _BPM_MIN), _BPM_MAX))
        self.bpm_slider.pack(fill="x", padx=theme.SP_MD, pady=(2, theme.SP_SM))
        ctk.CTkButton(speed, text="Restablecer", height=28, width=110,
                      command=self._reset_bpm, font=theme.f_small(),
                      fg_color=theme.SURFACE3, hover_color=theme.SURFACE4,
                      ).pack(anchor="w", padx=theme.SP_MD, pady=(0, theme.SP_SM))

        # Centro: transporte
        self.play_btn = ctk.CTkButton(
            panels, text="▶", width=84, height=84, corner_radius=42,
            command=self._on_play_pause, font=ctk.CTkFont(size=30),
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            text_color=theme.ON_ACCENT, state="disabled",
        )
        self.play_btn.grid(row=0, column=1, padx=theme.SP_SM)

        # Panel derecho: METRONOMO completo (nada del click vive fuera de aqui)
        met = ctk.CTkFrame(panels, fg_color=theme.SURFACE2,
                           corner_radius=theme.RAD_PANEL)
        met.grid(row=0, column=2, sticky="nsew", padx=(theme.SP_MD, 0))
        met.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(met, text="METRONOMO", text_color=theme.TEXT_MUTED,
                     font=theme.f_section()).grid(
            row=0, column=0, columnspan=2, sticky="w",
            padx=theme.SP_MD, pady=(theme.SP_SM, 2))
        self.met_switch = ctk.CTkSwitch(
            met, text="Click", variable=self._metronome,
            command=self._on_metronome_toggle, font=theme.f_body(), width=90,
        )
        self.met_switch.grid(row=1, column=0, sticky="w", padx=theme.SP_MD)
        self.vol_click = ctk.CTkSlider(
            met, from_=_VOL_MIN, to=_VOL_MAX, number_of_steps=_VOL_MAX - _VOL_MIN,
            command=self._on_vol_click)
        self.vol_click.set(min(max(self.gain_click * 100, _VOL_MIN), _VOL_MAX))
        self.vol_click.grid(row=1, column=1, sticky="ew",
                            padx=(0, theme.SP_MD))
        pulse_row = ctk.CTkFrame(met, fg_color="transparent")
        pulse_row.grid(row=2, column=0, columnspan=2, sticky="w",
                       padx=theme.SP_MD, pady=(theme.SP_XS, 0))
        self.pulse_seg = ctk.CTkSegmentedButton(
            pulse_row, values=["Cancion", "Manual"], command=self._on_pulse_mode,
            height=28, font=theme.f_small(),
        )
        self.pulse_seg.set("Cancion")
        self.pulse_seg.pack(side="left", padx=(0, theme.SP_SM))
        self.pulse_entry = ctk.CTkEntry(pulse_row, width=54, height=28,
                                        justify="center", font=theme.f_body())
        self.pulse_entry.insert(0, str(int(self.custom_bpm)))
        self.pulse_entry.pack(side="left")
        self.pulse_entry.bind("<Return>", self._on_custom_bpm_commit)
        self.pulse_entry.bind("<FocusOut>", self._on_custom_bpm_commit)
        ctk.CTkLabel(pulse_row, text="BPM", text_color=theme.TEXT_FAINT,
                     font=theme.f_small()).pack(side="left", padx=(4, 0))
        sub_row = ctk.CTkFrame(met, fg_color="transparent")
        sub_row.grid(row=3, column=0, columnspan=2, sticky="w",
                     padx=theme.SP_MD, pady=(theme.SP_XS, 0))
        self.sub_seg = ctk.CTkSegmentedButton(
            sub_row, values=["Negras", "Corcheas"], command=self._on_subdivision,
            height=28, font=theme.f_small(),
        )
        self.sub_seg.set("Negras")
        self.sub_seg.pack(side="left", padx=(0, theme.SP_SM))
        ctk.CTkCheckBox(
            sub_row, text="Acento 1er tiempo", variable=self._metronome_accent,
            command=self._on_metronome_accent_toggle, font=theme.f_small(),
        ).pack(side="left")
        met.grid_rowconfigure(4, minsize=theme.SP_SM)

        # ---- fila 5: status ----
        self.status = ctk.CTkLabel(self, text="", text_color=theme.TEXT_MUTED,
                                   font=theme.f_small())
        self.status.grid(row=5, column=0, pady=(0, theme.SP_SM))

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
            self.after(0, lambda: self._set_status(
                f"No se pudo cargar el audio: {msg}", error=True))

    def _on_loaded(self, events) -> None:
        self._events_sec = sorted(sec for sec, _ in events)
        self.score.set_events(
            events, self._orig_duration, bpm=int(self.bpm0),
            beats_per_bar=self.beats_per_bar, beat_offset=self.beat_offset,
        )
        self._update_bars()
        self.time_total.configure(text=f" / {_fmt_time(self._orig_duration)}")
        self._update_speed_label()
        self._render_buffer(keep_fraction=0.0)
        for btn in (self.play_btn, self.restart_btn, self.back5_btn,
                    self.fwd5_btn, self.mark_btn):
            btn.configure(state="normal")
        if self._on_apply is not None:
            self.apply_btn.configure(state="normal")
        if self.player.available:
            self._set_status("Espacio: play/pausa · Flechas: ±5s · M: metronomo")
        else:
            self._set_status(
                "Sin dispositivo de audio: conecta unos parlantes o auriculares "
                "y vuelve a abrir esta ventana.", error=True)

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
            subdivision=self.subdivision,
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
        self._set_status("Ajustando velocidad...")

        def work() -> None:
            try:
                self._render_buffer(keep_fraction=frac)
                self.after(0, lambda: self._after_tempo(was_playing))
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                self.after(0, lambda: (self._set_status(
                    f"No se pudo ajustar la velocidad: {msg}", error=True),
                    setattr(self, "_busy", False)))

        threading.Thread(target=work, daemon=True).start()

    def _after_tempo(self, resume: bool) -> None:
        self._busy = False
        self._set_status("")
        if resume:
            self.player.play()
            self.play_btn.configure(text="⏸")
        # Si el usuario cambio algo durante el re-render (siguio moviendo el
        # slider, o cambio compas/acento/subdivision), re-aplicamos el ultimo
        # estado pedido.
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

    def _update_speed_label(self) -> None:
        pct = int(round(self.target_bpm / self.bpm0 * 100))
        self.speed_value.configure(
            text=f"{pct}%  ·  {int(self.target_bpm)} BPM"
        )

    def _on_bpm_slide(self, value: float) -> None:
        self.target_bpm = float(value)
        self._update_speed_label()
        # Re-render con debounce: al dejar de mover el slider, estira el audio.
        if self._bpm_after is not None:
            self.after_cancel(self._bpm_after)
        self._bpm_after = self.after(350, self._apply_tempo_async)

    def _reset_bpm(self) -> None:
        self.target_bpm = self.bpm0
        # Vuelve al tempo REAL de la cancion aunque supere el rango del slider
        # (40-220); el slider solo se clampea visualmente.
        self.bpm_slider.set(min(max(self.bpm0, _BPM_MIN), _BPM_MAX))
        self._update_speed_label()
        self._apply_tempo_async()

    def _on_meter_change(self, value: str) -> None:
        num, den = (int(x) for x in value.split("/"))
        self.meter_label = value
        # NEGRAS por compas: 6/8 -> 3 (dos tiempos de negra con puntillo);
        # el acento del click cae al inicio de cada compas igualmente.
        self.beats_per_bar = max(1, num * 4 // den)
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
            f"({self.beat_offset:.2f}s). Usa 'Aplicar al PDF' para regenerar "
            "la partitura con este inicio."
        )

    def _on_apply_score(self) -> None:
        """
        Regenera la partitura PDF con el inicio de compas y compas elegidos.
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
        self._on_apply(self.beat_offset, self.beats_per_bar, status_cb, manual_bpm,
                       self.meter_label)

    def _on_metronome_toggle(self) -> None:
        # El click ya esta como pista aparte: solo cambiamos su volumen en vivo.
        self.player.set_gain(_T_CLICK, self.gain_click if self._metronome.get() else 0.0)

    def _on_metronome_accent_toggle(self) -> None:
        self._apply_tempo_async()

    def _on_subdivision(self, value: str) -> None:
        self.subdivision = 2 if value == "Corcheas" else 1
        self._apply_tempo_async()  # regenerar la pista de click

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
            self._set_status(
                f"'{text}' no es un numero: el pulso sigue en "
                f"{int(self.custom_bpm)} BPM.", error=True)
            value = self.custom_bpm  # entrada invalida: restaurar
        clamped = min(max(value, 20.0), 300.0)
        if clamped != value:
            self._set_status(
                f"El pulso va de 20 a 300 BPM: ajustado a {int(clamped)}.")
        value = clamped
        self.custom_bpm = value
        self.pulse_entry.delete(0, "end")
        self.pulse_entry.insert(0, str(int(value)))
        if self._pulse_mode == "manual":
            self._update_bars()
            self._apply_tempo_async()

    # ------------------------------------------------------------- transporte
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
                self._set_status(f"No se pudo reproducir: {exc}", error=True)

    def _on_restart(self) -> None:
        """Vuelve al inicio (sigue reproduciendo si estaba sonando)."""
        self._seek_seconds(0.0)

    def _on_back5(self) -> None:
        """Retrocede 5 segundos (en tiempo de la cancion original)."""
        if self._orig_duration <= 0:
            return
        cur = self.player.fraction() * self._orig_duration
        self._seek_seconds(max(0.0, cur - 5.0))

    def _on_forward5(self) -> None:
        """Avanza 5 segundos (en tiempo de la cancion original)."""
        if self._orig_duration <= 0:
            return
        cur = self.player.fraction() * self._orig_duration
        self._seek_seconds(min(self._orig_duration, cur + 5.0))

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

    # ------------------------------------------------------------------ teclado
    def _bind_keys(self) -> None:
        """
        Practica operable sin mouse (manos con baquetas):
          Espacio play/pausa · ←/→ ±5s · Inicio: volver al principio ·
          ↑/↓ velocidad ±5 BPM · M metronomo · Ctrl+rueda zoom de partitura.
        """
        for seq in ("<space>", "<Left>", "<Right>", "<Home>",
                    "<Up>", "<Down>", "<KeyPress-m>", "<KeyPress-M>"):
            self.bind(seq, self._on_key)
        self.bind("<Control-MouseWheel>", self._on_ctrl_wheel)
        # El foco arranca en la ventana para que las teclas lleguen ya.
        self.after(400, self.focus_set)

    def _on_key(self, event) -> str | None:
        # Si el usuario esta escribiendo en un cuadro de texto, no interceptar.
        focus = self.focus_get()
        if focus is not None and focus.winfo_class() in ("Entry", "TEntry"):
            return None
        key = event.keysym
        if key == "space":
            self._on_play_pause()
        elif key == "Left":
            self._on_back5()
        elif key == "Right":
            self._on_forward5()
        elif key == "Home":
            self._on_restart()
        elif key in ("Up", "Down"):
            delta = 5.0 if key == "Up" else -5.0
            self.target_bpm = min(max(self.target_bpm + delta, _BPM_MIN), _BPM_MAX)
            self.bpm_slider.set(self.target_bpm)
            self._update_speed_label()
            if self._bpm_after is not None:
                self.after_cancel(self._bpm_after)
            self._bpm_after = self.after(350, self._apply_tempo_async)
        elif key in ("m", "M"):
            self._metronome.set(not self._metronome.get())
            self._on_metronome_toggle()
        return "break"

    def _on_ctrl_wheel(self, event) -> str:
        if event.delta > 0:
            self.score.zoom_in()
        else:
            self.score.zoom_out()
        return "break"

    # ----------------------------------------------------------------- helpers
    def _set_status(self, text: str, error: bool = False) -> None:
        self.status.configure(
            text=text,
            text_color=theme.DANGER if error else theme.TEXT_MUTED,
            font=theme.f_body() if error else theme.f_small(),
        )

    def _on_close(self) -> None:
        self.player.close()
        self.destroy()
