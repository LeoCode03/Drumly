# 🥁 Drumly

Aplicación de escritorio que toma una canción (**MP3** o **WAV**), aísla la pista de
batería y genera una **partitura PDF** lista para leer.

## ¿Cómo funciona?

```
tu_cancion.mp3
   │  1. Demucs separa la mezcla en stems
   ├─▶ tu_cancion_drums.wav         ← solo batería
   └─▶ tu_cancion_sin_bateria.wav   ← todo menos la batería
   │  2. ADTOF "escucha" la batería y detecta cada golpe
   ▼
tu_cancion_drums.mid        ← MIDI (las notas, no audio)
   │  3. pretty_midi + LilyPond dibujan las notas en pentagrama
   ▼
tu_cancion_partitura.pdf    ← partitura final
   +  BPM estimado con librosa
```

Cada canción genera su **propia carpeta** dentro de `output/`:

```
output/
└── Yo Soy de Bolivia/
    ├── Yo Soy de Bolivia_drums.wav
    ├── Yo Soy de Bolivia_sin_bateria.wav
    ├── Yo Soy de Bolivia_drums.mid
    └── Yo Soy de Bolivia_partitura.pdf
```

> **Nota sobre el MIDI:** un MP3/WAV es *sonido grabado*; un MIDI son *instrucciones*
> (qué golpe, cuándo y con qué fuerza), como una partitura digital. Para dibujar una
> partitura necesitamos las notas (MIDI), no la onda de audio. El MP3 se convierte a
> WAV automáticamente dentro del programa: no tienes que hacerlo a mano.

> **¿Por qué no Basic Pitch?** Basic Pitch (de Spotify) solo detecta melodía/tono y
> *no puede transcribir batería*. Por eso Drumly usa **ADTOF**, un modelo entrenado
> específicamente para reconocer golpes de batería.

---

## Requisitos

- **Python 3.11** (el stack de ML aún no es estable en 3.13).
- **LilyPond** (motor de grabado de partituras).
- **ffmpeg** (para que Demucs pueda leer MP3).

### 1. Crear el entorno e instalar dependencias Python

```bash
# Crear y activar un entorno virtual con Python 3.11
py -3.11 -m venv .venv          # Windows
# python3.11 -m venv .venv      # macOS / Linux

# Activar
.venv\Scripts\activate          # Windows (PowerShell/CMD)
# source .venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
```

### 2. Instalar ADTOF (transcripción de batería)

ADTOF-pytorch no está en PyPI; se instala desde su repositorio. Trae los pesos del
modelo incluidos y solo depende de torch/librosa/pretty_midi:

```bash
pip install git+https://github.com/xavriley/ADTOF-pytorch.git
```

### 3. Instalar LilyPond (¡imprescindible para el PDF!)

- **Windows:** descargar el instalador desde <https://lilypond.org/download.html> y
  añadir la carpeta `bin` de LilyPond al `PATH`.
- **macOS:** `brew install lilypond` (o el binario de <https://lilypond.org/macos-x.html>).
- **Linux (Debian/Ubuntu):** `sudo apt install lilypond`

Comprueba que funciona: `lilypond --version`.

### 4. Instalar ffmpeg

- **Windows:** <https://www.gyan.dev/ffmpeg/builds/> (añadir al `PATH`) o `winget install ffmpeg`.
- **macOS:** `brew install ffmpeg`.
- **Linux:** `sudo apt install ffmpeg`.

---

## Uso

```bash
python main.py
```

1. Pulsa **Seleccionar archivo** y elige un MP3 o WAV.
2. (Opcional) Marca **Mostrar silencios en la partitura** si quieres ver los
   silencios; por defecto está desactivado y solo se muestran las notas tocadas.
3. Verás el progreso: *Separando instrumentos… → Transcribiendo batería… → Generando partitura…*
4. Al terminar se abre la **pantalla de mezcla**:
   - Sliders de volumen para **Batería** y **Otros** (sin batería), en vivo.
   - **Play/Pausa**, barra de progreso con tiempo y **BPM** estimado.
   - Botón 📄 para abrir la **partitura PDF**.
   - **Export** → guardar la *mezcla de audio* (con tus volúmenes), abrir el *PDF*
     o abrir la *carpeta* de la canción.

Los archivos se guardan en `output/` con el nombre de la canción:
`cancion_drums.wav`, `cancion_drums.mid`, `cancion_partitura.pdf`.

---

## Estructura del proyecto

```
Drumly/
├── main.py                # Punto de entrada (lanza la UI)
├── ui/app.py              # Ventana CustomTkinter
├── pipeline/
│   ├── separator.py       # Demucs: audio -> _drums.wav
│   ├── transcriber.py     # ADTOF: _drums.wav -> _drums.mid
│   └── score.py           # music21 + LilyPond: _drums.mid -> _partitura.pdf
├── output/                # Archivos generados
├── requirements.txt
└── README.md
```

## Notas técnicas

- Demucs detecta automáticamente si hay GPU (CUDA); si no, usa la CPU.
- La separación es pesada y se ejecuta en un hilo aparte para no congelar la interfaz.
- La partitura usa clave de percusión, compás 4/4 y sin armadura.
- La transcripción automática no es perfecta: el MIDI/partitura puede necesitar
  ajustes manuales en un editor (MuseScore, etc.).
