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

import glob
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

# Categoria de cada nota GM, para la vista de practica en pentagrama.
GM_DRUM_TO_CATEGORY: Dict[int, str] = {
    35: "kick", 36: "kick",
    37: "snare", 38: "snare", 40: "snare",
    42: "hihat", 44: "hihat", 46: "hihat",
    49: "cymbal", 51: "cymbal", 53: "cymbal", 55: "cymbal", 57: "cymbal", 59: "cymbal",
    41: "tom", 43: "tom", 45: "tom", 47: "tom", 48: "tom", 50: "tom",
}


def extract_drum_events(midi_path: str) -> tuple[List[tuple[float, str]], float]:
    """
    Para la vista de practica en tiempo real. Devuelve:
      - eventos: lista de (onset_en_segundos, categoria) ordenada por tiempo
      - duracion en segundos

    Se trabaja en SEGUNDOS reales del audio (pretty_midi guarda note.start en
    segundos), asi el cursor -que sigue el audio- cae exactamente sobre las notas.
    """
    pm = pretty_midi.PrettyMIDI(midi_path)
    events: List[tuple[float, str]] = []
    for inst in pm.instruments:
        for note in inst.notes:
            category = GM_DRUM_TO_CATEGORY.get(int(note.pitch))
            if category is not None:
                events.append((float(note.start), category))
    events.sort(key=lambda e: e[0])
    duration = float(pm.get_end_time()) if events else 0.0
    return events, duration


def _lilypond_candidates() -> List[str]:
    """Rutas candidatas a lilypond, en orden de preferencia (sin duplicados)."""
    cands: List[str] = []

    env = os.environ.get("DRUMLY_LILYPOND") or os.environ.get("LILYPOND_PATH")
    if env:
        cands.append(env)

    which = shutil.which("lilypond")
    if which:
        cands.append(which)

    cands += [
        r"C:\Program Files\lilypond\bin\lilypond.exe",
        r"C:\Program Files (x86)\lilypond\bin\lilypond.exe",
        r"C:\LilyPond\bin\lilypond.exe",
    ]
    localapp = os.environ.get("LOCALAPPDATA", "")
    if localapp:
        cands += glob.glob(
            os.path.join(localapp, "Microsoft", "WinGet", "Packages",
                         "LilyPond.LilyPond*", "**", "lilypond.exe"),
            recursive=True,
        )
    cands += glob.glob(r"C:\Program Files\LilyPond*\**\lilypond.exe", recursive=True)

    seen: set[str] = set()
    out: List[str] = []
    for c in cands:
        if c and c not in seen and os.path.isfile(c):
            seen.add(c)
            out.append(c)
    return out


def _lilypond_runs(path: str) -> bool:
    """True si ese lilypond.exe arranca de verdad (--version devuelve 0)."""
    try:
        r = subprocess.run(
            [path, "--version"], capture_output=True, text=True, timeout=30
        )
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _resolve_lilypond() -> str:
    """
    Devuelve un lilypond que REALMENTE arranca. Prueba varias rutas y verifica
    cada una con --version, para no quedarse con una instalacion danada que este
    en el PATH. Da un error claro si ninguna funciona.
    """
    candidates = _lilypond_candidates()
    if not candidates:
        raise FileNotFoundError(
            "No se encontro 'lilypond'. Instalalo y agregalo al PATH "
            "(ver README.md). Windows: https://lilypond.org/download.html"
        )
    for path in candidates:
        if _lilypond_runs(path):
            return path
    raise RuntimeError(
        "LilyPond esta instalado pero no arranca (instalacion danada o bloqueada). "
        "Rutas probadas: " + " | ".join(candidates) + ".\n"
        "Reinstalalo (ver README.md) o define la variable de entorno "
        "DRUMLY_LILYPOND con la ruta a un lilypond.exe que funcione."
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


def _hit_token(hits: Set[str]) -> str:
    """Token LilyPond (semicorchea) para uno o varios golpes simultaneos."""
    if len(hits) == 1:
        return f"{next(iter(hits))}16"
    return "<" + " ".join(sorted(hits)) + ">16"


def _measure_tokens(
    grid: Dict[int, Set[str]], measure: int, rest_char: str = "r"
) -> List[str]:
    """
    Tokens de un compas 4/4, agrupando los silencios para que sea legible:
      - compas entero en silencio  -> redonda
      - tiempo (negra) en silencio  -> negra
      - medio tiempo en silencio    -> corchea
      - resto                       -> notas/silencios de semicorchea (16)
    Las notas se mantienen en semicorcheas; solo se fusionan los silencios.

    `rest_char` es 'r' para silencios visibles o 's' (skip) para tiempo invisible
    que ocupa el compas sin imprimir ningun simbolo.
    """
    base = measure * SLOTS_PER_MEASURE
    if all(grid.get(base + i) is None for i in range(SLOTS_PER_MEASURE)):
        return [f"{rest_char}1"]

    tokens: List[str] = []
    for beat in range(4):  # 4 negras por compas
        b = base + beat * 4
        beat_slots = [grid.get(b + i) for i in range(4)]
        if all(s is None for s in beat_slots):
            tokens.append(f"{rest_char}4")
            continue
        for half in range(2):  # dos mitades (corcheas) por negra
            pair = [beat_slots[half * 2], beat_slots[half * 2 + 1]]
            if pair[0] is None and pair[1] is None:
                tokens.append(f"{rest_char}8")
            else:
                for hits in pair:
                    tokens.append(
                        f"{rest_char}16" if hits is None else _hit_token(hits)
                    )
    return tokens


def _grid_to_drummode(grid: Dict[int, Set[str]], show_rests: bool = True) -> str:
    """
    Convierte la rejilla en tokens \\drummode, compas por compas.

    Si `show_rests` es False se usan 'skips' (s) en vez de silencios (r): el
    tiempo se respeta pero no se imprime ningun simbolo de silencio, asi que solo
    se ven las notas que se tocan.
    """
    if not grid:
        raise ValueError(
            "No se detectaron golpes de bateria en el MIDI. "
            "La cancion puede no tener bateria o la transcripcion fallo."
        )

    rest_char = "r" if show_rests else "s"
    last_slot = max(grid)
    num_measures = last_slot // SLOTS_PER_MEASURE + 1

    lines: List[str] = []
    for m in range(num_measures):
        tokens = _measure_tokens(grid, m, rest_char=rest_char)
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
    show_rests: bool = True,
) -> str:
    """
    Convierte `midi_path` en una partitura PDF guardada en `output_pdf_path`.

    `progress` es un callback opcional para reportar el estado (lo usa la UI).
    `show_rests`: si es False, oculta los silencios y solo muestra las notas tocadas.
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
    drummode = _grid_to_drummode(grid, show_rests=show_rests)

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
        detail = (result.stderr or result.stdout or "").strip()
        msg = f"LilyPond fallo al generar el PDF (codigo {result.returncode})."
        if not detail:
            msg += (
                "\nLilyPond no devolvio ningun mensaje: normalmente significa que su "
                "instalacion esta danada/bloqueada y no arranca. Reinstala LilyPond "
                "(ver README.md) o define DRUMLY_LILYPOND con un lilypond.exe que funcione."
            )
        else:
            msg += "\n" + detail
        raise RuntimeError(msg)

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
