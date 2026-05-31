import { EchoAvatar } from './avatar.js';

const TARGET_SAMPLE_RATE = 16000;
const FRAME_SAMPLES = 512;
const CAPTURE_BUFFER_SIZE = 1024;

const avatar = new EchoAvatar(document.querySelector('#avatarCanvas'));

const elements = {
  stage: document.querySelector(".stage"),
  messages: document.querySelector("#messages"),
  micButton: document.querySelector("#micButton"),
  micLevel: document.querySelector("#micLevel"),
  statusDot: document.querySelector("#statusDot"),
  statusText: document.querySelector("#statusText"),
  textForm: document.querySelector("#textForm"),
  textInput: document.querySelector("#textInput"),
  toast: document.querySelector("#toast"),
  backButton: document.querySelector("#backButton"),
  menuButton: document.querySelector("#menuButton"),
  closeMenu: document.querySelector("#closeMenu"),
  menuPanel: document.querySelector("#menuPanel"),
  menuScrim: document.querySelector("#menuScrim"),
  menuTabs: document.querySelectorAll("[data-menu-tab]"),
  menuSections: document.querySelectorAll("[data-menu-section]"),
  permToggles: document.querySelectorAll("[data-perm]"),
  voiceProfileButtons: document.querySelectorAll("[data-voice-profile]"),
  infoButtons: document.querySelectorAll("[data-info]"),
  languageSelect: document.querySelector("#languageSelect"),
  wakePhrase: document.querySelector("#wakePhrase"),
  connectionStatus: document.querySelector("#connectionStatus"),
  pipelineStatus: document.querySelector("#pipelineStatus"),
  statusPill: document.querySelector(".status-pill"),
};

const prefsKey = "echo-ai-prefs";

const STATUS_LABELS = {
  sleeping: 'Say "Hey Jarvis"',
  listening: "Listening…",
  processing: "Thinking…",
  speaking: "Speaking…",
  error: "Something went wrong",
};

const infoMessages = {
  privacy: "Privacy: speech is processed locally on this device.",
  copyright: "Echo AI — © 2026.",
  ownership: "Built and owned by Get My Solutions.",
};

let socket;
let micStream;
let captureContext;
let processor;
let pendingSamples = new Int16Array(0);
let micActive = false;
let assistantMessage;
let playbackContext;
let playbackGain;
let playbackQueue = Promise.resolve();
let nextPlayTime = 0;
let volume = 0.9;
let realtimeReady = false;

loadPrefs();
initChrome();
initBootSplash();
connect();

/* ── boot splash ──────────────────────────────────────────────────── */
function initBootSplash() {
  const splash = document.querySelector("#bootSplash");
  const video = document.querySelector("#bootVideo");
  if (!splash) return;
  const dismiss = () => {
    if (splash.classList.contains("hidden")) return;
    splash.classList.add("hidden");
    setTimeout(() => splash.remove(), 700);
  };
  if (video) {
    video.addEventListener("ended", dismiss);
    video.play?.().catch(() => {});
  }
  setTimeout(dismiss, 5000); // fallback if the video stalls or is missing
}

/* ── earcons (WebAudio, no assets) ────────────────────────────────── */
let earconCtx;
function playEarcon(type) {
  try {
    earconCtx = earconCtx || playbackContext || new AudioContext();
    const ctx = earconCtx;
    if (ctx.state === "suspended") ctx.resume();
    const notes = {
      wake: [[660, 0], [880, 0.09]],
      listen: [[784, 0]],
      done: [[880, 0], [660, 0.1]],
      error: [[300, 0], [220, 0.12]],
    }[type] || [[660, 0]];
    const now = ctx.currentTime;
    for (const [freq, at] of notes) {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      const t = now + at;
      gain.gain.setValueAtTime(0, t);
      gain.gain.linearRampToValueAtTime(0.12, t + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.18);
      osc.connect(gain).connect(ctx.destination);
      osc.start(t);
      osc.stop(t + 0.2);
    }
  } catch { /* earcons are non-essential */ }
}

