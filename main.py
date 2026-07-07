"""
main.py — Punto de entrada de Drumly.

Lanza la interfaz grafica. El pipeline (Demucs -> ADTOF -> LilyPond) se ejecuta
desde la UI en un hilo aparte.
"""

import os
import sys


def _ensure_std_streams() -> None:
    """
    Bajo pythonw.exe (acceso directo sin consola) sys.stdout/sys.stderr son None.
    Muchas librerias escriben ahi (tqdm de Demucs, prints de ADTOF, descargas de
    torch) y eso provoca: 'NoneType' object has no attribute 'write'.
    Los redirigimos a un archivo de log para que nada falle y quede rastro.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    sink = None
    try:
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "drumly.log")
        sink = open(log_path, "a", encoding="utf-8", buffering=1)
    except Exception:  # noqa: BLE001 — si no se puede escribir, usamos devnull
        try:
            sink = open(os.devnull, "w")
        except Exception:  # noqa: BLE001
            sink = None
    if sink is not None:
        if sys.stdout is None:
            sys.stdout = sink
        if sys.stderr is None:
            sys.stderr = sink


_ensure_std_streams()

from ui.app import launch  # noqa: E402  (import despues de fijar los streams)

if __name__ == "__main__":
    launch()
