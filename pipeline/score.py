r"""
score.py — Convierte un MIDI de batería en una partitura PDF.

Estrategia:
  1. pretty_midi lee el .mid y extrae los golpes (offset en negras + nota MIDI).
  2. Se cuantizan los golpes a una rejilla de semicorcheas (1/16).
  3. Se generan instrucciones LilyPond en modo percusion (\drummode) sobre un
     DrumStaff -> clave de percusion automatica, compas 4/4, sin armadura.
  4. Se compila el .ly con el binario `lilypond` para obtener el PDF.

Nota: se lee con pretty_midi en vez de music21 porque music21 importa la bateria
como objetos Unpitched y descarta el numero de nota MIDI (pierde que golpe es).
El render se hace generando LilyPond a mano, mucho mas fiable que el exportador de
percusion de music21.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Callable, Dict, List, Optional, Set

import pretty_midi

# --- Mapa General MIDI (nota) -> nombre de bateria en LilyPond ---------------
# Nombres validos de \drummode: bd, sn, ss, hh, hhp, hho, hhho, cymc, cymr,
# cyms, rb, tomfl, tomfh, toml, tomml, tomh, etc.
GM_DRUM_TO_LILY: Dict[int, str] = {
    35: "bd", 36: "bd",          # bombo
    37: "ss",                    # rim / side stick
    38: "sn", 40: "sn",          # redoblante
    39: "hc",                    # palmas (hand clap)
    42: "hh", 44: "hhp",         # hi-hat cerrado / con pedal
    46: "hho",                   # hi-hat abierto
    49: "cymc", 57: "cymc",      # crash 1 / 2
    51: "cymr", 59: "cymr",      # ride 1 / 2
    53: "rb",                    # campana del ride
    55: "cyms",                  # splash
    41: "tomfl", 43: "tomfh",    # toms de piso (low floor / high floor)
    45: "toml", 47: "tomml",     # tom bajo / tom medio-bajo
    48: "tomh", 50: "tomh",      # tom alto
}

GRID = 0.25          # rejilla de cuantizacion en negras (0.25 = semicorchea)
SLOTS_PER_MEASURE = 16  # 4/4 con rejilla de semicorcheas


def _resolve_lilypond() -> str:
    """Devuelve la ruta al ejecutable de LilyPond o lanza un error claro."""
    lily = shutil.which("lilypond")
    if lily:
        return lily
    # Rutas habituales en Windows si no esta en el PATH
    for guess in (
        r"C:\Program Files\lilypond\bin\lilypond.exe",
        r"C:\Program Files (x86)\lilypond\bin\lilypond.exe",
    ):
        if os.path.isfile(guess):
            return guess
    raise FileNotFoundError(
        "No se encontro 'lilypond'. Instalalo y agregalo al PATH "
        "(ver README.md). Windows: https://lilypond.org/download.html"
    )


def _extract_events(midi_path: str) -> tuple[List[tuple[float, int]], float]:
    """Lee el MIDI y devuelve (lista de (offset_en_negras, nota_midi), tempo)."""
    pm = pretty_midi.PrettyMIDI(midi_path)

    # Tempo (si el MIDI lo trae); por defecto 120 BPM
    tempo = 120.0
    try:
        _times, tempi = pm.get_tempo_changes()
        if len(tempi):
            tempo = float(tempi[0])
    except Exception:  # noqa: BLE001 — si no hay tempo, usamos el por defecto
        pass

    quarters_per_sec = tempo / 60.0
    events: List[tuple[float, int]] = []
    for inst in pm.instruments:
        for note in inst.notes:
            offset_q = note.start * quarters_per_sec  # segundos -> negras
            events.append((offset_q, int(note.pitch)))

    events.sort(key=lambda e: e[0])
    return events, tempo


def _build_grid(events: List[tuple[float, int]]) -> Dict[int, Set[str]]:
    """Cuantiza los golpes a la rejilla y agrupa por slot -> conjunto de drums."""
    grid: Dict[int, Set[str]] = {}
    for offset, note in events:
        lily_name = GM_DRUM_TO_LILY.get(note)
        if lily_name is None:
            continue  # nota fuera del kit estandar: se ignora
        slot = int(round(offset / GRID))
        grid.setdefault(slot, set()).add(lily_name)
    return grid


def _grid_to_drummode(grid: Dict[int, Set[str]]) -> str:
    """Convierte la rejilla en tokens \\drummode, compas por compas."""
    if not grid:
        raise ValueError(
            "No se detectaron golpes de bateria en el MIDI. "
            "La cancion puede no tener bateria o la transcripcion fallo."
        )

    last_slot = max(grid)
    num_measures = last_slot // SLOTS_PER_MEASURE + 1

    lines: List[str] = []
    for m in range(num_measures):
        tokens: List[str] = []
        for s in range(SLOTS_PER_MEASURE):
            slot = m * SLOTS_PER_MEASURE + s
            hits = grid.get(slot)
            if not hits:
                tokens.append("r16")
            elif len(hits) == 1:
                tokens.append(f"{next(iter(hits))}16")
            else:
                tokens.append("<" + " ".join(sorted(hits)) + ">16")
        lines.append("  " + " ".join(tokens) + " |")
    return "\n".join(lines)


def _write_lilypond(drummode: str, tempo: float, title: str, ly_path: str) -> None:
    """Escribe el archivo .ly completo en disco."""
    content = f"""\\version "2.24.0"

