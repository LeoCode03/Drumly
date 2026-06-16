"""
main.py — Punto de entrada de Drumly.

Lanza la interfaz grafica. El pipeline (Demucs -> ADTOF -> music21/LilyPond) se
ejecuta desde la UI en un hilo aparte.
"""

from ui.app import launch

if __name__ == "__main__":
    launch()
