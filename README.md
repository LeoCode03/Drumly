# 🥁 Drumly

Desktop app that takes a song (**MP3** or **WAV**), isolates the drum track and
generates a ready-to-read **PDF drum score**.

## How does it work?

```
tu_cancion.mp3
   │  1. Demucs splits the mix into stems
   ├─▶ tu_cancion_drums.wav         ← drums only
   └─▶ tu_cancion_sin_bateria.wav   ← everything except the drums
   │  2. ADTOF "listens" to the drums and detects every hit
   ▼
tu_cancion_drums.mid        ← MIDI (the notes, not audio)
   │  3. pretty_midi + LilyPond draw the notes on a staff
   ▼
tu_cancion_partitura.pdf    ← final score
   +  BPM estimated with librosa
```

Each song gets its **own folder** inside `output/`:

```
output/
└── Yo Soy de Bolivia/
    ├── Yo Soy de Bolivia_drums.wav
    ├── Yo Soy de Bolivia_sin_bateria.wav
    ├── Yo Soy de Bolivia_drums.mid
    └── Yo Soy de Bolivia_partitura.pdf
```

> **A note on MIDI:** an MP3/WAV is *recorded sound*; a MIDI file is *instructions*
> (which hit, when, and how hard), like a digital score. To draw a score we need the
> notes (MIDI), not the audio waveform. The MP3 is converted to WAV automatically
> inside the program: you do not have to do it by hand.

> **Why not Basic Pitch?** Basic Pitch (by Spotify) only detects melody/pitch and
> *cannot transcribe drums*. That is why Drumly uses **ADTOF**, a model trained
> specifically to recognize drum hits.

---

## Requirements

- **Python 3.11** (the ML stack is not yet stable on 3.13).
- **LilyPond** (music engraving engine).
- **ffmpeg** (so Demucs can read MP3).

### 1. Create the environment and install Python dependencies

```bash
# Create and activate a virtual environment with Python 3.11
py -3.11 -m venv .venv          # Windows
# python3.11 -m venv .venv      # macOS / Linux

# Activate
.venv\Scripts\activate          # Windows (PowerShell/CMD)
# source .venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
```

### 2. Install ADTOF (drum transcription)

ADTOF-pytorch is not on PyPI; it is installed from its repository. It ships with the
model weights included and only depends on torch/librosa/pretty_midi:

```bash
pip install git+https://github.com/xavriley/ADTOF-pytorch.git
```

### 3. Install LilyPond (required for the PDF!)

- **Windows:** `winget install LilyPond.LilyPond` (recommended, stable version
  2.24), or download it from <https://lilypond.org/download.html>. If you have an
  installation that does not start, set the `DRUMLY_LILYPOND` variable to the path of
  a working `lilypond.exe`, or uninstall the broken one.
- **macOS:** `brew install lilypond` (or the binary from <https://lilypond.org/macos-x.html>).
- **Linux (Debian/Ubuntu):** `sudo apt install lilypond`

Check that it works: `lilypond --version`.

### 4. Install ffmpeg

- **Windows:** <https://www.gyan.dev/ffmpeg/builds/> (add to `PATH`) or `winget install ffmpeg`.
- **macOS:** `brew install ffmpeg`.
- **Linux:** `sudo apt install ffmpeg`.

---

## Usage

```bash
python main.py
```

1. Click **Select audio file** and choose an MP3 or WAV.
2. (Optional) Check **Show rests in the score** if you want to see the rests; it is
   off by default and only the notes that are played are shown.
3. You will see the progress: *Separating instruments… → Transcribing drums… → Generating score…*
4. When it finishes, the **mixer screen** opens:
   - Volume sliders for **Drums** and **Band** (everything but the drums), live.
   - **Play/Pause**, a progress bar with time, and the estimated **BPM**.
   - A 📄 button to open the **PDF score**.
   - **Export** → save the *audio mix* (with your volumes), open the *PDF*,
     or open the song's *folder*.
5. **🎯 Practice in real time** button → opens a large view with the score and a
   **cursor** that follows it while the drums play:
   - Detected **BPM** and **time signature** (2/4, 3/4, 4/4); both can be **changed**.
   - When you change the BPM, the drums are **stretched to the chosen tempo without
     changing the pitch** and the cursor stays in sync.
   - **Rewind/fast-forward** in real time: progress bar, **click on the score**, or
     the **⏮** (to the start) and **⏪ 5s** buttons.
   - Volume sliders for **Drums**, **Band** and **Metronome**, starting at the same
     values you left in the mixer (useful for following along with vocals/
     instruments).
   - Optional **Metronome** (with its own volume), with an
     **"Accent beat 1"** checkbox to mark the start of each bar more strongly.
   - The cursor compensates for the audio **output latency** so it stays aligned
     with what you hear, at any tempo.
   - **Real tempo (beat tracking)**: the score, the bar lines and the metronome
     follow the song's **actual beats** — if the band speeds up or slows down
     (live recordings), the notation does not drift.
   - **Manual anchoring**: pause where bar 1 really starts, click
     **📍 Mark bar 1** (it snaps to the nearest beat), choose the
     time signature (2/4, 3/4, 4/4) and click **📄 Apply to PDF** to regenerate
     the PDF with your anchor, without re-transcribing.
   - **Centered cursor**: the current position always stays pinned to the center
     of the screen (also when clicking any point of the score); the score scrolls
     underneath.
   - **Metronome pulse**: *Song* (follows the detected real beats) or
     *Manual* (type a BPM and the click plays at that fixed rhythm, 20–300).
   - The metronome and bars are **anchored to the first detected beat** of the
     song (not to second 0), so the click does not end up offset when there is an intro.
6. **🔄 Re-transcribe** button (on the mixer screen): re-runs the
   transcription (ADTOF + BPM/time signature/first beat + PDF) on the already
   separated stems, without repeating the Demucs separation. Useful if the
   transcription or the metronome ended up out of sync.
   (The downloadable PDF does not change; this is only for practice. The detected
   time signature is used to notate the PDF in 3/4, 4/4, etc.)

## Shortcut

`run_drumly.bat` is included (double-click to launch, with a console to see errors).
On Windows you can also create a desktop shortcut that points to
`.venv\Scripts\pythonw.exe` with the argument `main.py` and the project as the
working folder (this launches it without a console window).

Files are saved in `output/` named after the song:
`cancion_drums.wav`, `cancion_drums.mid`, `cancion_partitura.pdf`.

---

## Project structure

```
Drumly/
├── main.py                # Entry point (launches the UI)
├── ui/app.py              # CustomTkinter window
├── pipeline/
│   ├── separator.py       # Demucs: audio -> _drums.wav
│   ├── transcriber.py     # ADTOF: _drums.wav -> _drums.mid
│   └── score.py           # music21 + LilyPond: _drums.mid -> _partitura.pdf
├── output/                # Generated files
├── requirements.txt
└── README.md
```

## Technical notes

- Demucs automatically detects whether a GPU (CUDA) is available; otherwise it uses the CPU.
- Separation is heavy and runs on a separate thread so the interface does not freeze.
- The score uses a percussion clef, 4/4 time and no key signature.
- Automatic transcription is not perfect: the MIDI/score may need manual
  adjustments in an editor (MuseScore, etc.).