\\header {{
  title = "{title}"
  composer = "Transcrito con Drumly"
  tagline = ##f
}}

\\score {{
  \\new DrumStaff {{
    \\drummode {{
      \\tempo 4 = {int(round(tempo))}
      \\time 4/4
{drummode}
    }}
  }}
  \\layout {{ }}
}}
"""
    with open(ly_path, "w", encoding="utf-8") as fh:
        fh.write(content)


def midi_to_pdf(
    midi_path: str,
    output_pdf_path: str,
    progress: Optional[Callable[[str], None]] = None,
) -> str:
    """
    Convierte `midi_path` en una partitura PDF guardada en `output_pdf_path`.

    `progress` es un callback opcional para reportar el estado (lo usa la UI).
    Devuelve la ruta del PDF generado.
    """
    def report(msg: str) -> None:
        if progress:
            progress(msg)

    lilypond = _resolve_lilypond()

    report("Leyendo MIDI...")
    events, tempo = _extract_events(midi_path)

    report("Cuantizando golpes...")
    grid = _build_grid(events)
    drummode = _grid_to_drummode(grid)

    title = os.path.splitext(os.path.basename(output_pdf_path))[0]
    out_dir = os.path.dirname(os.path.abspath(output_pdf_path))
    os.makedirs(out_dir, exist_ok=True)

    # LilyPond decide la extension: usamos el nombre SIN extension como salida.
    out_base = os.path.splitext(os.path.abspath(output_pdf_path))[0]
    ly_path = out_base + ".ly"
    _write_lilypond(drummode, tempo, title, ly_path)

    report("Generando partitura con LilyPond...")
    result = subprocess.run(
        [lilypond, "--pdf", "-o", out_base, ly_path],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "LilyPond fallo al generar el PDF:\n" + (result.stderr or result.stdout)
        )

    pdf_path = out_base + ".pdf"
    if not os.path.isfile(pdf_path):
        raise RuntimeError("LilyPond termino pero no se encontro el PDF de salida.")

    report("Partitura lista.")
    return pdf_path


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Uso: python -m pipeline.score <archivo.mid> [salida.pdf]")
        raise SystemExit(1)

    midi = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(midi)[0] + "_partitura.pdf"
    pdf = midi_to_pdf(midi, out, progress=print)
    print("PDF generado:", pdf)
