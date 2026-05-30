# Echo AI — Raspberry Pi Implementation Guide

**Target:** Self-contained in-car AI assistant running entirely on a Raspberry Pi.  
**Result:** A kiosk-mode touchscreen or HDMI display that boots straight into Echo AI, fully offline-capable (except Maps/Spotify/YouTube/Weather which require internet).

---

## 1. Recommended Hardware

| Component | Minimum | Recommended |
|---|---|---|
| Board | Raspberry Pi 4B 4 GB | Raspberry Pi 5 8 GB |
| Storage | 32 GB microSD (A2 rated) | 64 GB microSD or USB-SSD |
| Display | Any HDMI monitor / 7" official Pi display | 10.1" IPS 1280×800 touchscreen |
| Microphone | Single USB mic | **ReSpeaker 4-Mic Array HAT** (beamforming) |
| Speaker | 3.5 mm + USB amp | Waveshare Audio HAT or USB speaker |
| Power | 5V 3A USB-C | UPS HAT (e.g. Waveshare UPS HAT C) for safe shutdown |
| Case | Any | Vented case with fan (Pi 5 gets warm) |
| Internet | Wi-Fi built-in | 4G/LTE HAT + SIM (for standalone car use) |
| Cooling | Heatsink | Heatsink + 30 mm fan |

> **Why ReSpeaker?** Car cabins are noisy. A mic array with beamforming + echo cancellation dramatically improves STT accuracy over any single mic.

---

## 2. OS Setup

### 2.1 Flash the OS
```bash
# Use Raspberry Pi Imager
# Choose: Raspberry Pi OS (64-bit, Bookworm) — NOT Lite; we need a desktop for Chromium
# Enable SSH and set username/password in the Imager settings
```

### 2.2 First boot essentials
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl wget build-essential cmake python3-pip python3-venv \
                    portaudio19-dev libsndfile1-dev alsa-utils pulseaudio \
                    chromium-browser xdotool unclutter
```

### 2.3 Configure audio (for ReSpeaker HAT)
```bash
# Check current audio devices
aplay -l
arecord -l

# Set the ReSpeaker as default input in /etc/asound.conf
sudo nano /etc/asound.conf
```
Add:
```
pcm.!default {
    type asym
    playback.pcm "plughw:0,0"   # change index to match your speaker
    capture.pcm  "plughw:2,0"   # change index to match ReSpeaker
}
```
```bash
# Test recording
arecord -D plughw:2,0 -f S16_LE -r 16000 -c 1 test.wav
```

---

## 3. Project Setup

### 3.1 Clone / copy the project
```bash
cd ~
git clone https://github.com/yourusername/echo-ai.git   # or scp from laptop
cd echo-ai
```

### 3.2 Python virtual environment
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r backend/requirements.txt
```

> **Note:** `pycaw` and `comtypes` are Windows-only and will be skipped automatically on Linux — that is correct behaviour.

---

## 4. Install AI Components (ARM builds)

### 4.1 Whisper.cpp (STT)
```bash
cd ~
git clone https://github.com/ggerganov/whisper.cpp
cd whisper.cpp

# On Pi 4 (ARM64, NEON)
cmake -B build -DGGML_NEON=ON -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_EXAMPLES=ON
cmake --build build --config Release -j4

# On Pi 5 (ARM64, SVE/NEON)
cmake -B build -DGGML_NEON=ON -DGGML_SVE=ON -DWHISPER_BUILD_EXAMPLES=ON
cmake --build build -j4

# Copy binary
cp build/bin/whisper-cli ~/echo-ai/backend/bin/whisper/whisper-cli

# Download STT model (tiny = fastest, small = best accuracy)
bash ./models/download-ggml-model.sh tiny.en
bash ./models/download-ggml-model.sh small.en        # recommended for accuracy
cp models/ggml-small.en.bin ~/echo-ai/backend/models/

# Download VAD model
wget -O ~/echo-ai/backend/models/ggml-silero-v6.2.0.bin \
  "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-silero-v5.0.0.bin"
```

### 4.2 Piper TTS (ARM binary)
```bash
cd ~
# Get the latest ARM64 release from https://github.com/rhasspy/piper/releases
wget https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_aarch64.tar.gz
tar -xzf piper_linux_aarch64.tar.gz
cp -r piper ~/echo-ai/backend/bin/piper/

# Download voices into models/piper/
mkdir -p ~/echo-ai/backend/models/piper
cd ~/echo-ai/backend/models/piper

# Female voice (lessac)
BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"
wget $BASE/en_US-lessac-medium.onnx
wget $BASE/en_US-lessac-medium.onnx.json

# Male voice (ryan)
BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/medium"
wget $BASE/en_US-ryan-medium.onnx
wget $BASE/en_US-ryan-medium.onnx.json
```

