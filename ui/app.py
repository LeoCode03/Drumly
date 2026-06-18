"""
app.py — Interfaz grafica (CustomTkinter) de Drumly.

- Modo oscuro.
- Boton para seleccionar audio (MP3/WAV).
- Barra de progreso indeterminada + texto de etapa.
- El pipeline corre en un hilo aparte para no congelar la UI; los widgets se
  actualizan siempre desde el hilo principal con self.after(...).
- Al terminar: botones para abrir el PDF y la carpeta output.
- Los errores se muestran en rojo en la propia ventana.
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

from pipeline import PipelineResult, run_pipeline

OUTPUT_DIR = os.path.abspath("output")


def _open_path(path: str) -> None:
    """Abre un archivo o carpeta con la aplicacion por defecto del sistema."""
    if platform.system() == "Windows":
        os.startfile(path)  # type: ignore[attr-defined]
    elif platform.system() == "Darwin":
        subprocess.run(["open", path])
    else:
        subprocess.run(["xdg-open", path])


class DrumlyApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("Drumly — Transcriptor de bateria")
        self.geometry("560x420")
        self.minsize(520, 400)

        self._audio_path: Optional[str] = None
        self._result: Optional[PipelineResult] = None
        self._msg_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()

        self._build_widgets()
        self.after(100, self._poll_queue)

    # ---------------------------------------------------------------- widgets
    def _build_widgets(self) -> None:
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=24, pady=24)

        ctk.CTkLabel(
            container, text="🥁 Drumly", font=ctk.CTkFont(size=28, weight="bold")
        ).pack(pady=(0, 4))
        ctk.CTkLabel(
            container,
            text="De MP3/WAV a partitura de bateria en PDF",
            text_color="gray70",
        ).pack(pady=(0, 20))

        self.select_btn = ctk.CTkButton(
            container, text="Seleccionar archivo de audio", command=self._on_select
        )
        self.select_btn.pack(pady=(0, 8))

        self.file_label = ctk.CTkLabel(
            container, text="Ningun archivo seleccionado", text_color="gray60"
        )
        self.file_label.pack(pady=(0, 16))

        self.start_btn = ctk.CTkButton(
            container,
            text="Generar partitura",
            command=self._on_start,
            state="disabled",
            fg_color="#2e7d32",
            hover_color="#1b5e20",
        )
        self.start_btn.pack(pady=(0, 12))

        # Opcion: mostrar u ocultar los silencios en la partitura.
        # Por defecto desactivada -> solo se ven las notas que se tocan.
        self.show_rests_var = ctk.BooleanVar(value=False)
        self.show_rests_check = ctk.CTkCheckBox(
            container,
            text="Mostrar silencios en la partitura",
            variable=self.show_rests_var,
        )
        self.show_rests_check.pack(pady=(0, 18))

        self.progress = ctk.CTkProgressBar(container, mode="indeterminate")
        self.progress.pack(fill="x", pady=(0, 8))
        self.progress.set(0)

        self.stage_label = ctk.CTkLabel(container, text="", text_color="gray80")
        self.stage_label.pack(pady=(0, 8))

        self.error_label = ctk.CTkLabel(
            container, text="", text_color="#ef5350", wraplength=480, justify="left"
        )
        self.error_label.pack(pady=(0, 8))

        # Botones de resultado (ocultos hasta terminar)
        self.result_frame = ctk.CTkFrame(container, fg_color="transparent")
        self.open_pdf_btn = ctk.CTkButton(
            self.result_frame, text="Abrir PDF", command=self._on_open_pdf
        )
        self.open_pdf_btn.pack(side="left", padx=6)
        self.open_folder_btn = ctk.CTkButton(
            self.result_frame,
            text="Abrir carpeta output",
            command=lambda: _open_path(OUTPUT_DIR),
        )
        self.open_folder_btn.pack(side="left", padx=6)

    # ----------------------------------------------------------------- events
    def _on_select(self) -> None:
        path = filedialog.askopenfilename(
            title="Selecciona una cancion",
            filetypes=[("Audio", "*.mp3 *.wav"), ("Todos", "*.*")],
        )
        if not path:
            return
        self._audio_path = path
        self.file_label.configure(
            text=os.path.basename(path), text_color="gray85"
        )
        self.start_btn.configure(state="normal")
        self._clear_result()

    def _on_start(self) -> None:
        if not self._audio_path:
            return
        self._clear_result()
        # Capturamos el valor antes de lanzar el hilo (no tocar widgets desde el hilo).
        self._show_rests = bool(self.show_rests_var.get())
        self._set_busy(True)
        thread = threading.Thread(target=self._run_worker, daemon=True)
        thread.start()

    def _on_open_pdf(self) -> None:
        if self._result and os.path.isfile(self._result.score_pdf):
            _open_path(self._result.score_pdf)

    # ----------------------------------------------------------- worker / UI
    def _run_worker(self) -> None:
        """Corre en un hilo aparte. Comunica con la UI por cola de mensajes."""
        try:
            result = run_pipeline(
                self._audio_path,  # type: ignore[arg-type]
                output_dir=OUTPUT_DIR,
                progress=lambda msg: self._msg_queue.put(("stage", msg)),
                show_rests=getattr(self, "_show_rests", False),
            )
            self._result = result
            self._msg_queue.put(("done", result.score_pdf))
        except Exception as exc:  # noqa: BLE001 — mostramos cualquier error en la UI
            self._msg_queue.put(("error", str(exc)))

    def _poll_queue(self) -> None:
        """Procesa los mensajes del hilo trabajador en el hilo principal."""
        try:
            while True:
                kind, payload = self._msg_queue.get_nowait()
                if kind == "stage":
                    self.stage_label.configure(text=payload)
                elif kind == "done":
                    self._on_finished_ok()
                elif kind == "error":
                    self._on_finished_error(payload)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _on_finished_ok(self) -> None:
        self._set_busy(False)
        self.stage_label.configure(text="✅ Partitura generada con exito")
        self.result_frame.pack(pady=(8, 0))

    def _on_finished_error(self, message: str) -> None:
        self._set_busy(False)
        self.stage_label.configure(text="")
        self.error_label.configure(text=f"❌ Error: {message}")

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

    def _clear_result(self) -> None:
        self._result = None
        self.error_label.configure(text="")
        self.stage_label.configure(text="")
        self.result_frame.pack_forget()


def launch() -> None:
    app = DrumlyApp()
    app.mainloop()