/* ── chrome: back, menu, tabs, permissions, voice ─────────────────── */
function initChrome() {
  elements.micButton.addEventListener("click", async () => {
    if (micActive) stopMic();
    else await startMic();
  });

  elements.backButton.addEventListener("click", () => {
    if (!elements.menuPanel.hidden) { closeMenu(); return; }
    if (!elements.textForm.hidden) { elements.textForm.hidden = true; return; }
    sendJson({ type: "reset" });
  });

  elements.menuButton.addEventListener("click", openMenu);
  elements.closeMenu.addEventListener("click", closeMenu);
  elements.menuScrim.addEventListener("click", closeMenu);

  elements.menuTabs.forEach((tab) => {
    tab.addEventListener("click", () => activateMenuTab(tab.dataset.menuTab));
  });

  elements.permToggles.forEach((toggle) => {
    toggle.addEventListener("change", () => { savePrefs(); sendPermissions(); });
  });

  elements.voiceProfileButtons.forEach((button) => {
    button.addEventListener("click", () => {
      elements.voiceProfileButtons.forEach((b) => b.classList.toggle("active", b === button));
      savePrefs();
      sendJson({ type: "settings", voice_profile: button.dataset.voiceProfile });
      showToast(`Voice switched to ${button.dataset.voiceProfile}.`);
    });
  });

  elements.infoButtons.forEach((button) => {
    button.addEventListener("click", () => showToast(infoMessages[button.dataset.info] || "Info"));
  });

  // text bypass: tap the status pill (or press Enter) to type
  elements.statusPill.addEventListener("click", toggleTextBar);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && elements.textForm.hidden && document.activeElement !== elements.textInput) {
      toggleTextBar();
    } else if (event.key === "Escape") {
      elements.textForm.hidden = true;
      closeMenu();
    }
  });

  elements.textForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = elements.textInput.value.trim();
    if (!text) return;
    sendJson({ type: "text", text });
    appendMessage("user", text);
    elements.textInput.value = "";
    elements.textForm.hidden = true;
  });
}

function toggleTextBar() {
  const showing = !elements.textForm.hidden;
  elements.textForm.hidden = showing;
  if (!showing) elements.textInput.focus();
}

function openMenu() { elements.menuScrim.hidden = false; elements.menuPanel.hidden = false; }
function closeMenu() { elements.menuScrim.hidden = true; elements.menuPanel.hidden = true; }

function activateMenuTab(name) {
  elements.menuTabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.menuTab === name));
  elements.menuSections.forEach((s) => s.classList.toggle("active", s.dataset.menuSection === name));
}

/* ── preferences (permissions + voice) ────────────────────────────── */
function getPermissions() {
  const perms = {};
  elements.permToggles.forEach((t) => { perms[t.dataset.perm] = t.checked; });
  return perms;
}

function activeVoiceProfile() {
  return [...elements.voiceProfileButtons].find((b) => b.classList.contains("active"))?.dataset.voiceProfile || "female";
}

function savePrefs() {
  localStorage.setItem(prefsKey, JSON.stringify({ permissions: getPermissions(), voiceProfile: activeVoiceProfile() }));
}

function loadPrefs() {
  let stored = {};
  try { stored = JSON.parse(localStorage.getItem(prefsKey) || "{}"); } catch { stored = {}; }
  if (stored.permissions) {
    elements.permToggles.forEach((t) => {
      if (Object.hasOwn(stored.permissions, t.dataset.perm)) t.checked = Boolean(stored.permissions[t.dataset.perm]);
    });
  }
  const profile = stored.voiceProfile || "female";
  elements.voiceProfileButtons.forEach((b) => b.classList.toggle("active", b.dataset.voiceProfile === profile));
}

function sendPermissions() {
  sendJson({ type: "settings", permissions: getPermissions() });
}

