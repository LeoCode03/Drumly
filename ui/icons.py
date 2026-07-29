"""
icons.py — Iconos Lucide (https://github.com/lucide-icons/lucide, ISC license)
rasterizados a PNG en ui/icons/ (generados en dev; ver README).

Uso:
    from ui.icons import icon
    ctk.CTkButton(..., image=icon("play", 20), text="Reproducir")

`variant`: "light" (trazo claro, para fondos oscuros) o "dark" (trazo casi
negro, para botones de acento verde).
"""

from __future__ import annotations

import os
from typing import Dict, Tuple

import customtkinter as ctk
from PIL import Image

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
_cache: Dict[Tuple[str, int, str], ctk.CTkImage] = {}


def icon(name: str, size: int = 18, variant: str = "light") -> ctk.CTkImage:
    """Devuelve el icono Lucide `name` como CTkImage cuadrado de `size` px."""
    key = (name, size, variant)
    if key not in _cache:
        path = os.path.join(_DIR, f"{name}_{variant}.png")
        img = Image.open(path)
        _cache[key] = ctk.CTkImage(light_image=img, dark_image=img,
                                   size=(size, size))
    return _cache[key]


def has(name: str, variant: str = "light") -> bool:
    return os.path.isfile(os.path.join(_DIR, f"{name}_{variant}.png"))
