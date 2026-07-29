---
name: Drumly
description: Transcriptor y practicador de bateria de escritorio (CustomTkinter)
colors:
  accent-green: "#1db954"
  accent-green-hover: "#17a347"
  steel-blue: "#243b52"
  steel-blue-hover: "#2d4a68"
  canvas-black: "#0f0f0f"
  panel-deep: "#141414"
  row-surface: "#1e1e1e"
  tile-green-tint: "#16241e"
  control-gray: "#2a2a2a"
  control-gray-hover: "#3a3a3a"
  divider-gray: "#4a4a4a"
  staff-line: "#8a8a8a"
  bar-line: "#5a5a5a"
  note-ink: "#e8e8e8"
  danger-red: "#ef5350"
  danger-hover: "#5a2a2a"
typography:
  display:
    fontFamily: "Segoe UI (CTkFont default)"
    fontSize: "30px"
    fontWeight: 700
  headline:
    fontFamily: "Segoe UI (CTkFont default)"
    fontSize: "16-18px"
    fontWeight: 700
  body:
    fontFamily: "Segoe UI (CTkFont default)"
    fontSize: "13-15px"
    fontWeight: 400
  label:
    fontFamily: "Segoe UI (CTkFont default)"
    fontSize: "12-13px"
    fontWeight: 400
rounded:
  control: "6px (CTk default)"
  tile: "12px"
  pill: "22px"
  circle: "50% (play 36px radius)"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
components:
  button-primary:
    backgroundColor: "{colors.accent-green}"
    textColor: "#ffffff"
    rounded: "{rounded.pill}"
  button-secondary:
    backgroundColor: "{colors.steel-blue}"
    textColor: "#ffffff"
    rounded: "{rounded.pill}"
  button-ghost:
    backgroundColor: "{colors.control-gray}"
    textColor: "#ffffff"
---

# Design System: Drumly

## Overview

**Creative North Star: "El Estudio Profesional"**

Drumly se ve como la cabina de un estudio/DAW: fondos casi negros, un unico
color de accion (verde Spotify-like) y controles de transporte reconocibles. La
partitura en lienzo negro profundo es la protagonista; los controles viven
debajo, agrupados. Densidad media: ni minimalismo vacio ni cabina de avion.

Estado ACTUAL capturado antes del rediseno integral (2026-07): sirve como
referencia "antes". Debilidades conocidas que el rediseno corrige: 7 grises
ad-hoc sin escala, dos acentos compitiendo (verde vs azul acero), textos gray60
de 12-13px que fallan contraste, emojis como iconografia, espaciado sin ritmo.

**Key Characteristics:**
- Fondo casi negro con un solo acento de accion verde.
- La partitura (lienzo) domina el espacio; controles agrupados abajo.
- Boton de play circular grande como centro del transporte.
- Espanol en toda la UI, tono directo de herramienta.

## Colors

Paleta oscura de estudio con un acento de accion y demasiados grises sueltos.

### Primary
- **Verde Accion** (#1db954): botones primarios (Generar, Export, Play de
  practica), cursor de partitura y nota resaltada. Hover #17a347.

### Secondary
- **Azul Acero** (#243b52): acciones secundarias de practica (Practicar,
  Aplicar a partitura). Hover #2d4a68. Compite con el verde sin regla clara.

### Neutral
- **Negro Lienzo** (#0f0f0f): fondo del pentagrama.
- **Panel Profundo** (#141414): panel de historial.
- **Fila** (#1e1e1e): filas de historial.
- **Gris Control** (#2a2a2a) / hover (#3a3a3a): botones neutros (transporte).
- **Linea de Pentagrama** (#8a8a8a) y **Barra de Compas** (#5a5a5a) sobre negro.
- **Tinta de Nota** (#e8e8e8): cabezas de nota.
- **Rojo Error** (#ef5350): mensajes de error; hover destructivo #5a2a2a.
- Textos secundarios en escala Tk "gray55"–"gray85" (sin tokens formales).

## Typography

**Fuente unica:** Segoe UI via CTkFont default (sin fuente propia).

**Character:** utilitaria y neutra; jerarquia solo por tamano (12→30) y bold.

### Hierarchy
- **Display** (700, 30px): titulo "Drumly" en la entrada.
- **Headline** (700, 16-18px): titulos de vista ("Practicar en tiempo real").
- **Title** (700, 15px): valores destacados (BPM).
- **Body** (400, 13-15px): etiquetas de controles.
- **Label** (400, 12-13px): subtextos gray60 (fallan contraste; a corregir).

## Layout

Ventana principal compacta (480x760) con una columna; practica grande (1100x700)
en grid de 6 filas donde la fila de partitura se estira (weight=1). Paddings
ad-hoc de 4-24px sin escala consistente. El lienzo de partitura usa relleno
lateral de media pantalla para poder centrar cualquier instante (cursor clavado
al medio). Controles de practica en 3 columnas simetricas (uniform).

## Elevation & Depth

Plano total: sin sombras. La profundidad se transmite solo por diferencia de
luminancia entre superficies (negro lienzo < panel < fila < control). Valido
para el registro DAW; mantener.

## Shapes

Esquinas redondeadas CTk por defecto (6px) en la mayoria; pastillas (22-24px) en
CTAs; circulo perfecto para Play (radio 36). Sin bordes: las superficies se
separan por color, no por trazo.

## Components

### Botones
- **Primario:** verde accion, pastilla, texto blanco bold.
- **Secundario:** azul acero, pastilla.
- **Neutro/transporte:** gris control #2a2a2a, hover #3a3a3a, con EMOJIS como
  icono (⏮ ⏪ ▶ 📍 📄 🔄) — a reemplazar por iconos Lucide.
- **Destructivo:** transparente con hover #5a2a2a (🗑 historial).

### Sliders
CTkSlider estandar (volumen 1-150, tempo 40-220, seek 0-1). Sin marcas ni
etiquetas de escala.

### Partitura (componente firma)
Lienzo negro #0f0f0f: 5 lineas #8a8a8a, notas #e8e8e8 (aspas ✕ para platillos,
circulos para tambores), cursor verde 3px clavado al centro, barras de compas
#5a5a5a, resaltado verde de la nota sonando, auto-scroll horizontal.

### Historial
Scrollable #141414 con filas #1e1e1e; boton principal transparente + 🗑.

## Do's and Don'ts

### Do:
- **Do** mantener fondo oscuro profundo y un solo acento de accion verde.
- **Do** mantener el Play circular grande como centro del transporte.
- **Do** separar superficies por luminancia (sin sombras ni bordes).

### Don't:
- **Don't** introducir tema claro ni cards blancas.
- **Don't** usar emojis como iconografia (migrar a Lucide).
- **Don't** dejar texto informativo bajo 4.5:1 de contraste.
