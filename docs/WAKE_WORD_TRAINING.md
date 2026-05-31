# Training a Custom "Hey Echo" Wake Word

This guide explains how to train a branded **"Hey Echo"** wake word (replacing the bundled `hey_jarvis`) and wire it into Echo AI. It uses [openWakeWord](https://github.com/dscripka/openWakeWord)'s **synthetic-data training pipeline** — no manual voice recording required.

---

## 1. How the wake word works today

Echo AI detects the wake word with openWakeWord, in [`backend/pipeline/wake_word.py`](../backend/pipeline/wake_word.py):

- Loads the model via `Model()` (bundled `hey_jarvis`) **or** `Model(wakeword_models=[path])` when a custom file is configured.
- Audio is fed in **1280-sample frames at 16 kHz** (`wake_frame_samples=1280`, `sample_rate=16000`).
- `model.predict(frame)` returns a dict of `{label: score}`.
- It fires when the score for the active label ≥ `wake_threshold` (**currently `0.72`**).
- After a wake, an 8-second cooldown prevents immediate re-triggering (see `orchestrator.py`).

The relevant config keys in [`backend/config.py`](../backend/config.py):

| Setting | Config key | Env var | Current default |
|---|---|---|---|
| Wake phrase (display) | `wake_phrase` | `ECHO_WAKE_PHRASE` | `Hey Jarvis` |
| Model name | `wake_model_name` | `ECHO_WAKE_MODEL_NAME` | `hey_jarvis` |
| Custom model path | `wake_model_path` | `ECHO_WAKE_MODEL` | `None` |
| Detection threshold | `wake_threshold` | `ECHO_WAKE_THRESHOLD` | `0.72` |
| Frame size | `wake_frame_samples` | `ECHO_WAKE_FRAME_SAMPLES` | `1280` |
| Sample rate | `sample_rate` | `ECHO_SAMPLE_RATE` | `16000` |

`hey_jarvis` is a pre-trained model bundled inside the `openwakeword` package — no local file is needed for it. A custom model like **"Hey Echo"** must be trained and supplied as a local `.onnx` file.

---

## 2. The approach: synthetic training data

openWakeWord's killer feature is that you **don't record your own voice thousands of times**. Instead:

1. A text-to-speech engine (Piper) generates thousands of synthetic *"Hey Echo"* utterances across many voices, speeds, and pitches → **positive** samples.
2. Large public audio datasets (speech, music, noise) provide **negative** samples (everything that is *not* the wake word).
3. A small classifier is trained to fire only on the positive pattern, then exported to **ONNX**.

This produces a robust model in a few hours on a free GPU.

---

## 3. Step-by-step

### 3.1 Environment (Google Colab GPU recommended)

openWakeWord provides an official Colab notebook that does the whole pipeline:

> **openWakeWord automatic model training notebook:**
> https://github.com/dscripka/openWakeWord/blob/main/notebooks/automatic_model_training.ipynb

Open it in Colab, set the runtime to **GPU (T4)**.

If training locally instead:

```bash
python -m venv owwt && source owwt/bin/activate   # Windows: owwt\Scripts\activate
pip install openwakeword piper-tts torch torchaudio onnx
# plus the training extras the notebook installs (datasets, scipy, etc.)
```

### 3.2 Configure the target phrase

In the notebook's configuration cell, set:

```python
target_word   = "hey echo"
# phonetic / spelling variants improve robustness:
target_phrases = ["hey echo", "hey eko", "hey ekko", "hay echo"]
model_name    = "hey_echo"
```

> **Tip:** "Echo" can be heard as "eko"/"ekko" by TTS phonemizers. Including spelling variants makes the positive set sound more natural and varied.

### 3.3 Generate positive clips (synthetic TTS)

The notebook uses Piper to synthesize the phrase across many voices. Aim for **2,000–20,000** positive clips with augmentation:

- Multiple Piper voices (male/female, different accents — include Indian-English voices if your users are Indian).
- Random speed (0.8×–1.2×) and pitch shifts.
- Random padding/trim so the phrase isn't always centered.

### 3.4 Add negative + background audio

Negatives teach the model what to ignore. The notebook pulls from public datasets — include:

- General speech (so normal conversation doesn't trigger it).
- Music and podcasts.
- **Car-cabin noise** (road noise, HVAC, indicator clicks) — critical for in-car use. Record a few minutes of your own cabin noise and add it.

### 3.5 Train and export

Run the training cells. Output is **`hey_echo.onnx`** (and optionally a `.tflite`). Download it.

### 3.6 Validate

The notebook reports false-accept and false-reject rates. Goal:

- **Low false-reject** (it should wake when you say "Hey Echo").
- **Low false-accept** (it should NOT wake on TV, music, or chatter).

Pick a threshold where false-accepts are rare. Start around **0.5–0.6**, then tune (see §5).

---

## 4. Wire "Hey Echo" into Echo AI

1. Copy the trained model into the models folder:
   ```
   backend/models/hey_echo.onnx
   ```

2. Set environment variables before starting the server (or add to your `.env` / launch script):
   ```bash
   # Windows PowerShell
   $env:ECHO_WAKE_MODEL      = "backend/models/hey_echo.onnx"
   $env:ECHO_WAKE_MODEL_NAME = "hey_echo"
   $env:ECHO_WAKE_PHRASE     = "Hey Echo"
   $env:ECHO_WAKE_THRESHOLD  = "0.6"
   ```
   ```bash
   # Linux / Raspberry Pi
   export ECHO_WAKE_MODEL=backend/models/hey_echo.onnx
   export ECHO_WAKE_MODEL_NAME=hey_echo
   export ECHO_WAKE_PHRASE="Hey Echo"
   export ECHO_WAKE_THRESHOLD=0.6
   ```
   `wake_word.py` will then load via `Model(wakeword_models=["backend/models/hey_echo.onnx"])`.

3. Update the UI label so it reads "Say 'Hey Echo'":
   - In [`frontend/app.js`](../frontend/app.js), `STATUS_LABELS.sleeping` is `Say "Hey Jarvis"` → change to `Say "Hey Echo"`.
   - In [`frontend/index.html`](../frontend/index.html), the hidden `#wakePhrase` input and the Customize → Wake phrase display both say "Hey Jarvis" → update to "Hey Echo".

4. Restart the server and test by saying **"Hey Echo."**

---

## 5. Tuning tips

| Symptom | Fix |
|---|---|
| Doesn't wake reliably | Lower `ECHO_WAKE_THRESHOLD` (e.g. 0.6 → 0.5); add more/varied positive clips and retrain |
| Wakes on its own / random noise | Raise `ECHO_WAKE_THRESHOLD` (e.g. 0.6 → 0.72); add more negatives, especially cabin noise |
| Re-triggers on its own TTS | The 8-second wake cooldown + greeting mute window in `orchestrator.py` already guard this; raise threshold if still happening |
| Works at desk, fails in car | Add real cabin-noise negatives and retrain; consider a mic array (see [MINIMUM_HARDWARE_REQUIREMENTS.md](MINIMUM_HARDWARE_REQUIREMENTS.md)) |
| Different accents fail | Add positive clips from voices matching your users' accents |

> **Note on the threshold/cooldown interaction:** even a perfect model will occasionally score high on similar-sounding audio. The 8s cooldown means at worst one spurious wake, not a loop. Keep the threshold high enough that spurious wakes are rare.

---

## 6. Summary checklist

- [ ] Open openWakeWord automatic training notebook (Colab GPU)
- [ ] Set `target_word = "hey echo"` + variants, `model_name = "hey_echo"`
- [ ] Generate 2k–20k synthetic positives (multiple voices/accents)
- [ ] Add negatives incl. car-cabin noise
- [ ] Train → export `hey_echo.onnx`
- [ ] Validate FA/FR rates; pick threshold ~0.5–0.6
- [ ] Drop `hey_echo.onnx` into `backend/models/`
- [ ] Set `ECHO_WAKE_MODEL`, `ECHO_WAKE_MODEL_NAME`, `ECHO_WAKE_PHRASE`, `ECHO_WAKE_THRESHOLD`
- [ ] Update UI labels in `app.js` + `index.html`
- [ ] Restart and test "Hey Echo"
