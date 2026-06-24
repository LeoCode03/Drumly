"""
player.py — Mezclador de dos pistas (bateria + sin bateria) con volumen en vivo.

Reproduce ambos stems en un UNICO stream de audio mezclado con sounddevice, lo
que garantiza sincronia perfecta y permite ajustar el volumen de cada pista en
tiempo real. Tambien permite buscar (seek) y exportar la mezcla a WAV.

Es deliberadamente independiente de la UI: la interfaz solo llama a play/pause/
stop/seek, lee position()/duration() para la barra de progreso, y mueve las
ganancias con set_gain_*.
"""

from __future__ import annotations

import threading
from typing import Optional

import numpy as np
import soundfile as sf

try:
    import sounddevice as sd
except Exception:  # noqa: BLE001 — puede no haber PortAudio/dispositivo
    sd = None  # type: ignore[assignment]


def _read_stereo(path: str) -> tuple[np.ndarray, int]:
    """Lee un WAV como float32 estereo [frames, 2]."""
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    return data, sr


class DualTrackPlayer:
    """Reproductor de 2 pistas sincronizadas con volumen independiente."""

    def __init__(self) -> None:
        self._drums: Optional[np.ndarray] = None
        self._no_drums: Optional[np.ndarray] = None
        self.samplerate: int = 44100
        self.gain_drums: float = 1.0
        self.gain_no_drums: float = 1.0

        self._pos: int = 0           # posicion actual en frames
        self._total: int = 0
        self._stream = None
        self._lock = threading.Lock()
        self._finished = False

    # ------------------------------------------------------------------ carga
    def load(self, drums_path: str, no_drums_path: str) -> None:
        drums, sr = _read_stereo(drums_path)
        no_drums, _ = _read_stereo(no_drums_path)
        n = max(len(drums), len(no_drums))
        self._drums = _pad(drums, n)
        self._no_drums = _pad(no_drums, n)
        self.samplerate = sr
        self._total = n
        self._pos = 0
        self._finished = False

    @property
    def loaded(self) -> bool:
        return self._drums is not None and self._total > 0

    @property
    def available(self) -> bool:
        """True si hay backend de audio disponible para reproducir."""
        return sd is not None

    # --------------------------------------------------------------- volumen
    def set_gain_drums(self, value: float) -> None:
        self.gain_drums = max(0.0, float(value))

    def set_gain_no_drums(self, value: float) -> None:
        self.gain_no_drums = max(0.0, float(value))

    # ---------------------------------------------------------------- tiempos
    def duration(self) -> float:
        return self._total / self.samplerate if self._total else 0.0

    def position(self) -> float:
        with self._lock:
            return self._pos / self.samplerate if self._total else 0.0

    def fraction(self) -> float:
        with self._lock:
            return self._pos / self._total if self._total else 0.0

    def seek_fraction(self, frac: float) -> None:
        frac = min(max(frac, 0.0), 1.0)
        with self._lock:
            self._pos = int(frac * self._total)
            self._finished = False

    @property
    def is_playing(self) -> bool:
        return self._stream is not None and self._stream.active

    @property
    def finished(self) -> bool:
        return self._finished

    # ----------------------------------------------------------- reproduccion
    def _callback(self, outdata, frames, time_info, status) -> None:  # noqa: ANN001
        with self._lock:
            start = self._pos
            end = min(start + frames, self._total)
            chunk_d = self._drums[start:end]
            chunk_n = self._no_drums[start:end]
            gd, gn = self.gain_drums, self.gain_no_drums
            self._pos = end
            done = end >= self._total

        mix = chunk_d * gd + chunk_n * gn
        np.clip(mix, -1.0, 1.0, out=mix)

        if len(mix) < frames:  # final: rellenar con silencio y parar
            out = np.zeros((frames, mix.shape[1] if mix.ndim == 2 else 2), dtype="float32")
            out[: len(mix)] = mix
            outdata[:] = out
            self._finished = True
            raise sd.CallbackStop()
        outdata[:] = mix
        if done:
            self._finished = True
            raise sd.CallbackStop()

    def play(self) -> None:
        if not self.loaded:
            return
        if sd is None:
            raise RuntimeError(
                "No hay backend de audio (sounddevice/PortAudio) disponible."
            )
        self._close_stream()
        with self._lock:
            if self._pos >= self._total:
                self._pos = 0
            self._finished = False
        self._stream = sd.OutputStream(
            samplerate=self.samplerate,
            channels=2,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()

    def pause(self) -> None:
        """Detiene la reproduccion conservando la posicion."""
        self._close_stream()

    def stop(self) -> None:
        """Detiene y vuelve al inicio."""
        self._close_stream()
        with self._lock:
            self._pos = 0
            self._finished = False

    def _close_stream(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:  # noqa: BLE001
                pass
            self._stream = None

    # ------------------------------------------------------------- exportar
    def render_mix(self, out_path: str) -> str:
        """Escribe a WAV la mezcla con las ganancias actuales."""
        if not self.loaded:
            raise RuntimeError("No hay audio cargado para exportar.")
        mix = self._drums * self.gain_drums + self._no_drums * self.gain_no_drums
        peak = float(np.max(np.abs(mix))) if mix.size else 0.0
        if peak > 1.0:
            mix = mix / peak
        sf.write(out_path, mix, self.samplerate)
        return out_path

    def close(self) -> None:
        self._close_stream()


def _pad(arr: np.ndarray, n: int) -> np.ndarray:
    """Rellena con ceros hasta n frames (para igualar longitudes)."""
    if len(arr) >= n:
        return arr[:n]
    pad = np.zeros((n - len(arr), arr.shape[1]), dtype=arr.dtype)
    return np.concatenate([arr, pad], axis=0)
