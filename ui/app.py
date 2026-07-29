"""
app.py — Interfaz grafica (CustomTkinter) de Drumly.

Dos vistas:
  1. Entrada: seleccionar audio, opciones y generar (pipeline en hilo aparte).
  2. Mezclador (estilo reproductor de stems): volumen de bateria / sin bateria en
     vivo, play/pausa, barra de progreso con tiempo, BPM y boton Export.

Regla de oro de Tkinter: el pipeline corre en un hilo, pero los widgets solo se
tocan desde el hilo principal (via cola de mensajes + self.after).
"""

from __future__ import annotations

import os
import platform
import queue
import subprocess
import threading
from typing import Optional

import customtkinter as ctk
from tkinter import filedialog

from dataclasses import fields as _dc_fields

from pipeline import (
    PipelineResult, history, regenerate_score, retranscribe, run_pipeline,
)
from ui import theme
from ui.icons import icon
from ui.player import DualTrackPlayer
from ui.practice import PracticeWindow

OUTPUT_DIR = os.path.abspath("output")

ACCENT = theme.ACCENT
ACCENT_HOVER = theme.ACCENT_HOVER
VOL_MIN = 0
VOL_MAX = 150


def _open_path(path: str) -> None:
    """Abre un archivo o carpeta con la aplicacion por defecto del sistema."""
    if platform.system() == "Windows":
        os.startfile(path)  # type: ignore[attr-defined]
    elif platform.system() == "Darwin":
        subprocess.run(["open", path])
    else:
        subprocess.run(["xdg-open", path])