### 4.3 Ollama (LLM)
```bash
# Ollama has an official ARM64 installer
curl -fsSL https://ollama.com/install.sh | sh

# Start Ollama service
sudo systemctl enable ollama
sudo systemctl start ollama

# Pull models — choose based on Pi RAM:
ollama pull qwen2.5:0.5b   # Pi 4 4GB: use this for conversation
ollama pull llama3.2:3b    # Pi 5 8GB: use this for tool-calling
# On Pi 4 4GB, use the same small model for both conversation and tools:
# Set OLLAMA_TOOL_MODEL=qwen2.5:1.5b in environment
```

### 4.4 OpenWakeWord
```bash
source ~/echo-ai/.venv/bin/activate
pip install openwakeword
# The hey_jarvis ONNX model is bundled with the package
# Test wake word detection
python3 -c "import openwakeword; print('OpenWakeWord OK')"
```

---

## 5. Environment Configuration

Create `/etc/echo-ai.env`:
```bash
sudo nano /etc/echo-ai.env
```
```env
# Profile (auto-detected on ARM, but explicit is safer)
ECHO_PROFILE=pi-fast

# STT — use small.en for better accuracy
ECHO_WHISPER_MODEL=/home/pi/echo-ai/backend/models/ggml-small.en.bin
ECHO_WHISPER_CPP_BIN=/home/pi/echo-ai/backend/bin/whisper/whisper-cli
ECHO_WHISPER_THREADS=4

# TTS
ECHO_PIPER_BIN=/home/pi/echo-ai/backend/bin/piper/piper
ECHO_PIPER_MODEL=/home/pi/echo-ai/backend/models/piper/en_US-lessac-medium.onnx
ECHO_PIPER_CONFIG=/home/pi/echo-ai/backend/models/piper/en_US-lessac-medium.onnx.json
ECHO_PIPER_MODEL_MALE=/home/pi/echo-ai/backend/models/piper/en_US-ryan-medium.onnx
ECHO_PIPER_CONFIG_MALE=/home/pi/echo-ai/backend/models/piper/en_US-ryan-medium.onnx.json

# LLM (on Pi 4 4GB, use same small model for tools too)
OLLAMA_MODEL=qwen2.5:0.5b
OLLAMA_TOOL_MODEL=qwen2.5:1.5b

# Car defaults
ECHO_DEFAULT_CITY=Pune
ECHO_CONTACTS=/home/pi/echo-ai/contacts.json
ECHO_CAR_INFO=/home/pi/echo-ai/car_info.md

# Wake word
ECHO_WAKE_PHRASE=Hey Jarvis

# VAD tuning for car cabin (slightly more aggressive)
ECHO_VAD_MIN_SILENCE_MS=480
ECHO_VAD_MAX_SECONDS=8
ECHO_ENDPOINT_RMS_THRESHOLD=0.018
```

---

## 6. Stage Avatar Frames

```bash
cd ~/echo-ai
source .venv/bin/activate
python3 scripts/prepare_avatar.py
```

---

## 7. Systemd Service (Auto-start on Boot)

### 7.1 Backend service
```bash
sudo nano /etc/systemd/system/echo-ai-backend.service
```
```ini
[Unit]
Description=Echo AI Backend
After=network.target ollama.service
Wants=ollama.service

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/echo-ai
EnvironmentFile=/etc/echo-ai.env
ExecStart=/home/pi/echo-ai/.venv/bin/python -m uvicorn backend.main:app \
          --host 127.0.0.1 --port 8123 --workers 1
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 7.2 Kiosk frontend service
```bash
sudo nano /etc/systemd/system/echo-ai-kiosk.service
```
```ini
[Unit]
Description=Echo AI Kiosk
After=graphical.target echo-ai-backend.service
Wants=echo-ai-backend.service

[Service]
Type=simple
User=pi
Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/pi/.Xauthority
ExecStartPre=/bin/sleep 4
ExecStart=/usr/bin/chromium-browser \
  --kiosk \
  --no-sandbox \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --disable-restore-session-state \
  --autoplay-policy=no-user-gesture-required \
  --check-for-update-interval=31536000 \
  --start-maximized \
  http://127.0.0.1:8123/
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical.target
```

### 7.3 Enable services
```bash
sudo systemctl daemon-reload
sudo systemctl enable ollama
sudo systemctl enable echo-ai-backend
sudo systemctl enable echo-ai-kiosk