/* ── websocket ────────────────────────────────────────────────────── */
function connect() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${protocol}://${location.host}/ws/audio`);
  socket.binaryType = "arraybuffer";

  socket.addEventListener("open", () => {
    elements.connectionStatus.textContent = "Online";
    elements.connectionStatus.classList.add("online");
  });

  socket.addEventListener("close", () => {
    realtimeReady = false;
    elements.connectionStatus.textContent = "Offline";
    elements.connectionStatus.classList.remove("online");
    window.setTimeout(connect, 1200);
  });

  socket.addEventListener("message", async (event) => {
    if (typeof event.data !== "string") return;
    await handleServerMessage(JSON.parse(event.data));
  });
}

async function handleServerMessage(message) {
  switch (message.type) {
    case "hello":
      elements.wakePhrase.value = message.wake_phrase || "Hey Jarvis";
      elements.pipelineStatus.textContent = `${message.stt_engine || "STT"} -> ${message.ollama_model || "LLM"} -> ${message.tts_engine || "TTS"}`;
      break;
    case "state":
      setState(message.state);
      break;
    case "wake":
      playEarcon("wake");
      break;
    case "speech":
      if (message.active) {
        elements.statusText.textContent = STATUS_LABELS.listening;
        playEarcon("listen");
      }
      break;
    case "assistant_start":
      assistantMessage = appendMessage("assistant", "");
      break;
    case "transcript_delta":
      if (!assistantMessage) assistantMessage = appendMessage("assistant", "");
      assistantMessage.querySelector(".content").textContent += message.text;
      scrollMessages();
      break;
    case "transcript":
      if (message.role === "assistant" && message.final) {
        if (assistantMessage) {
          assistantMessage.querySelector(".content").textContent = message.text;
          assistantMessage = null;
        } else {
          appendMessage("assistant", message.text);
        }
        playEarcon("done");
      } else if (message.role !== "assistant" || !message.final) {
        if (!(message.role === "user" && message.source === "text")) appendMessage(message.role, message.text);
      }
      break;
    case "audio":
      enqueueAudio(message.data);
      break;
    case "warmup":
      handleWarmup(message);
      break;
    case "notice":
      appendMessage("system", message.message);
      break;
    case "error":
      appendMessage("error", message.message);
      setState("error");
      playEarcon("error");
      break;
    default:
      break;
  }
}

function handleWarmup(message) {
  if (message.state === "starting") {
    realtimeReady = false;
    elements.connectionStatus.textContent = "Warming";
  } else if (message.state === "loading" && message.component) {
    elements.statusText.textContent = `Loading ${message.component}…`;
  } else if (message.state === "ready" || message.state === "degraded") {
    realtimeReady = true;
    elements.connectionStatus.textContent = message.state === "ready" ? "Ready" : "Online";
    if (!micActive) elements.statusText.textContent = "Tap mic to start";
    if (message.state === "degraded" && message.message) appendMessage("error", message.message);
    // push current preferences to backend
    sendPermissions();
    sendJson({ type: "settings", voice_profile: activeVoiceProfile() });
  }
}

function setState(state) {
  elements.statusText.textContent = STATUS_LABELS[state] || state;
  elements.statusDot.className = `status-dot ${state}`;
  elements.stage.dataset.state = state;
  avatar.setState(state);
}

/* ── microphone capture ───────────────────────────────────────────── */
async function startMic() {
  if (!realtimeReady) { showToast("Still warming up…"); return; }
  try {
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      video: false,
    });

    captureContext = new AudioContext({ latencyHint: "interactive" });
    const source = captureContext.createMediaStreamSource(micStream);
    processor = captureContext.createScriptProcessor(CAPTURE_BUFFER_SIZE, 1, 1);
    const mute = captureContext.createGain();
    mute.gain.value = 0;

    processor.onaudioprocess = (event) => {
      if (!micActive || !socket || socket.readyState !== WebSocket.OPEN) return;
      const input = event.inputBuffer.getChannelData(0);
      const resampled = downsample(input, captureContext.sampleRate, TARGET_SAMPLE_RATE);
      updateMicLevel(resampled);
      sendPcmFrames(floatToInt16(resampled));
    };

    source.connect(processor);
    processor.connect(mute);
    mute.connect(captureContext.destination);

    micActive = true;
    elements.micButton.classList.add("active");
    elements.micLevel.parentElement.classList.add("visible");
    setState("sleeping");
  } catch (error) {
    appendMessage("error", `Mic error: ${error.message}`);
  }
}

