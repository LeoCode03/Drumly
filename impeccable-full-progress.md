# impeccable-full — progreso

Target: `ui/` (app CustomTkinter de escritorio).
Snapshot critique: `.impeccable/critique/2026-07-29T01-24-07Z__ui.md` (20/40; audit 8/20).
Gate: usuario pidio explicitamente reestructurar y aplicar -> sin pausa.

## Fase 0 — Contexto  [COMPLETA]
- [x] PRODUCT.md (registro product, plataforma desktop, 5 principios)
- [x] DESIGN.md (captura del estado ANTES; north star "El Estudio Profesional")
- [x] Iconos Lucide: 40 PNGs RGBA en ui/icons/ (20 nombres x light/dark, 64px) + ui/icons.py (loader CTkImage con cache)
  Nombres: play pause skip-back rewind fast-forward rotate-ccw map-pin file-text folder-open refresh-cw target music drum timer trash-2 download gauge audio-lines file-music clock

## Fase 1 — Analisis  [COMPLETA]
- [x] critique (A+B en workflow dual-agent) 20/40; audit (C) 8/20
- Hallazgos clave verificados:
  - Solape caja/tom: separacion 0.5*gap (17px) vs diametro nota 0.83*gap (28px) -> ilegible SIEMPRE (score_view lane_y)
  - _PX_PER_SEC=120 fijo: semicorcheas a 15px con cabezas de 28px; sin zoom
  - Cero teclado en toda la app (unico bind: entry BPM Return/FocusOut)
  - Blanco sobre verde #1db954 = 2.59:1 FALLA (fix: texto #0f0f0f sobre verde = 8:1, patron Spotify)
  - Barras compas #5a5a5a/#0f0f0f = 2.78:1 FALLA 3:1 (fix: ~#7a7a7a)
  - gray60/70 SI pasan (5.4-7.4:1); #ef5350 marginal 4.45:1
  - Metronomo repartido en 3 zonas; dos "BPM" sin distincion (slider Tempo vs entry Pulso)
  - Jerarquia invertida: Export verde primario, Practicar azul secundario
  - 63 literales color / 14 grises / CYAN muerto / #1db954 crudo en app.py:531,549
  - Emojis ~35 puntos; ES/EN mezclado (Export, Reset tempo)
  - Borrar historial sin confirmar; BPM entry clampa en silencio; sin cancel pipeline
  - VOL_MIN=1: no se puede mutear (mutear bateria = modo de practica central)
  - Solo atras-5s (falta adelante-5s); ExportDialog sin Esc (trampa de teclado)
  - after() desde hilos worker (practice.py:342,345,457; app.py:379) vs cola en app.py
  - Configure redibuja todo sin debounce; resaltado O(N) cada 33ms incluso en pausa
  - Header practica ~850px de contenido con minsize 820 -> desborda
  - Duplicados: _fmt_time, VolumeRow-builders, ACCENT, VOL_*, patron _user_seeking
  - Compases solo N/4 (6/8 irrepresentable; folclore = repertorio del usuario)
  - Errores de practica en gris status sin severidad
  - Positivos a conservar: ScoreCanvas tiempo->X unico + iman + centro; stretch con debounce/captura unica/pending; players con locks; pipeline sin UI

## RESULTADO FINAL (2026-07-29)
Critique 20/40 -> 31/40 (Bueno). Audit 8/20 -> 16/20 (Bueno).
Snapshots: .impeccable/critique/2026-07-29T01-24-07Z__ui.md (antes) y
2026-07-29T01-51-23Z__ui.md (despues). Commits: colorize+typeset 962875d,
layout ab45b16, clarify 2e6e6a0, harden 880a7b5, adapt 877d743, optimize
cf3f658, polish (iconos). Todos los pedidos F1-F8 del usuario: HECHOS.
Omitidos con motivo: bolder/quieter (registro DAW correcto), onboard (fuera de
alcance), optimize-web y sidecar live (N/A escritorio), widgets.py (solo 2 usos:
abstraccion prematura). Pendientes ofrecidos: cancel de pipeline, foco visible,
tooltips, loop A-B, count-in, presets, persistencia por cancion.

