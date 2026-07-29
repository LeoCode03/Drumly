"""
theme.py — Tokens de diseño de Drumly ("El Estudio Profesional", ver DESIGN.md).

Roles, no bolsa de colores: superficies por luminancia (sin sombras), UN acento
de acción (verde), semántica de error, y tinta de partitura. Contrastes
verificados WCAG: texto primario >=12:1, secundario >=7:1, terciario >=4.5:1,
gráficos de partitura >=3:1, texto sobre acento >=8:1.

Tipografía: una sola familia (default CTk/Segoe UI) con escala por rol,
dimensionada para leerse a 1-2 m (piso 14px; valores clave grandes).
"""

from __future__ import annotations

import customtkinter as ctk

# ---------------------------------------------------------------- superficies
SURFACE0 = "#101010"   # lienzo de partitura (lo mas profundo)
SURFACE1 = "#171717"   # fondo de ventana
SURFACE2 = "#1f1f1f"   # paneles / secciones / historial
SURFACE3 = "#292929"   # controles en reposo (botones neutros, filas)
SURFACE4 = "#363636"   # hover de controles

# --------------------------------------------------------------------- texto
TEXT = "#f2f2f2"         # primario (15.5:1 sobre SURFACE1)
TEXT_MUTED = "#b8b8b8"   # secundario (8.4:1 sobre SURFACE1)
TEXT_FAINT = "#909090"   # terciario, solo >=15px (5.2:1 sobre SURFACE1)

# -------------------------------------------------------------------- acento
ACCENT = "#1db954"          # verde de accion: SOLO acciones primarias
ACCENT_HOVER = "#23d160"    # hover: mas brillante (estamos en oscuro)
ON_ACCENT = "#0c1410"       # texto/icono sobre verde (8.6:1)
ACCENT_TINT = "#16241e"     # superficie tenida de verde (tiles)

# ----------------------------------------------------------------- semantica
DANGER = "#f2665c"          # errores (5.1:1 sobre SURFACE1)
DANGER_HOVER_BG = "#5a2a2a"
SUCCESS = ACCENT            # exito comparte el verde

# ---------------------------------------------------------------- partitura
STAFF = "#8f8f8f"       # lineas del pentagrama (5.6:1 sobre SURFACE0)
BARLINE = "#7d7d7d"     # barras de compas (4.3:1; mas tenues que STAFF por rol)
NOTE = "#efefef"        # cabezas de nota (16.9:1)
NOTE_HL = ACCENT        # nota sonando
CURSOR = ACCENT

# ------------------------------------------------------------------ espaciado
SP_XS, SP_SM, SP_MD, SP_LG = 4, 8, 16, 24

# ------------------------------------------------------------------- radios
RAD_CONTROL = 8
RAD_PANEL = 12
RAD_PILL = 22

# ---------------------------------------------------------------- tipografia
_FONTS: dict = {}


def font(size: int, bold: bool = False) -> ctk.CTkFont:
    """CTkFont cacheada (una sola familia, la default del sistema)."""
    key = (size, bold)
    if key not in _FONTS:
        _FONTS[key] = ctk.CTkFont(size=size, weight="bold" if bold else "normal")
    return _FONTS[key]


def f_display() -> ctk.CTkFont:  # titulo de la app
    return font(30, bold=True)


def f_title() -> ctk.CTkFont:    # titulo de vista / cancion
    return font(20, bold=True)


def f_section() -> ctk.CTkFont:  # titulo de panel (VELOCIDAD, METRONOMO)
    return font(15, bold=True)


def f_value() -> ctk.CTkFont:    # numeros clave (BPM, tiempo actual)
    return font(22, bold=True)


def f_body() -> ctk.CTkFont:     # etiquetas de controles
    return font(15)


def f_small() -> ctk.CTkFont:    # metadatos (piso 14px)
    return font(14)
