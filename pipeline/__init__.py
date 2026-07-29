"""
pipeline — Orquesta el flujo completo:

    audio (mp3/wav)  --Demucs-->  _drums.wav  +  _sin_bateria.wav
                     --ADTOF-->   _drums.mid
                     --LilyPond-->  _partitura.pdf
                     --librosa-->  BPM

Cada cancion genera su propia subcarpeta dentro de output/.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, replace
from typing import Callable, List, Optional

from .analyze import estimate_tempo_and_meter
from .score import midi_to_pdf
from .separator import separate
from .transcriber import transcribe

__all__ = ["run_pipeline", "retranscribe", "regenerate_score", "PipelineResult"]


def _safe_stem(audio_path: str) -> str:
    """Nombre base de la cancion, sin extension y saneado para archivos/carpeta."""
    stem = os.path.splitext(os.path.basename(audio_path))[0]
    stem = re.sub(r"[^\w\-]+", "_", stem, flags=re.UNICODE).strip("_")
    return stem or "cancion"


@dataclass
class PipelineResult:
    song_name: str
    song_dir: str
    drums_wav: str
    no_drums_wav: str
    drums_mid: str
    score_pdf: str
    bpm: Optional[int]
    beats_per_bar: int = 4
    beat_offset: float = 0.0  # instante (s) del inicio del compas 1
    # Pulsos reales de la cancion (curva de tempo). Permite que la partitura
    # siga el tempo real aunque fluctue (en vivo).
    beat_times: List[float] = field(default_factory=list)
    # Compas como texto ('6/8', '3/4'...); beats_per_bar guarda NEGRAS por compas
    # (6/8 -> 3). Entradas viejas sin meter_label caen al formato N/4.
    meter_label: str = ""

    @property
    def meter(self) -> str:
        """Compas como texto, p. ej. '4/4' o '6/8'."""
        return self.meter_label or f"{self.beats_per_bar}/4"


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

    Genera una subcarpeta output/<cancion>/ con los stems, el MIDI y el PDF, y
    devuelve un PipelineResult con todas las rutas y el BPM estimado.
    """
    stem = _safe_stem(audio_path)
    song_dir = os.path.join(output_dir, stem)
    os.makedirs(song_dir, exist_ok=True)

    drums_wav = os.path.join(song_dir, f"{stem}_drums.wav")
    no_drums_wav = os.path.join(song_dir, f"{stem}_sin_bateria.wav")
    drums_mid = os.path.join(song_dir, f"{stem}_drums.mid")
    score_pdf = os.path.join(song_dir, f"{stem}_partitura.pdf")

    # 1. Separacion (bateria + sin bateria, una sola pasada de Demucs)
    separate(audio_path, drums_wav, no_drums_wav, progress=progress)
    # 2. Transcripcion a MIDI
    transcribe(drums_wav, drums_mid, progress=progress)
    # 3. BPM + compas + beats reales (antes del PDF, para notarlo bien)
    if progress:
        progress("Estimando BPM y compas...")
    bpm, beats_per_bar, beat_offset, beat_times = estimate_tempo_and_meter(drums_wav)
    # 4. Partitura PDF: cuantizada sobre los beats REALES (sigue el tempo aunque
    #    fluctue) y anclada al inicio del compas 1
    score_pdf = midi_to_pdf(
        drums_mid, score_pdf, progress=progress,
        show_rests=show_rests, beats_per_bar=beats_per_bar,
        bpm=bpm, beat_offset=beat_offset, beat_times=beat_times,
        time_label=f"{beats_per_bar}/4",
    )

    return PipelineResult(
        song_name=stem,
        song_dir=song_dir,
        drums_wav=drums_wav,
        no_drums_wav=no_drums_wav,
        drums_mid=drums_mid,
        score_pdf=score_pdf,
        bpm=bpm,
        beats_per_bar=beats_per_bar,
        beat_offset=beat_offset,
        beat_times=beat_times,
        meter_label=f"{beats_per_bar}/4",
    )


def retranscribe(
    prev: PipelineResult,
    show_rests: bool = True,
    progress: Optional[Callable[[str], None]] = None,
) -> PipelineResult:
    """
    Re-ejecuta la transcripcion de una cancion ya separada: ADTOF sobre el
    drums.wav existente, re-analisis de BPM/compas/primer tiempo y regeneracion
    del PDF. NO repite la separacion de Demucs (que es lo lento).
    """
    transcribe(prev.drums_wav, prev.drums_mid, progress=progress)
    if progress:
        progress("Estimando BPM y compas...")
    bpm, beats_per_bar, beat_offset, beat_times = estimate_tempo_and_meter(prev.drums_wav)
    score_pdf = midi_to_pdf(
        prev.drums_mid, prev.score_pdf, progress=progress,
        show_rests=show_rests, beats_per_bar=beats_per_bar,
        bpm=bpm, beat_offset=beat_offset, beat_times=beat_times,
        time_label=f"{beats_per_bar}/4",
    )
    return replace(
        prev,
        score_pdf=score_pdf,
        bpm=bpm,
        beats_per_bar=beats_per_bar,
        beat_offset=beat_offset,
        beat_times=beat_times,
        meter_label=f"{beats_per_bar}/4",
    )


def regenerate_score(
    prev: PipelineResult,
    show_rests: bool = True,
    beat_offset: Optional[float] = None,
    beats_per_bar: Optional[int] = None,
    grid_bpm: Optional[int] = None,
    meter_label: Optional[str] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> PipelineResult:
    """
    Regenera SOLO el PDF a partir del MIDI existente, sin re-transcribir ni
    re-detectar nada. Es el camino para los ajustes MANUALES del usuario:
    `beat_offset` (donde empieza el compas 1) y `beats_per_bar` (compas) anulan
    lo detectado automaticamente.

    `grid_bpm`: si se pasa (pulso Manual validado de oido por el usuario), la
    partitura se cuantiza con una rejilla CONSTANTE a ese BPM anclada en
    `beat_offset`, ignorando los beats detectados. Los beats almacenados se
    conservan en el resultado para poder volver al modo Cancion.
    """
    new_offset = prev.beat_offset if beat_offset is None else float(beat_offset)
    new_bpb = prev.beats_per_bar if beats_per_bar is None else int(beats_per_bar)
    new_label = meter_label or prev.meter_label or f"{new_bpb}/4"
    if grid_bpm:
        quant_bpm, quant_beats = int(grid_bpm), None
    else:
        quant_bpm, quant_beats = prev.bpm, prev.beat_times
    score_pdf = midi_to_pdf(
        prev.drums_mid, prev.score_pdf, progress=progress,
        show_rests=show_rests, beats_per_bar=new_bpb,
        bpm=quant_bpm, beat_offset=new_offset, beat_times=quant_beats,
        time_label=new_label,
    )
    return replace(
        prev, score_pdf=score_pdf, beat_offset=new_offset, beats_per_bar=new_bpb,
        meter_label=new_label,
    )
