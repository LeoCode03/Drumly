# Product

## Register

product

## Platform

desktop

(App de escritorio Windows en Python/CustomTkinter — no aplican HIG ni Material;
los criterios web se adaptan: tokens en Python, "responsive" = redimensionar
ventana, a11y = teclado + contraste.)

## Users

Leo, baterista aficionado hispanohablante, y bateristas como él: quieren tocar
canciones reales (folclore, rock) sin partitura publicada. Contexto físico:
sentados en la batería frente a una PC con Windows, a veces a 1–2 metros del
monitor, en salas de ensayo con poca luz, con las manos ocupadas por baquetas.
El trabajo a realizar: convertir una canción (MP3/WAV) en partitura de batería y
practicarla siguiéndola en pantalla al ritmo real.

## Product Purpose

Drumly separa la batería de una canción (Demucs), la transcribe a MIDI (ADTOF),
genera una partitura PDF (LilyPond) y ofrece una vista de práctica en tiempo
real: cursor sincronizado, metrónomo que sigue los beats reales o un BPM manual,
tempo ajustable sin cambiar el tono, y anclaje manual del compás. Éxito = el
usuario puede leer y tocar la canción completa sin desfases entre lo que ve, lo
que oye y lo que toca.

## Positioning

La única app local que convierte cualquier canción en una partitura de batería
practicable — separación, transcripción y práctica en vivo — sin subir nada a la
nube.

## Brand Personality

Estudio de música profesional: preciso, oscuro, musical. La estética de un DAW
(Ableton, Spotify artista): fondos casi negros, un verde como color de acción,
tipografía precisa, densidad media. Serio pero musical; herramienta de músico,
no juguete.

## Anti-references

- Apps gamificadas infantiles (Duolingo): nada de mascotas, confeti ni colores
  caramelo.
- SaaS genérico claro: nada de cards blancas sobre gris claro ni landing-style.
- Cabina de avión: no acumular controles sin jerarquía; cada control visible
  debe ganarse su lugar.

## Design Principles

1. **La partitura es la protagonista.** Todo lo demás (transporte, ajustes)
   sirve para leerla; la jerarquía visual siempre es partitura > transporte >
   ajustes.
2. **Legible desde la batería.** Alto contraste y tamaños generosos: el usuario
   puede estar a 1–2 m del monitor.
3. **Operable sin mouse.** El flujo de práctica completo funciona con teclado
   (las manos llevan baquetas): espacio, flechas, atajos.
4. **La verdad es el audio.** Cursor, barras y click deben estar clavados a lo
   que suena; nunca "aproximados". Si hay conflicto, gana la sincronía.
5. **Dos relojes, nunca confundidos.** La velocidad de la canción y el pulso del
   metrónomo son controles distintos, siempre separados y etiquetados.

## Accessibility & Inclusion

- Contraste alto: texto ≥4.5:1 sobre su fondo; notas/líneas del pentagrama ≥3:1.
- Todo operable por teclado (práctica completa sin mouse).
- Tipografía base mayor que el default de Tkinter (legible a distancia).