function stopMic() {
  micActive = false;
  pendingSamples = new Int16Array(0);
  updateMicLevel(new Float32Array(0));
  elements.micButton.classList.remove("active");
  elements.micLevel.parentElement.classList.remove("visible");
  elements.statusText.textContent = "Tap mic to start";
  if (processor) processor.disconnect();
  if (captureContext) captureContext.close();
  if (micStream) micStream.getTracks().forEach((track) => track.stop());
}

function updateMicLevel(buffer) {
  if (!elements.micLevel) return;
  if (!buffer.length) { elements.micLevel.style.width = "0%"; return; }
  let sum = 0;
  for (let i = 0; i < buffer.length; i += 1) sum += buffer[i] * buffer[i];
  const rms = Math.sqrt(sum / buffer.length);
  elements.micLevel.style.width = `${Math.min(100, Math.round(rms * 720))}%`;
}

function sendPcmFrames(chunk) {
  const merged = new Int16Array(pendingSamples.length + chunk.length);
  merged.set(pendingSamples, 0);
  merged.set(chunk, pendingSamples.length);
  let offset = 0;
  while (merged.length - offset >= FRAME_SAMPLES) {
    socket.send(merged.slice(offset, offset + FRAME_SAMPLES).buffer);
    offset += FRAME_SAMPLES;
  }
  pendingSamples = merged.slice(offset);
}

function downsample(buffer, inputRate, outputRate) {
  if (inputRate === outputRate) return buffer;
  const ratio = inputRate / outputRate;
  const length = Math.floor(buffer.length / ratio);
  const result = new Float32Array(length);
  for (let i = 0; i < length; i += 1) {
    const start = Math.floor(i * ratio);
    const end = Math.min(Math.floor((i + 1) * ratio), buffer.length);
    let sum = 0;
    for (let j = start; j < end; j += 1) sum += buffer[j];
    result[i] = sum / Math.max(1, end - start);
  }
  return result;
}

function floatToInt16(buffer) {
  const result = new Int16Array(buffer.length);
  for (let i = 0; i < buffer.length; i += 1) {
    const sample = Math.max(-1, Math.min(1, buffer[i]));
    result[i] = sample < 0 ? sample * 32768 : sample * 32767;
  }
  return result;
}

function sendJson(payload) {
  if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(payload));
}

/* ── audio playback ───────────────────────────────────────────────── */
function enqueueAudio(base64Audio) {
  playbackQueue = playbackQueue.then(() => scheduleAudio(base64Audio)).catch((error) => {
    appendMessage("error", `Audio error: ${error.message}`);
  });
}

async function scheduleAudio(base64Audio) {
  await ensurePlaybackContext();
  const audioBuffer = await playbackContext.decodeAudioData(base64ToArrayBuffer(base64Audio));
  const source = playbackContext.createBufferSource();
  source.buffer = audioBuffer;
  source.connect(playbackGain);
  const startAt = Math.max(playbackContext.currentTime + 0.025, nextPlayTime);
  source.start(startAt);
  nextPlayTime = startAt + audioBuffer.duration;
  source.onended = () => { if (playbackContext.currentTime >= nextPlayTime - 0.05) nextPlayTime = 0; };
}

async function ensurePlaybackContext() {
  if (!playbackContext) {
    playbackContext = new AudioContext({ latencyHint: "interactive" });
    playbackGain = playbackContext.createGain();
    playbackGain.gain.value = volume;
    playbackGain.connect(playbackContext.destination);
  }
  if (playbackContext.state === "suspended") await playbackContext.resume();
}

function base64ToArrayBuffer(base64) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

