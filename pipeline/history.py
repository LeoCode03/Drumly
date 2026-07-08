"""
history.py — Historial persistente de transcripciones.

Guarda un JSON (output/history.json) con las transcripciones ya hechas para poder
reabrirlas sin volver a subir/procesar el archivo. Cada entrada son los campos de
PipelineResult mas un timestamp.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from typing import Any, Dict, List

_FILENAME = "history.json"


def _path(output_dir: str) -> str:
    return os.path.join(output_dir, _FILENAME)


def load(output_dir: str) -> List[Dict[str, Any]]:
    """Devuelve la lista de entradas (mas reciente primero). Nunca lanza."""
    p = _path(output_dir)
    if not os.path.isfile(p):
        return []
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001
        return []


def save(output_dir: str, entries: List[Dict[str, Any]]) -> None:
    os.makedirs(output_dir, exist_ok=True)
    with open(_path(output_dir), "w", encoding="utf-8") as fh:
        json.dump(entries, fh, ensure_ascii=False, indent=2)


def add(output_dir: str, result: Any) -> None:
    """Anade (o actualiza) la transcripcion. Upsert por song_dir: re-transcribir
    la misma cancion no crea duplicados."""
    entries = load(output_dir)
    entry = asdict(result)
    entry["created_at"] = time.time()
    entries = [e for e in entries if e.get("song_dir") != entry.get("song_dir")]
    entries.insert(0, entry)  # mas reciente primero
    save(output_dir, entries)


def remove(output_dir: str, song_dir: str) -> None:
    """Elimina la entrada del historial (no borra los archivos)."""
    entries = [e for e in load(output_dir) if e.get("song_dir") != song_dir]
    save(output_dir, entries)


def dedupe(output_dir: str) -> int:
    """Colapsa entradas repetidas (misma cancion), conserva la mas reciente.
    Devuelve cuantas se quitaron."""
    entries = load(output_dir)
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for e in entries:
        key = e.get("song_dir") or e.get("song_name")
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    removed = len(entries) - len(out)
    if removed:
        save(output_dir, out)
    return removed