def _fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class DrumlyApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__(fg_color=theme.SURFACE1)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("green")

        self.title("Drumly — Transcriptor de bateria")
        self.geometry("480x760")
        self.minsize(440, 680)

        self._audio_path: Optional[str] = None
        self._result: Optional[PipelineResult] = None
        self._msg_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()

        self.player = DualTrackPlayer()
        self._user_seeking = False

        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)
        # Los textos largos se reajustan al ancho real de la ventana.
        self.container.bind("<Configure>", self._on_container_resize)

        self._build_input_view()
        self._build_mixer_view()
        self._show_input()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # Mezclador operable por teclado (cuando esta visible y hay cancion)
        self.bind("<space>", self._on_key)
        self.bind("<Left>", self._on_key)
        self.bind("<Right>", self._on_key)
        self.after(100, self._poll_queue)
        self.after(200, self._tick)

    # ============================================================ VISTA ENTRADA
    def _build_input_view(self) -> None:
        f = ctk.CTkFrame(self.container, fg_color="transparent")
        self.input_frame = f

        ctk.CTkLabel(f, text=" Drumly", image=icon("drum", 30), compound="left",
                     font=ctk.CTkFont(size=30, weight="bold")).pack(
            pady=(10, 4)
        )
        ctk.CTkLabel(
            f, text="De MP3/WAV a partitura de bateria en PDF", text_color=theme.TEXT_MUTED
        ).pack(pady=(0, 24))

        self.select_btn = ctk.CTkButton(
            f, text=" Seleccionar archivo de audio", image=icon("file-music", 18),
            compound="left", command=self._on_select, height=40, font=theme.f_body()
        )
        self.select_btn.pack(pady=(0, 8), fill="x")

        self.file_label = ctk.CTkLabel(
            f, text="Ningun archivo seleccionado", text_color=theme.TEXT_FAINT
        )
        self.file_label.pack(pady=(0, 16))

        self.start_btn = ctk.CTkButton(
            f, text=" Generar partitura", image=icon("file-text", 18, "dark"),
            compound="left", command=self._on_start, state="disabled",
            height=44, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color=theme.ON_ACCENT, font=theme.font(16, bold=True),
        )
        self.start_btn.pack(pady=(0, 14), fill="x")

        self.show_rests_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            f, text="Mostrar silencios en la partitura", variable=self.show_rests_var
        ).pack(pady=(0, 18))

        self.progress = ctk.CTkProgressBar(f, mode="indeterminate")
        self.progress.pack(fill="x", pady=(0, 8))
        self.progress.set(0)

        self.stage_label = ctk.CTkLabel(f, text="", text_color=theme.TEXT_MUTED)
        self.stage_label.pack(pady=(0, 8))

        self.error_label = ctk.CTkLabel(
            f, text="", text_color=theme.DANGER, wraplength=420, justify="left"
        )
        self.error_label.pack(pady=(0, 8))

        # --- Historial de transcripciones ---
        hist_head = ctk.CTkFrame(f, fg_color="transparent")
        hist_head.pack(fill="x", pady=(6, 4))
        ctk.CTkLabel(
            hist_head, text="Historial", font=ctk.CTkFont(size=14, weight="bold")
        ).pack(side="left")
        ctk.CTkButton(
            hist_head, text="Eliminar duplicados", width=140, height=26,
            fg_color=theme.SURFACE4, hover_color=theme.SURFACE4, command=self._on_dedupe,
        ).pack(side="right")

        self.history_frame = ctk.CTkScrollableFrame(f, fg_color=theme.SURFACE2)
        self.history_frame.pack(fill="both", expand=True)
        self._refresh_history()

    # ============================================================ VISTA MEZCLADOR
    def _build_mixer_view(self) -> None:
        f = ctk.CTkFrame(self.container, fg_color="transparent")
        self.mixer_frame = f

        # --- Barra superior: volver + titulo ---
        top = ctk.CTkFrame(f, fg_color="transparent")
        top.pack(fill="x", pady=(0, 18))
        ctk.CTkButton(
            top, text="←", width=40, height=36, command=self._show_input,
            fg_color="transparent", hover_color=theme.SURFACE3,
            font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(side="left")
        self.song_title = ctk.CTkLabel(
            top, text="", font=theme.f_title(), wraplength=320
        )
        self.song_title.pack(side="left", expand=True)

        # --- Pista: Bateria ---
        self._build_track_row(f, "drum", "Bateria", self._on_vol_drums)
        # --- Pista: Otros (sin bateria) ---
        self._build_track_row(f, "music", "Banda", self._on_vol_no_drums)

        # espacio flexible
        ctk.CTkFrame(f, fg_color="transparent", height=40).pack(expand=True, fill="both")

        # --- Barra de progreso + tiempos ---
        self.seek = ctk.CTkSlider(f, from_=0, to=1, command=self._on_seek)
        self.seek.set(0)
        self.seek.pack(fill="x", pady=(0, 4))
        self.seek.bind("<ButtonPress-1>", lambda e: setattr(self, "_user_seeking", True))
        self.seek.bind("<ButtonRelease-1>", self._on_seek_release)

        times = ctk.CTkFrame(f, fg_color="transparent")
        times.pack(fill="x", pady=(0, 16))
        self.time_cur = ctk.CTkLabel(times, text="00:00", text_color=theme.TEXT_MUTED,
                                     font=theme.f_small())
        self.time_cur.pack(side="left")
        self.time_total = ctk.CTkLabel(times, text="00:00", text_color=theme.TEXT_MUTED,
                                       font=theme.f_small())
        self.time_total.pack(side="right")

        # --- Controles: BPM | Play | PDF ---
        controls = ctk.CTkFrame(f, fg_color="transparent")
        controls.pack(fill="x", pady=(0, 18))
        controls.grid_columnconfigure((0, 1, 2), weight=1)

        bpm_box = ctk.CTkFrame(controls, fg_color="transparent")
        bpm_box.grid(row=0, column=0)
        ctk.CTkLabel(bpm_box, text="", image=icon("timer", 24)).pack()
        self.bpm_label = ctk.CTkLabel(
            bpm_box, text="-- BPM", font=theme.font(16, bold=True)
        )
        self.bpm_label.pack()

        self.play_btn = ctk.CTkButton(
            controls, text="", image=icon("play", 26), width=64, height=64,
            corner_radius=32, command=self._on_play_pause,
            fg_color=theme.SURFACE3, hover_color=theme.SURFACE4,
        )
        self.play_btn.grid(row=0, column=1)

        pdf_box = ctk.CTkFrame(controls, fg_color="transparent")
        pdf_box.grid(row=0, column=2)
        ctk.CTkButton(
            pdf_box, text="", image=icon("file-text", 22), width=48, height=40,
            command=self._on_open_pdf,
            fg_color="transparent", hover_color=theme.SURFACE3,
        ).pack()
        ctk.CTkLabel(pdf_box, text="Partitura", text_color=theme.TEXT_MUTED,
                     font=theme.f_small()).pack()

        # --- Practicar en tiempo real: LA accion primaria del producto ---
        self.practice_btn = ctk.CTkButton(
            f, text=" Practicar en tiempo real", image=icon("target", 20, "dark"),
            compound="left", command=self._on_practice,
            height=48, corner_radius=theme.RAD_PILL,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color=theme.ON_ACCENT, font=theme.font(16, bold=True),
        )
        self.practice_btn.pack(fill="x", pady=(0, 8))

        # --- Re-transcribir (sin repetir la separacion de Demucs) ---
        self.retrans_btn = ctk.CTkButton(
            f, text=" Re-transcribir", image=icon("refresh-cw", 16),
            compound="left", command=self._on_retranscribe,
            height=36, corner_radius=18, fg_color=theme.SURFACE3,
            hover_color=theme.SURFACE4, font=theme.f_body(),
        )
        self.retrans_btn.pack(fill="x", pady=(0, 8))

        # --- Exportar (accion secundaria: neutra, no compite con Practicar) ---
        self.export_btn = ctk.CTkButton(
            f, text=" Exportar", image=icon("download", 16), compound="left",
            command=self._on_export, height=40,
            corner_radius=theme.RAD_PILL, fg_color=theme.SURFACE3,
            hover_color=theme.SURFACE4, font=theme.f_body(),
        )
        self.export_btn.pack(fill="x", pady=(0, 4))

        self.mixer_msg = ctk.CTkLabel(f, text="", text_color=theme.TEXT_MUTED,
                                      font=theme.f_small())
        self.mixer_msg.pack(pady=(4, 0))

    def _build_track_row(self, parent, icon_name: str, name: str, command) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=8)
        ctk.CTkLabel(
            row, text="", image=icon(icon_name, 24), width=48, height=48,
            corner_radius=12, fg_color=theme.ACCENT_TINT,
        ).pack(side="left", padx=(0, 14))
        col = ctk.CTkFrame(row, fg_color="transparent")
        col.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(col, text=name, anchor="w", text_color=theme.TEXT_MUTED,
                     font=theme.f_body()).pack(
            fill="x", pady=(0, 2)
        )
        slider = ctk.CTkSlider(
            col, from_=VOL_MIN, to=VOL_MAX, number_of_steps=VOL_MAX - VOL_MIN,
            command=command,
        )
        slider.set(100)
        slider.pack(fill="x")

    # ----------------------------------------------------------- cambios de vista
    def _show_input(self) -> None:
        self.player.pause()
        self.mixer_frame.pack_forget()
        self.input_frame.pack(fill="both", expand=True)

    def _show_mixer(self) -> None:
        self.input_frame.pack_forget()
        self.mixer_frame.pack(fill="both", expand=True)

    # ----------------------------------------------------------------- eventos
    def _on_select(self) -> None:
        path = filedialog.askopenfilename(
            title="Selecciona una cancion",
            filetypes=[("Audio", "*.mp3 *.wav"), ("Todos", "*.*")],
        )
        if not path:
            return
        self._audio_path = path
        self.file_label.configure(text=os.path.basename(path), text_color=theme.TEXT)
        self.start_btn.configure(state="normal")
        self.error_label.configure(text="")
        self.stage_label.configure(text="")

    def _on_start(self) -> None:
        if not self._audio_path:
            return
        self.error_label.configure(text="")
        self._show_rests = bool(self.show_rests_var.get())
        self._set_busy(True)
        threading.Thread(target=self._run_worker, daemon=True).start()

    def _on_open_pdf(self) -> None:
        if self._result and os.path.isfile(self._result.score_pdf):
            _open_path(self._result.score_pdf)

    # --- volumen / seek / play ---
    def _on_vol_drums(self, value: float) -> None:
        self.player.set_gain_drums(value / 100.0)

    def _on_vol_no_drums(self, value: float) -> None:
        self.player.set_gain_no_drums(value / 100.0)

    def _on_seek(self, value: float) -> None:
        if self.player.loaded:
            self.player.seek_fraction(float(value))

    def _on_seek_release(self, _event) -> None:
        self._user_seeking = False

    def _on_play_pause(self) -> None:
        if not self.player.loaded:
            return
        if self.player.is_playing:
            self.player.pause()
            self.play_btn.configure(image=icon("play", 26), text="")
        else:
            try:
                self.player.play()
                self.play_btn.configure(image=icon("pause", 26), text="")
            except Exception as exc:  # noqa: BLE001
                self.mixer_msg.configure(text=f"No se pudo reproducir: {exc}")

    def _on_export(self) -> None:
        if not self._result:
            return
        ExportDialog(self, self._result, self.player)

    def _on_container_resize(self, event) -> None:
        w = max(event.width - 24, 200)
        self.error_label.configure(wraplength=w)
        self.song_title.configure(wraplength=max(w - 100, 160))

    def _on_key(self, event) -> str | None:
        """Espacio = play/pausa, flechas = ±5 s (solo en el mezclador)."""
        focus = self.focus_get()
        if focus is not None and focus.winfo_class() in ("Entry", "TEntry"):
            return None
        if not (self.mixer_frame.winfo_ismapped() and self.player.loaded):
            return None
        if event.keysym == "space":
            self._on_play_pause()
        elif event.keysym in ("Left", "Right"):
            dur = self.player.duration()
            if dur > 0:
                cur = self.player.fraction() * dur
                delta = -5.0 if event.keysym == "Left" else 5.0
                frac = min(max((cur + delta) / dur, 0.0), 1.0)
                self.player.seek_fraction(frac)
        return "break"

    def _on_practice(self) -> None:
        if not self._result:
            return
        # La practica reproduce solo bateria: pausamos el mezclador para no solapar.
        self.player.pause()
        self.play_btn.configure(image=icon("play", 26), text="")
        win = PracticeWindow(
            self, self._result.drums_mid, self._result.drums_wav,
            self._result.bpm, self._result.song_name,
            beats_per_bar=self._result.beats_per_bar,
            no_drums_wav=self._result.no_drums_wav,
            drums_gain=self.player.gain_drums,
            no_drums_gain=self.player.gain_no_drums,
            beat_offset=self._result.beat_offset,
            beat_times=self._result.beat_times,
            on_apply=self._on_practice_apply,
            meter_label=self._result.meter,
        )
        win.focus()

    def _on_practice_apply(self, beat_offset: float, beats_per_bar: int,
                           status_cb, manual_bpm=None,
                           meter_label=None) -> None:
        """
        Aplica los ajustes MANUALES hechos en la practica (inicio del compas 1,
        compas y, si el pulso era Manual, esa rejilla de BPM fija) a la
        partitura: regenera solo el PDF (sin re-transcribir) y persiste el
        ajuste en el resultado y el historial.
        """
        if not self._result:
            status_cb("No hay transcripcion activa.")
            return
        prev = self._result
        show_rests = bool(self.show_rests_var.get())

        def work() -> None:
            try:
                result = regenerate_score(
                    prev, show_rests=show_rests,
                    beat_offset=beat_offset, beats_per_bar=beats_per_bar,
                    grid_bpm=manual_bpm, meter_label=meter_label,
                )
                def done() -> None:
                    self._result = result
                    try:
                        history.add(OUTPUT_DIR, result)
                    except Exception:  # noqa: BLE001
                        pass
                    self._refresh_history()
                    bpm_txt = f"{result.bpm} BPM" if result.bpm else "-- BPM"
                    self.bpm_label.configure(text=f"{bpm_txt} · {result.meter}")
                    status_cb("Partitura regenerada con el nuevo inicio/compas.")
                self.after(0, done)
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                self.after(0, lambda: status_cb(f"Error: {msg}"))

        threading.Thread(target=work, daemon=True).start()

    def _on_retranscribe(self) -> None:
        """Re-ejecuta ADTOF + analisis + PDF sobre los stems ya separados."""
        if not self._result:
            return
        self.player.pause()
        self.play_btn.configure(image=icon("play", 26), text="")
        for btn in (self.practice_btn, self.retrans_btn, self.export_btn):
            btn.configure(state="disabled")
        show_rests = bool(self.show_rests_var.get())
        prev = self._result

        def work() -> None:
            try:
                result = retranscribe(
                    prev, show_rests=show_rests,
                    progress=lambda msg: self._msg_queue.put(("rstage", msg)),
                )
                self._msg_queue.put(("rdone", result))
            except Exception as exc:  # noqa: BLE001
                self._msg_queue.put(("rerror", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    # ----------------------------------------------------------- worker / UI
    def _run_worker(self) -> None:
        try:
            result = run_pipeline(
                self._audio_path,  # type: ignore[arg-type]
                output_dir=OUTPUT_DIR,
                progress=lambda msg: self._msg_queue.put(("stage", msg)),
                show_rests=getattr(self, "_show_rests", False),
            )
            self._result = result
            self._msg_queue.put(("done", ""))
        except Exception as exc:  # noqa: BLE001
            self._msg_queue.put(("error", str(exc)))

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self._msg_queue.get_nowait()
                if kind == "stage":
                    self.stage_label.configure(text=payload)
                elif kind == "done":
                    self._on_finished_ok()
                elif kind == "error":
                    self._on_finished_error(payload)
                elif kind == "rstage":
                    self.mixer_msg.configure(text=payload, text_color=theme.TEXT_MUTED)
                elif kind == "rdone":
                    self._on_retranscribe_done(payload)
                elif kind == "rerror":
                    self._on_retranscribe_error(payload)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _on_finished_ok(self) -> None:
        self._set_busy(False)
        self.stage_label.configure(text="")
        result = self._result
        assert result is not None
        # Guardar en el historial y refrescar la lista.
        try:
            history.add(OUTPUT_DIR, result)
        except Exception:  # noqa: BLE001
            pass
        self._refresh_history()
        self._display_result(result)

    def _display_result(self, result: PipelineResult) -> None:
        """Carga los stems en el reproductor y abre la vista mezclador."""
        self._result = result
        try:
            self.player.load(result.drums_wav, result.no_drums_wav)
        except Exception as exc:  # noqa: BLE001
            self.mixer_msg.configure(text=f"Audio no disponible: {exc}")

        self.song_title.configure(text=result.song_name)
        bpm_txt = f"{result.bpm} BPM" if result.bpm else "-- BPM"
        self.bpm_label.configure(text=f"{bpm_txt} · {result.meter}")
        self.time_total.configure(text=_fmt_time(self.player.duration()))
        self.time_cur.configure(text="00:00")
        self.seek.set(0)
        self.play_btn.configure(image=icon("play", 26), text="")
        self.mixer_msg.configure(
            text="" if self.player.available else "Sin dispositivo de audio para reproducir."
        )
        self._show_mixer()

    # -------------------------------------------------------------- historial
    def _refresh_history(self) -> None:
        for w in self.history_frame.winfo_children():
            w.destroy()
        entries = history.load(OUTPUT_DIR)
        if not entries:
            ctk.CTkLabel(
                self.history_frame,
                text="Aun no hay transcripciones.\nSelecciona un audio arriba "
                     "para crear la primera.",
                text_color=theme.TEXT_FAINT, font=theme.f_small(),
            ).pack(pady=12)
            return
        valid_fields = {fld.name for fld in _dc_fields(PipelineResult)}
        for entry in entries:
            row = ctk.CTkFrame(self.history_frame, fg_color=theme.SURFACE3)
            row.pack(fill="x", pady=3, padx=2)
            bpm = entry.get("bpm")
            meter = f"{entry.get('beats_per_bar', 4)}/4"
            sub = f"{bpm} BPM · {meter}" if bpm else meter
            ctk.CTkButton(
                row, image=icon("music", 16), compound="left",
                text=f"  {entry.get('song_name', '?')}\n{sub}",
                anchor="w", fg_color="transparent", hover_color=theme.SURFACE3,
                command=lambda e=entry: self._open_history_entry(e, valid_fields),
            ).pack(side="left", fill="x", expand=True)
            del_btn = ctk.CTkButton(
                row, text="", image=icon("trash-2", 16), width=44, height=32, fg_color="transparent",
                hover_color=theme.DANGER_HOVER_BG, font=theme.f_small(),
            )
            del_btn.configure(
                command=lambda e=entry, b=del_btn: self._confirm_delete(b, e))
            del_btn.pack(side="right", padx=4)

    def _open_history_entry(self, entry: dict, valid_fields: set) -> None:
        data = {k: v for k, v in entry.items() if k in valid_fields}
        try:
            result = PipelineResult(**data)
        except Exception as exc:  # noqa: BLE001
            self.error_label.configure(text=f"Entrada invalida: {exc}")
            return
        if not (os.path.isfile(result.drums_wav) or os.path.isfile(result.score_pdf)):
            self.error_label.configure(
                text="Faltan los archivos de esta transcripcion (¿carpeta borrada?).",
                text_color=theme.DANGER,
            )
            return
        self.error_label.configure(text="")
        self._display_result(result)

    def _confirm_delete(self, btn, entry: dict) -> None:
        """Borrado en dos pasos: el primer clic arma el boton ('Borrar?') 3 s;
        el segundo dentro de ese lapso elimina la entrada del historial."""
        if getattr(btn, "_armed", False):
            history.remove(OUTPUT_DIR, entry.get("song_dir", ""))
            self._refresh_history()
            return
        btn._armed = True
        btn.configure(text="Borrar?", width=70, fg_color=theme.DANGER,
                      text_color=theme.ON_ACCENT)
        def disarm() -> None:
            if btn.winfo_exists():
                btn._armed = False
                btn.configure(text="", image=icon("trash-2", 16), width=44, fg_color="transparent",
                              text_color=theme.TEXT)
        self.after(3000, disarm)

    def _on_dedupe(self) -> None:
        removed = history.dedupe(OUTPUT_DIR)
        self._refresh_history()
        self.error_label.configure(
            text=(f"Se quitaron {removed} duplicados." if removed
                  else "No habia duplicados."),
            text_color=theme.TEXT_MUTED if not removed else theme.ACCENT,
        )

    def _on_finished_error(self, message: str) -> None:
        self._set_busy(False)
        self.stage_label.configure(text="")
        self.error_label.configure(text=f"Error: {message}", text_color=theme.DANGER)

    def _on_retranscribe_done(self, result: PipelineResult) -> None:
        for btn in (self.practice_btn, self.retrans_btn, self.export_btn):
            btn.configure(state="normal")
        try:
            history.add(OUTPUT_DIR, result)
        except Exception:  # noqa: BLE001
            pass
        self._refresh_history()
        self._display_result(result)
        self.mixer_msg.configure(
            text="Transcripcion regenerada", text_color=theme.ACCENT
        )

    def _on_retranscribe_error(self, message: str) -> None:
        for btn in (self.practice_btn, self.retrans_btn, self.export_btn):
            btn.configure(state="normal")
        self.mixer_msg.configure(text=f"Error: {message}", text_color=theme.DANGER)

    def _tick(self) -> None:
        """Actualiza la barra de progreso y el tiempo durante la reproduccion."""
        if self.player.loaded and not self._user_seeking:
            self.time_cur.configure(text=_fmt_time(self.player.position()))
            self.seek.set(self.player.fraction())
            if self.player.finished and not self.player.is_playing:
                self.play_btn.configure(image=icon("play", 26), text="")
        self.after(200, self._tick)

    # ----------------------------------------------------------------- helpers
    def _set_busy(self, busy: bool) -> None:
        if busy:
            self.progress.start()
            self.select_btn.configure(state="disabled")
            self.start_btn.configure(state="disabled")
        else:
            self.progress.stop()
            self.progress.set(0)
            self.select_btn.configure(state="normal")
            self.start_btn.configure(state="normal")

    def _on_close(self) -> None:
        self.player.close()
        self.destroy()


class ExportDialog(ctk.CTkToplevel):
    """Pequeno menu de exportacion (mezcla / PDF / carpeta)."""

    def __init__(self, master, result: PipelineResult, player: DualTrackPlayer) -> None:
        super().__init__(master, fg_color=theme.SURFACE1)
        self.title("Exportar")
        self.geometry("380x280")
        self.minsize(380, 280)
        self.result = result
        self.player = player
        self.transient(master)
        self.grab_set()
        self.bind("<Escape>", lambda e: self.destroy())

        ctk.CTkLabel(
            self, text="Exportar", font=theme.f_title()
        ).pack(pady=(18, 12))

        ctk.CTkButton(
            self, text=" Mezcla de audio (WAV)", image=icon("audio-lines", 18), compound="left", height=42, command=self._export_mix
        ).pack(fill="x", padx=20, pady=6)
        ctk.CTkButton(
            self, text=" Partitura PDF", image=icon("file-text", 18), compound="left", height=42, command=self._export_pdf
        ).pack(fill="x", padx=20, pady=6)
        ctk.CTkButton(
            self, text=" Abrir carpeta de la cancion", image=icon("folder-open", 18), compound="left", height=42,
            command=self._open_folder,
        ).pack(fill="x", padx=20, pady=6)

        self.msg = ctk.CTkLabel(self, text="", text_color=theme.TEXT_MUTED, wraplength=320)
        self.msg.pack(pady=(8, 0))

    def _export_mix(self) -> None:
        default = os.path.join(self.result.song_dir, f"{self.result.song_name}_mezcla.wav")
        path = filedialog.asksaveasfilename(
            parent=self, title="Guardar mezcla", defaultextension=".wav",
            initialfile=os.path.basename(default), initialdir=self.result.song_dir,
            filetypes=[("WAV", "*.wav")],
        )
        if not path:
            return
        try:
            self.player.render_mix(path)
            self.msg.configure(text=f"Mezcla guardada:\n{os.path.basename(path)}")
        except Exception as exc:  # noqa: BLE001
            self.msg.configure(text=f"Error: {exc}")

    def _export_pdf(self) -> None:
        if os.path.isfile(self.result.score_pdf):
            _open_path(self.result.score_pdf)
            self.msg.configure(text="Abriendo PDF...")
        else:
            self.msg.configure(text="No se encontro el PDF.")

    def _open_folder(self) -> None:
        _open_path(self.result.song_dir)
        self.msg.configure(text="Abriendo carpeta...")


def launch() -> None:
    app = DrumlyApp()
    app.mainloop()
