---
name: Drumly
description: Transcriptor y practicador de bateria de escritorio (CustomTkinter)
colors:
  accent-green: "#1db954"
  accent-green-hover: "#23d160"
  on-accent: "#0c1410"
  accent-tint: "#16241e"
  surface-0: "#101010"
  surface-1: "#171717"
  surface-2: "#1f1f1f"
  surface-3: "#292929"
  surface-4: "#363636"
  text: "#f2f2f2"
  text-muted: "#b8b8b8"
  text-faint: "#909090"
  danger: "#f2665c"
  danger-hover-bg: "#5a2a2a"
  staff-line: "#8f8f8f"
  bar-line: "#7d7d7d"
  note-ink: "#efefef"
typography:
  display:
    fontFamily: "Segoe UI (CTkFont default)"
    fontSize: "30px"
    fontWeight: 700
  title:
    fontFamily: "Segoe UI (CTkFont default)"
    fontSize: "20px"
    fontWeight: 700
  value:
    fontFamily: "Segoe UI (CTkFont default)"
    fontSize: "22px"
    fontWeight: 700
  section:
    fontFamily: "Segoe UI (CTkFont default)"
    fontSize: "15px"
    fontWeight: 700
  body:
    fontFamily: "Segoe UI (CTkFont default)"
    fontSize: "15px"
    fontWeight: 400
  small:
    fontFamily: "Segoe UI (CTkFont default)"
    fontSize: "14px"
    fontWeight: 400
rounded:
  control: "8px"
  panel: "12px"
  pill: "22px"
  circle: "50% (play 42px radius)"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
components:
  button-primary:
    backgroundColor: "{colors.accent-green}"
    textColor: "{colors.on-accent}"
    rounded: "{rounded.pill}"
  button-secondary:
    backgroundColor: "{colors.surface-3}"
    textColor: "{colors.text}"
    rounded: "{rounded.pill}"
  panel:
    backgroundColor: "{colors.surface-2}"
    rounded: "{rounded.panel}"
---

# Design System: Drumly

## Overview

**Creative North Star: "El Estudio Profesional"**

Drumly se ve como la cabina de un estudio/DAW: superficies casi negras separadas
solo por luminancia, UN acento de accion verde, iconografia Lucide monocroma y
tipografia dimensionada para leerse a 1-2 metros (el baterista esta sentado en
su bateria, no pegado al monitor). La partitura en lienzo negro profundo es la
protagonista; los controles viven agrupados por significado en paneles
titulados. Todos los tokens viven en `ui/theme.py` (fuente de verdad unica).

**Key Characteristics:**
- Escalera de superficies SURFACE0-4 (lienzo < ventana < panel < control < hover).
- Un solo acento: el verde premia SIEMPRE la accion primaria (Practicar, Play,
  Generar); el resto de acciones son neutras.
- Texto oscuro ON_ACCENT sobre verde (8.6:1); nunca blanco sobre verde.
- Iconos Lucide PNG (ui/icons.py, variantes light/dark), cero emojis.
- Dos relojes separados: panel VELOCIDAD DE LA CANCION vs panel METRONOMO.
- Operable por teclado: espacio, flechas, Inicio, M, Ctrl+rueda.

## Colors

Contrastes verificados: texto primario 15.5:1, secundario 8.4:1, terciario
5.2:1 (solo >=15px), danger 5.1:1, on-accent 8.6:1, pentagrama 5.6:1, barras de
compas 4.3:1.

