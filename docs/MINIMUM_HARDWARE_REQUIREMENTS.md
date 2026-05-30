# Echo AI — Minimum Hardware Requirements

This document specifies the minimum and recommended hardware for each deployment target.

---

## 1. Development / Demo (Current — Windows Laptop)

| Component | Minimum | Recommended |
|---|---|---|
| CPU | Intel Core i5 (8th gen) / AMD Ryzen 5 | Core i7 / Ryzen 7 |
| RAM | 8 GB | 16 GB |
| Storage | 10 GB free | 20 GB free (models are large) |
| OS | Windows 10 64-bit | Windows 11 |
| Microphone | Built-in laptop mic | USB cardioid mic / headset |
| Speaker | Built-in | External speaker |
| Internet | Required for weather, maps, Spotify, YouTube | — |
| GPU | Not required | Dedicated GPU accelerates Whisper/Ollama |

**Software stack tested on:**
- Python 3.11 / 3.12
- Ollama 0.3+
- whisper.cpp (pre-compiled .exe)
- Piper TTS (pre-compiled .exe)

---

## 2. Raspberry Pi (Embedded In-Car)

### Absolute Minimum (Pi 4B 4 GB)
| Component | Spec | Notes |
|---|---|---|
| Board | Raspberry Pi 4B 4 GB | 2 GB will struggle with 3B LLM |
| Storage | 32 GB microSD, Class 10 / A1 | A2 rated preferred for speed |
| Microphone | USB microphone (e.g. Blue Snowball iCE) | Single mic, basic accuracy |
| Speaker | 3.5 mm analog speaker | Built-in amp required |
| Display | Any HDMI display 1024×600+ | Or official 7" Pi touchscreen |
| Power | Official 5V 3A USB-C Pi power supply | Must handle current spikes |
| Cooling | Heatsink (passive) | Mandatory — Pi 4 throttles at 80°C |
| Internet | Wi-Fi (built-in) | Required for weather/maps/streaming |

**Model constraints at 4 GB RAM:**
- Whisper: tiny.en (fastest) or small.en (better accuracy)
- LLM: qwen2.5:0.5b for conversation, qwen2.5:1.5b for tools (both fit in RAM)
- Piper TTS: runs fine (CPU inference, ~100 ms/sentence)

### Recommended (Pi 5 8 GB)
| Component | Spec | Notes |
|---|---|---|
| Board | Raspberry Pi 5 8 GB | 2× faster than Pi 4, better thermals |
| Storage | 64 GB A2 microSD or USB3 SSD | SSD = much faster model loading |
| Microphone | **ReSpeaker 4-Mic Array HAT** | Beamforming + echo cancel = essential in car |
| Speaker | USB DAC + car speaker | Better audio quality |
| Display | 10.1" IPS touchscreen (1280×800 HDMI) | Capacitive touch |
| Power | UPS HAT (Waveshare UPS HAT C) | Safe shutdown on ignition-off |
| Cooling | Active cooler (official Pi 5 fan) | Mandatory for sustained LLM load |
| Internet | 4G/LTE HAT + SIM OR car Wi-Fi router | Standalone connectivity |

**Model capability at 8 GB RAM (Pi 5):**
- Whisper: small.en (good accuracy)
- LLM: llama3.2:3b for both conversation and tools
- Expected response time: 2–5 seconds

### Why a ReSpeaker Mic Array is Essential in a Car
A standard single USB mic in a moving car faces:
- Road noise (50–80 dB broadband noise)
- HVAC fan noise
- Music playing from speakers
- Echo from the assistant's own voice

A 4-mic array with beamforming points at the driver, suppresses side/rear noise, and applies acoustic echo cancellation. Without it, Whisper STT accuracy in a car cabin can drop from 90%+ to under 50%.

---

## 3. Android Car Head Unit / Tablet

### Minimum Android Specs
| Component | Minimum | Recommended |
|---|---|---|
| Android version | Android 8.0 (API 26) | Android 11+ (API 30+) |
| CPU | Quad-core ARM Cortex-A53 | Octa-core Cortex-A55 or higher |
| RAM | 3 GB | 4 GB+ |
| Storage | 16 GB internal | 32 GB+ (models take 2–5 GB) |
| Display | 7" 1024×600 (common head unit size) | 9–10.1" 1280×800 IPS |
| Touch | Capacitive single-touch | 5-point multi-touch |
| Microphone | Built-in (low quality) | External USB or 3.5mm mic |
| Bluetooth | BT 4.0 | BT 5.0 (for HFP calls) |
| Wi-Fi | 2.4 GHz 802.11n | Dual-band 802.11ac |
| GPS | Required for navigation | — |

