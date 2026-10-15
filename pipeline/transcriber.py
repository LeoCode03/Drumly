"""
transcriber.py — Transcribe la pista de bateria (WAV) a MIDI con ADTOF-pytorch.

Se usa la implementacion PyTorch de ADTOF (xavriley/ADTOF-pytorch), que solo
depende de torch/librosa/pretty_midi y trae los pesos del modelo incluidos:

    from adtof_pytorch import transcribe_to_midi
    transcribe_to_midi("drums.wav", "drums.mid", device="cpu")

El modelo emite 5 clases con notas General MIDI:
    35=bombo, 38=redoblante, 47=tom, 42=hi-hat, 49=crash
que es justo lo que espera pipeline/score.py.
"""

from __future__ import annotations

import os
from typing import Callable, Optional

import torch


def _pick_device() -> str:
    """Devuelve 'cuda' si hay GPU disponible, si no 'cpu'."""
    return "cuda" if torch.cuda.is_available() else "cpu"


def transcribe(
    drums_wav: str,
    midi_out: str,
    progress: Optional[Callable[[str], None]] = None,
) -> str:
    """
    Transcribe `drums_wav` a un archivo MIDI guardado en `midi_out`.

    `progress` es un callback opcional para reportar estado (lo usa la UI).
    Devuelve la ruta del MIDI generado.
    """
    def report(msg: str) -> None:
        if progress:
            progress(msg)

    if not os.path.isfile(drums_wav):
        raise FileNotFoundError(f"Drum WAV not found: {drums_wav}")

    try:
        from adtof_pytorch import transcribe_to_midi
    except ImportError as exc:  # mensaje claro para la UI
        raise ImportError(
            "Could not import ADTOF-pytorch. Install it with:\n"
            "  pip install git+https://github.com/xavriley/ADTOF-pytorch.git\n"
            f"(details: {exc})"
        ) from exc

    os.makedirs(os.path.dirname(os.path.abspath(midi_out)) or ".", exist_ok=True)

    device = _pick_device()
    report(f"Transcribing drums to MIDI (ADTOF, {device.upper()})...")
    result_path = transcribe_to_midi(drums_wav, midi_out, device=device)

    out = str(result_path)
    if not os.path.isfile(out):
        raise RuntimeError(
            "ADTOF did not produce any MIDI. Check that the WAV contains drums."
        )

    report("Drum MIDI ready.")
    return out


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m pipeline.transcriber <drums.wav> [output.mid]")
        raise SystemExit(1)

    wav = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(wav)[0] + ".mid"
    print("MIDI generated:", transcribe(wav, out, progress=print))
