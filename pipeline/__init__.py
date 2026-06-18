"""
pipeline — Orquesta el flujo completo:

    audio (mp3/wav)  --Demucs-->  _drums.wav
                     --ADTOF-->   _drums.mid
                     --music21+LilyPond-->  _partitura.pdf
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Callable, Optional

from .score import midi_to_pdf
from .separator import separate_drums
from .transcriber import transcribe

__all__ = ["run_pipeline", "PipelineResult"]


def _safe_stem(audio_path: str) -> str:
    """Nombre base de la cancion, sin extension y saneado para archivos."""
    stem = os.path.splitext(os.path.basename(audio_path))[0]
    stem = re.sub(r"[^\w\-]+", "_", stem, flags=re.UNICODE).strip("_")
    return stem or "cancion"


@dataclass
class PipelineResult:
    drums_wav: str
    drums_mid: str
    score_pdf: str


def run_pipeline(
    audio_path: str,
    output_dir: str = "output",
    progress: Optional[Callable[[str], None]] = None,
    show_rests: bool = True,
) -> PipelineResult:
    """
    Ejecuta el pipeline completo sobre `audio_path`.

    `progress(msg)` se llama con texto descriptivo en cada etapa (lo usa la UI).
    `show_rests`: si es False, la partitura oculta los silencios (solo notas tocadas).
    Devuelve un PipelineResult con las rutas de los 3 archivos generados.
    """
    os.makedirs(output_dir, exist_ok=True)
    stem = _safe_stem(audio_path)

    drums_wav = os.path.join(output_dir, f"{stem}_drums.wav")
    drums_mid = os.path.join(output_dir, f"{stem}_drums.mid")
    score_pdf = os.path.join(output_dir, f"{stem}_partitura.pdf")

    # 1. Separacion
    separate_drums(audio_path, drums_wav, progress=progress)
    # 2. Transcripcion a MIDI
    transcribe(drums_wav, drums_mid, progress=progress)
    # 3. Partitura PDF
    score_pdf = midi_to_pdf(drums_mid, score_pdf, progress=progress, show_rests=show_rests)

    return PipelineResult(drums_wav=drums_wav, drums_mid=drums_mid, score_pdf=score_pdf)