# Disable mouse cursor in kiosk
sudo nano /etc/X11/xinit/xinitrc
# Add: unclutter -idle 0 &
```

---

## 8. Display Setup

### 8.1 Official Raspberry Pi 7" touchscreen
```bash
# Connect via DSI ribbon. No config needed — detected automatically.
# Rotate if needed (for landscape mount):
sudo nano /boot/config.txt
# Add: display_lcd_rotate=2  (180°) or 1 (90°)
```

### 8.2 HDMI car monitor
```bash
sudo nano /boot/config.txt
```
```
hdmi_force_hotplug=1
hdmi_group=2
hdmi_mode=87
hdmi_cvt=1024 600 60 6 0 0 0
```

### 8.3 Auto-login to desktop (for kiosk)
```bash
sudo raspi-config
# System Options → Boot / Auto Login → Desktop Autologin
```

---

## 9. Car Integration

### 9.1 Safe ignition-aware power (UPS HAT)
```bash
# Install UPS HAT monitoring script (varies by HAT model)
# On ignition-off: UPS powers Pi for ~30s, triggers graceful shutdown
sudo nano /etc/systemd/system/echo-ai-shutdown.service
```
```ini
[Unit]
Description=Echo AI Safe Shutdown
DefaultDependencies=no
Before=shutdown.target

[Service]
Type=oneshot
ExecStart=/bin/sync
TimeoutStartSec=10

[Install]
WantedBy=shutdown.target
```

### 9.2 Read-only root filesystem (prevents SD corruption on power loss)
```bash
# Use raspi-config → Performance → Overlay File System → Enable
# Then make /home/pi/echo-ai/contacts.json and car_info.md writable overlays
```

### 9.3 Bluetooth phone pairing (for calls via phone)
```bash
sudo apt install -y bluez pulseaudio-module-bluetooth
# Pair phone in Pi Bluetooth settings
# HFP profile enables call audio routing through Pi speaker/mic
bluetoothctl
> pair XX:XX:XX:XX:XX:XX
> connect XX:XX:XX:XX:XX:XX
> trust XX:XX:XX:XX:XX:XX
```

### 9.4 4G/LTE HAT (optional, for standalone internet)
```bash
# Install network-manager
sudo apt install -y network-manager
# Use nmtui to configure the LTE modem connection
nmtui
```

---

## 10. Performance Tuning

```bash
# Increase GPU memory split (helps Chromium rendering)
sudo nano /boot/config.txt
# Add: gpu_mem=128

# Disable unnecessary services
sudo systemctl disable bluetooth   # if not using BT calls
sudo systemctl disable avahi-daemon

# Set CPU governor to performance
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor

# Add to /etc/rc.local before exit 0:
echo performance > /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor

# Disable swap (Pi 5 only — Pi 4 may need swap for 3B model)
sudo dphys-swapfile swapoff
sudo dphys-swapfile uninstall
```

### Model selection by Pi model
| Pi Model | RAM | Conversation LLM | Tool LLM | Expected response |
|---|---|---|---|---|
| Pi 4B 4 GB | 4 GB | qwen2.5:0.5b | qwen2.5:1.5b | 3–6 s |
| Pi 4B 8 GB | 8 GB | qwen2.5:1.5b | llama3.2:3b | 4–8 s |
| Pi 5 8 GB | 8 GB | qwen2.5:3b | llama3.2:3b | 2–4 s |
| Pi 5 16 GB | 16 GB | llama3.2:3b | llama3.2:3b | 1–3 s |

---

## 11. Troubleshooting

| Problem | Fix |
|---|---|
| No audio input | `arecord -l` to list devices; check ALSA config index |
| Whisper not found | Check `ECHO_WHISPER_CPP_BIN` path; `ls -la` the binary |
| Ollama model OOM | Use smaller model; reduce `OLLAMA_NUM_CTX` to 512 |
| Kiosk black screen | Check `echo-ai-backend` started first; increase `ExecStartPre` sleep |
| Wake word not firing | Lower `ECHO_WAKE_THRESHOLD` to 0.35; check mic input level |
| STT always empty | Increase `ECHO_ENDPOINT_RMS_THRESHOLD`; check mic is capturing |
| Pi overheating | Add heatsink + fan; reduce `OLLAMA_NUM_THREAD` |
| SD card corruption | Enable overlay filesystem (step 9.2) |

---

## 12. Quick-Start Checklist

- [ ] Flash Pi OS 64-bit, enable SSH, set hostname `echo-pi`
- [ ] Install apt dependencies
- [ ] Compile whisper.cpp with NEON flags
- [ ] Install Piper ARM binary + female + male voices
- [ ] Install Ollama + pull models
- [ ] Run `prepare_avatar.py`
- [ ] Create `/etc/echo-ai.env`
- [ ] Enable all 3 systemd services
- [ ] Configure display rotation and auto-login
- [ ] Test: `curl http://127.0.0.1:8123/api/health`
- [ ] Pair phone via Bluetooth (for calls)
- [ ] Enable overlay FS for SD protection
- [ ] Mount in car and test wake word