/* ── conversation bubbles ─────────────────────────────────────────── */
function appendMessage(role, text) {
  const message = document.createElement("div");
  message.className = `message ${role}`;
  const roleNode = document.createElement("span");
  roleNode.className = "role";
  roleNode.textContent = role;
  const content = document.createElement("span");
  content.className = "content";
  content.textContent = text;
  message.append(roleNode, content);
  elements.messages.append(message);
  while (elements.messages.childElementCount > 12) elements.messages.firstElementChild.remove();
  scrollMessages();
  return message;
}

function scrollMessages() {
  elements.messages.scrollTop = elements.messages.scrollHeight;
}

let toastTimer;
function showToast(message) {
  if (!elements.toast) return;
  elements.toast.textContent = message;
  elements.toast.hidden = false;
  requestAnimationFrame(() => elements.toast.classList.add("show"));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    elements.toast.classList.remove("show");
    setTimeout(() => { elements.toast.hidden = true; }, 260);
  }, 2400);
}

/* ── driving-safe mode ────────────────────────────────────────────── */
const drivingSafeToggle = document.querySelector("#drivingSafeToggle");
const vehicleHudToggle = document.querySelector("#vehicleHudToggle");
const vehicleHud = document.querySelector("#vehicleHud");

function setDrivingSafe(on) {
  document.body.classList.toggle("driving-safe", on);
  if (drivingSafeToggle) drivingSafeToggle.checked = on;
}

function setVehicleHud(on) {
  if (vehicleHud) vehicleHud.hidden = !on;
  if (vehicleHudToggle) vehicleHudToggle.checked = on;
}

if (drivingSafeToggle) {
  drivingSafeToggle.addEventListener("change", () => {
    setDrivingSafe(drivingSafeToggle.checked);
    showToast(drivingSafeToggle.checked ? "Safe driving mode on." : "Safe driving mode off.");
    saveUIModePrefs();
  });
}

if (vehicleHudToggle) {
  vehicleHudToggle.addEventListener("change", () => {
    setVehicleHud(vehicleHudToggle.checked);
    showToast(vehicleHudToggle.checked ? "Vehicle HUD on." : "Vehicle HUD off.");
    saveUIModePrefs();
  });
}

function saveUIModePrefs() {
  localStorage.setItem("echo-ai-ui", JSON.stringify({
    drivingSafe: drivingSafeToggle?.checked || false,
    vehicleHud: vehicleHudToggle?.checked || false,
  }));
}

function loadUIModePrefs() {
  try {
    const p = JSON.parse(localStorage.getItem("echo-ai-ui") || "{}");
    if (p.drivingSafe) setDrivingSafe(true);
    if (p.vehicleHud) setVehicleHud(true);
  } catch { /* ignore */ }
}

loadUIModePrefs();

// poll vehicle data every 5 s when HUD is visible
setInterval(async () => {
  if (!vehicleHud || vehicleHud.hidden) return;
  try {
    const res = await fetch("/api/vehicle");
    if (res.ok) updateHud(await res.json());
  } catch { /* offline or unavailable */ }
}, 5000);

/* ── vehicle HUD updates ──────────────────────────────────────────── */
function updateHud(data) {
  const speed = document.querySelector("#hudSpeedVal");
  const bat = document.querySelector("#hudBatVal");
  const batEl = document.querySelector("#hudBattery");
  const batBar = document.querySelector("#hudBattBar");
  const range = document.querySelector("#hudRangeVal");
  const temp = document.querySelector("#hudTempVal");

  if (speed) speed.textContent = data.speed_kmh ?? "—";
  if (bat && data.battery_pct != null) {
    const pct = Math.round(data.battery_pct);
    bat.textContent = pct;
    if (batEl) batEl.classList.toggle("low", pct < 20);
    if (batBar) batBar.setAttribute("width", Math.round(16 * pct / 100));
  }
  if (range) range.textContent = data.range_km ?? "—";
  if (temp) temp.textContent = data.cabin_temp_c ?? "—";

  // auto-enable driving-safe mode if speed > 20 km/h
  if ((data.speed_kmh ?? 0) > 20 && !document.body.classList.contains("driving-safe")) {
    setDrivingSafe(true);
  }
}
