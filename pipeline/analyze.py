"""
analyze.py — Analisis musical del audio (BPM y compas).

Usa librosa (ya es dependencia de ADTOF-pytorch). Se analiza la pista de bateria,
que da una pulsacion clara.

La deteccion de compas es una HEURISTICA (aproximada): busca cada cuantas negras
se repite un acento fuerte (candidatos 2, 3, 4). No siempre acierta; por eso en la
vista de practica se puede cambiar a mano.
"""

from __future__ import annotations

from typing import Optional, Tuple


def estimate_bpm(wav_path: str) -> Optional[int]:
    """Estima el tempo (BPM). Devuelve un entero o None. Nunca lanza."""
    bpm, _ = estimate_tempo_and_meter(wav_path)
    return bpm


def estimate_tempo_and_meter(wav_path: str) -> Tuple[Optional[int], int]:
    """
    Estima (BPM, negras_por_compas). El compas se devuelve como numero de negras
    por compas (2, 3 o 4 -> 2/4, 3/4, 4/4). Por defecto 4. Nunca lanza.
    """
    try:
        import librosa
        import numpy as np

        y, sr = librosa.load(wav_path, sr=None, mono=True)
        tempo, beats = librosa.beat.beat_track(y=y, sr=sr)
        bpm: Optional[int] = int(round(float(np.atleast_1d(tempo)[0])))
        if bpm is not None and bpm <= 0:
            bpm = None

        beats_per_bar = _estimate_beats_per_bar(y, sr, beats)
        return bpm, beats_per_bar
    except Exception:  # noqa: BLE001 — informativo, no critico
        return None, 4


def _estimate_beats_per_bar(y, sr, beats) -> int:
    """
    Heuristica: fuerza de onset por negra; para cada candidato B (2,3,4) mide si
    hay una posicion del ciclo que destaca de forma consistente (el acento fuerte
    del compas). Devuelve el B con mayor contraste. Empates -> 4.
    """
    try:
        import librosa
        import numpy as np

        if beats is None or len(beats) < 12:
            return 4

        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        bs = np.asarray(
            librosa.util.sync(onset_env, beats, aggregate=np.mean), dtype=float
        ).ravel()
        if bs.size < 12:
            return 4

        best_b, best_score = 4, -1.0
        for b in (4, 3, 2):  # 4 gana empates
            phase_means = np.array(
                [bs[np.arange(p, bs.size, b)].mean() for p in range(b)]
            )
            score = (phase_means.max() - phase_means.mean()) / (phase_means.std() + 1e-9)
            if score > best_score + 1e-6:
                best_score, best_b = score, b
        return best_b
    except Exception:  # noqa: BLE001
        return 4