### Notes on Aftermarket Android Head Units
Most aftermarket Android head units run Android 8–12 on Allwinner A133, Rockchip RK3399, or Qualcomm Snapdragon 665 SoCs. They range from $60 (poor performance) to $250+ (smooth experience).

**Recommended head unit tier for Echo AI:**
- CPU: Octa-core 1.8 GHz+
- RAM: 4 GB (to run backend + Chromium)
- Storage: 32 GB
- Android: 10 or 11
- Supports sideloading APKs (standard AOSP, no Google Play approval needed)

For Path B (on-device): the head unit's NPU (if present, e.g. RK3588) can accelerate ONNX model inference.

### Path A — Backend on Separate Device (Pi/Laptop)
The Android app is only a **WebView client**. The heavy AI computation (Whisper, LLM, Piper) runs on a Pi or laptop connected to the same car Wi-Fi. In this case:

- Android minimum drops to: **2 GB RAM, Android 8, any SoC** — just a browser.
- The Pi or laptop handles all compute.

---

## 4. Microphone Selection Guide

| Mic Type | In-Car Accuracy | Cost | Notes |
|---|---|---|---|
| Built-in laptop mic | Poor | Free | Good for dev only |
| Single USB cardioid | Fair | $15–40 | OK for quiet indoor testing |
| ReSpeaker 2-Mic HAT | Good | $20 | Pi HAT — beamforming, limited noise rejection |
| ReSpeaker 4-Mic Array | Very good | $35 | **Recommended for Pi in-car** |
| ReSpeaker 6-Mic Array | Excellent | $55 | Best for large cabins/SUVs |
| MATRIX Voice | Excellent | $65 | 8-mic array, integrated |

---

## 5. Network Requirements

| Feature | Required | Notes |
|---|---|---|
| Wake word, STT, LLM, TTS | ❌ Offline | All local — no internet needed |
| Weather | ✅ Internet | Open-Meteo API, no key |
| Maps / Navigation | ✅ Internet | Google Maps in browser |
| YouTube | ✅ Internet | Opens YouTube search |
| Spotify | ✅ Internet | Opens Spotify search |
| WhatsApp (prefill) | ✅ Internet | Opens wa.me link |
| Web search | ✅ Internet | Google search in browser |

**For fully standalone operation (no phone hotspot):**
- Use a 4G/LTE HAT on Pi with a data SIM, or
- Use a Mi-Fi router in the car powered from USB

---

## 6. Power Budget (In-Car)

| Component | Idle | Peak |
|---|---|---|
| Raspberry Pi 5 8 GB | 3 W | 12 W |
| 10" display (HDMI) | 5 W | 8 W |
| ReSpeaker 4-Mic HAT | 0.5 W | 0.5 W |
| USB speaker/amp | 1 W | 10 W |
| 4G LTE HAT | 1 W | 3 W |
| **Total** | **~11 W** | **~34 W** |

A standard car USB-A port provides 5 W — insufficient. Use:
- A dedicated 12V → 5V/5A DC-DC converter (from car fuse box)
- Or a powered USB hub with 12V input

For the Android head unit: it ships with its own 12V power harness — no extra calculation needed.

---

## 7. Storage Breakdown

| Item | Size |
|---|---|
| Raspberry Pi OS 64-bit | ~4 GB |
| Python venv + dependencies | ~800 MB |
| whisper.cpp (binary + small.en model) | ~600 MB |
| Piper (binary + 2 voices) | ~300 MB |
| Ollama + qwen2.5:0.5b | ~400 MB |
| Ollama + llama3.2:3b | ~2.1 GB |
| OpenWakeWord models | ~40 MB |
| Avatar frame PNGs (4 states) | ~180 MB |
| BOOT.mp4 + project code | ~60 MB |
| **Total (with 3B model)** | **~8.5 GB** |

Minimum SD card: **16 GB** (tight)  
Recommended: **32 GB** (comfortable with room for logs and updates)
