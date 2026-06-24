"""
analyze.py — Analisis musical del audio (estimacion de BPM).

Usa librosa (ya es dependencia de ADTOF-pytorch). El BPM se estima sobre la
pista de bateria, que da una pulsacion clara.
"""

from __future__ import annotations

from typing import Optional


def estimate_bpm(wav_path: str) -> Optional[int]:
    """
    Estima el tempo (BPM) de un archivo de audio. Devuelve un entero o None si
    no se pudo estimar. Nunca lanza: si falla, devuelve None.
    """
    try:
        import librosa
        import numpy as np

        y, sr = librosa.load(wav_path, sr=None, mono=True)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        bpm = float(np.atleast_1d(tempo)[0])
        if bpm <= 0:
            return None
        return int(round(bpm))
    except Exception:  # noqa: BLE001 — el BPM es informativo, no critico
        return None