### Primary
- **Verde Accion** (#1db954): acciones primarias, cursor de partitura, nota
  sonando, switch/checkbox activos. Hover #23d160 (mas brillante: fondo oscuro).

### Neutral
- **SURFACE0-4** (#101010 → #363636): profundidad sin sombras.
- **Tinta** text/text-muted/text-faint (#f2f2f2/#b8b8b8/#909090).
- **Partitura**: lineas #8f8f8f, barras de compas #7d7d7d (mas tenues por rol,
  no por ilegibilidad), notas #efefef.
- **Danger** (#f2665c): errores; hover destructivo #5a2a2a.

### Named Rules
**La Regla del Verde Unico.** El verde va SOLO en la accion primaria de cada
vista y en la partitura viva (cursor/nota sonando). Si dos botones verdes
compiten en una vista, uno esta mal.
**La Regla del Texto Oscuro.** Sobre el verde de accion, el texto y los iconos
son ON_ACCENT (#0c1410), jamas blanco (2.6:1).

## Typography

**Fuente unica:** Segoe UI (CTkFont default), escala por rol en `theme.f_*()`.

### Hierarchy
- **Display** (700, 30px): titulo "Drumly".
- **Title** (700, 20px): titulos de vista/cancion.
- **Value** (700, 22px): numeros que se leen de reojo (tiempo actual, % + BPM).
- **Section** (700, 15px): titulos de panel (VELOCIDAD..., METRONOMO).
- **Body** (400, 15px): etiquetas de controles.
- **Small** (400, 14px): metadatos y status. **Piso 14px** en toda la app.

**La Regla del Vistazo.** Todo numero que el baterista lee mientras toca
(tiempo, BPM, %) usa Value (22px bold); nada critico va en Small.

## Layout

Ventana principal 480x760 de una columna. Practica 1150x760 en 6 filas grid con
la partitura en weight=1: titulo+Compas / PARTITURA / mezcla / navegacion /
paneles (Velocidad | Play | Metronomo) / status. Espaciado en pasos SP_XS-SP_LG
(4/8/16/24). Los textos largos recalculan wraplength al redimensionar.

## Elevation & Depth

Plano total: sin sombras. Profundidad = escalera de luminancia SURFACE0-4.

## Shapes

Controles 8px, paneles 12px, pastillas CTA 22px, Play circular (84px). Sin
bordes: las superficies se separan por color.

## Components

### Botones
- **Primario**: verde + ON_ACCENT + icono Lucide dark + pastilla.
- **Secundario/transporte**: SURFACE3, hover SURFACE4, icono Lucide light.
- **Destructivo en dos pasos**: transparente -> "Borrar?" rojo armado 3 s.

### Paneles
SURFACE2 redondeado 12px con titulo Section en TEXT_MUTED. Un panel = un
concepto (todo el metronomo vive en el suyo).

### Partitura (componente firma)
Lienzo SURFACE0: carriles en notacion real de bateria (aspas arriba, tom hueco
1er espacio, caja 2do espacio, bombo abajo) con separacion >=1 gap y gap que
escala con el alto (14-44px); leyenda fija de carriles; cursor verde clavado al
centro; barras de compas en beats reales; zoom 60-480 px/s; iman de nota al
clic; resaltado O(log n) y Configure con debounce.

### Iconografia
Lucide via `ui/icons.py` (`icon(nombre, px, variante)`): PNGs RGBA 64px en
ui/icons/, variantes light (#e8e8e8) y dark (#0d120f). Generados en dev con
scratchpad/gen_icons (svglib); regenerar solo si se agregan nombres.

## Do's and Don'ts

### Do:
- **Do** tomar TODO color/fuente/espaciado de `ui/theme.py`.
- **Do** icono + texto en botones anchos; icono solo en transporte compacto.
- **Do** mantener el flujo de practica operable 100% por teclado.
- **Do** errores en DANGER con f_body; el status normal en TEXT_MUTED f_small.

### Don't:
- **Don't** literales #hex ni grayNN en las vistas (solo theme.py).
- **Don't** emojis como iconografia ni en mensajes de estado.
- **Don't** texto blanco sobre el verde de accion.
- **Don't** un segundo acento de color para acciones (el azul acero murio aqui).
- **Don't** texto informativo bajo 14px o bajo 4.5:1.
