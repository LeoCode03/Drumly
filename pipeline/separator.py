"""
separator.py — Aisla la pista de bateria de una cancion con Demucs (htdemucs).

Demucs 4.0.x (PyPI) no incluye el modulo `demucs.api`, asi que se usa la API de
bajo nivel: get_model + apply_model. Demucs lee MP3 directamente (via ffmpeg) y
separa la mezcla en stems: drums / bass / other / vocals. Guardamos solo "drums".

Detecta automaticamente la GPU (CUDA); si no hay, usa la CPU.
"""

from __future__ import annotations

import glob
import os
import shutil
from typing import Callable, Optional

import torch


def _pick_device() -> str:
    """Devuelve 'cuda' si hay GPU disponible, si no 'cpu'."""
    return "cuda" if torch.cuda.is_available() else "cpu"


def _ensure_ffmpeg_on_path() -> None:
    """
    Demucs necesita ffmpeg/ffprobe. Si no estan en el PATH (p. ej. el usuario
    instalo ffmpeg pero no reinicio la terminal), intentamos localizarlos en las
    rutas tipicas de Windows (winget / chocolatey) y los agregamos al PATH.
    """
    if shutil.which("ffprobe") and shutil.which("ffmpeg"):
        return

    localapp = os.environ.get("LOCALAPPDATA", "")
    program_data = os.environ.get("ProgramData", r"C:\ProgramData")
    patterns = []
    if localapp:
        patterns.append(
            os.path.join(localapp, "Microsoft", "WinGet", "Packages",
                         "Gyan.FFmpeg*", "**", "bin")
        )
    patterns.append(os.path.join(program_data, "chocolatey", "bin"))

    for pattern in patterns:
        for bin_dir in glob.glob(pattern, recursive=True):
            if os.path.isfile(os.path.join(bin_dir, "ffprobe.exe")):
                os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
                return


def separate_drums(
    audio_path: str,
    out_wav: str,
    progress: Optional[Callable[[str], None]] = None,
) -> str:
    """
    Separa la bateria de `audio_path` y la guarda como WAV en `out_wav`.

    `progress` es un callback opcional para reportar estado (lo usa la UI).
    Devuelve la ruta del WAV de bateria.
    """
    def report(msg: str) -> None:
        if progress:
            progress(msg)

    if not os.path.isfile(audio_path):
        raise FileNotFoundError(f"No existe el archivo de audio: {audio_path}")

    _ensure_ffmpeg_on_path()
    if not shutil.which("ffprobe"):
        raise RuntimeError(
            "No se encontro ffmpeg/ffprobe (necesario para leer el audio). "
            "Instalalo (ver README.md) y reinicia la terminal."
        )

    try:
        import soundfile as sf
        from demucs.apply import apply_model
        from demucs.audio import AudioFile
        from demucs.pretrained import get_model
    except ImportError as exc:
        raise ImportError(
            "No se pudo importar Demucs. Instalalo con: pip install demucs\n"
            f"(detalle: {exc})"
        ) from exc

    device = _pick_device()
    report(f"Cargando Demucs (htdemucs) en {device.upper()}...")
    model = get_model("htdemucs")
    model.to(device)
    model.eval()

    report("Leyendo audio...")
    wav = AudioFile(audio_path).read(
        streams=0, samplerate=model.samplerate, channels=model.audio_channels
    )
    # Normalizacion estandar de Demucs
    ref = wav.mean(0)
    std = ref.std() + 1e-8
    wav = (wav - ref.mean()) / std

    report("Separando instrumentos (esto puede tardar)...")
    with torch.no_grad():
        sources = apply_model(
            model, wav[None], device=device, progress=True
        )[0]
    sources = sources * std + ref.mean()

    if "drums" not in model.sources:
        raise RuntimeError(
            "El modelo no expone un stem 'drums'. Stems: " + ", ".join(model.sources)
        )
    drums = sources[model.sources.index("drums")]

    os.makedirs(os.path.dirname(os.path.abspath(out_wav)) or ".", exist_ok=True)
    report("Guardando pista de bateria...")
    # Guardamos con soundfile (espera [frames, canales]) en vez de la utilidad de
    # Demucs, que enruta por torchaudio/torchcodec y es fragil entre versiones.
    sf.write(out_wav, drums.cpu().numpy().T, model.samplerate)

    report("Bateria aislada.")
    return out_wav


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Uso: python -m pipeline.separator <cancion.mp3|wav> [salida_drums.wav]")
        raise SystemExit(1)

    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(src)[0] + "_drums.wav"
    print("WAV generado:", separate_drums(src, out, progress=print))