## Fase 2 — Aplicacion (commits por capa: `style(ui): <comando> via impeccable-full`)
- [ ] 6. colorize+typeset: ui/theme.py (tokens color+tipo+espaciado desde DESIGN.md);
      texto oscuro #0f1211 sobre verde en CTAs; barras compas #7a7a7a; UN acento
      (Practicar=verde primario, Export=gris secundario, adios azul acero);
      escala tipo: base 14-15, numeros clave grandes, status >=14; borrar CYAN
- [ ] 8. layout (F1,F2,F7-agrupacion):
      score_view: gap cap h/7 (max ~44), carriles en POSICIONES REALES de notacion
      (bombo 1er espacio, caja 3er espacio, tom 4to espacio, hihat/platillo con aspa
      encima del pentagrama), tom con cabeza hueca, leyenda de carriles (labels
      place() sobre el lienzo a la izquierda), PX_PER_SEC variable + zoom 60-360
      (Ctrl+rueda, +/-, botones); practice regroup: header=titulo+seccion Compas
      (selector+Marcar+Aplicar compactos); fila mezcla=Bateria+Banda; fila seek=
      restart|back5|fwd5(NUEVO)+slider+tiempos; abajo 3 paneles titulados:
      VELOCIDAD DE LA CANCION (slider %+BPM+entry+reset) | transporte play | METRONOMO
      (switch on/off, volumen, Pulso Cancion/Manual+BPM, Subdivision Negras/Corcheas,
      Acento) — todo el metronomo en UN panel
- [ ] 9. clarify: "Exportar", "Restablecer tempo", "Banda" (antes Otros), "Velocidad
      de la cancion 85% (~102 BPM)", feedback al clampar BPM entry, errores humanos
- [ ] (harden funcional, mismo commit o siguiente): teclado (espacio=play, izq/der=+-5s,
      Home=inicio, Up/Down=tempo+-5, M=metronomo, Esc=cerrar dialogo; guarda de foco
      en entries); compases (meter_num/meter_den en PipelineResult, beats_per_bar=
      num*4/den derivado, lista 2/4 3/4 4/4 5/4 6/4 6/8; \time num/den en LilyPond);
      subdivision del click (negras/corcheas; en Cancion interpolar punto medio entre
      beats); VOL_MIN=0; confirmar borrado 2 pasos; _set_status(level) rojo; despachador
      thread-safe unico; List import player.py; comentario 40-220
- [ ] 10. adapt: wraplength dinamico (error_label, song_title, Export msg), Esc y
      minsize en ExportDialog, labels que truncan antes que botones
- [ ] 12. optimize: debounce Configure (80ms), resaltado con bisect + early-return
      en pausa, sin y.copy() a rate 1.0
- [ ] Fase2 commit por capa + push al final

## Fase 3 — Consolidacion y cierre
- [ ] 13. extract: ui/widgets.py (fmt_time, VolumeRow, SeekRow, StatusLabel,
      despachador) + refrescar DESIGN.md al estado NUEVO
- [ ] 15. polish: barrido de iconos Lucide en TODOS los botones/labels (adios emojis,
      tambien ✅❌ de status), foco visible, detalles
- [ ] 16. audit final: re-medir contraste y heuristicas clave, comparar 20/40 y 8/20
      iniciales, reporte antes/despues al usuario
- Omitidos con motivo: colorize-independiente (fusionado con typeset en theme.py),
  bolder/quieter (registro DAW correcto, no plano ni recargado), onboard (fuera de
  alcance pedido), animate/delight/overdrive (ofrecer al final), optimize-web (N/A)
- Proximos pasos a OFRECER (no implementar): loop A-B, count-in, persistir ajustes
  por cancion, fusionar mezclador+practica, converger vista practica a notacion real,
  cancelar pipeline en curso, adelante-5s hecho? (SI, va en layout), mute por boton

## Pedidos funcionales del usuario (mapa)
F1 lineas pentagrama -> layout | F2 separacion horizontal/zoom -> layout
F3 espacio -> harden-teclado | F4 flechas 5s -> harden-teclado
F5 compases amplios -> harden-meters | F6 click corcheas -> harden-subdivision
F7 dos BPM separados -> layout+clarify | F8 iconos Lucide -> polish (assets listos)
