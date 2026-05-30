// Image-sequence avatar player. Plays the cropped frame folders
// (normal / listen / loding / error) as a looping animation on a canvas.
// Frames sit on solid black; the stage background is also black and the
// canvas edge is feathered (CSS mask), so the avatar blends in seamlessly.

const MANIFEST_URL = "/assets/avatar/manifest.json";

// app pipeline state  ->  frame folder
const STATE_TO_FOLDER = {
  sleeping: "normal",
  listening: "listen",
  processing: "loding",
  speaking: "listen", // no separate "talking" folder — reuse listen
  error: "error",
};

export class EchoAvatar {
  constructor(canvas) {
    this._canvas = canvas;
    this._ctx = canvas.getContext("2d");
    this._fps = 24;
    this._pad = 4;
    this._states = {};        // key -> { count, ext }
    this._frames = {};        // key -> [Image, ...]
    this._folder = "normal";
    this._index = 0;
    this._lastAdvance = 0;
    this._dpr = Math.min(window.devicePixelRatio || 1, 2);

    this._resize();
    new ResizeObserver(() => this._resize()).observe(canvas);

    this._init();
  }

  async _init() {
    try {
      const manifest = await (await fetch(MANIFEST_URL)).json();
      this._fps = manifest.fps || 24;
      this._pad = manifest.pad || 4;
      this._states = manifest.states || {};
    } catch {
      // manifest missing — nothing to play, keep canvas black
      return;
    }

    // Load the default state first so idle shows immediately, then the rest.
    await this._loadFolder("normal");
    requestAnimationFrame((t) => this._loop(t));

    for (const key of Object.keys(this._states)) {
      if (key !== "normal") this._loadFolder(key);
    }
  }

  _loadFolder(key) {
    if (this._frames[key]) return Promise.resolve();
    const meta = this._states[key];
    if (!meta) return Promise.resolve();

    const images = new Array(meta.count);
    this._frames[key] = images;
    let firstLoaded;
    const firstPromise = new Promise((resolve) => (firstLoaded = resolve));

    for (let i = 0; i < meta.count; i += 1) {
      const img = new Image();
      img.decoding = "async";
      img.src = `/assets/avatar/${key}/${String(i + 1).padStart(this._pad, "0")}.${meta.ext}`;
      if (i === 0) img.onload = () => firstLoaded();
      images[i] = img;
    }
    return firstPromise;
  }

  // app.js calls these — keep the same surface as the old orb
  setState(state) {
    const folder = STATE_TO_FOLDER[state] || "normal";
    if (folder === this._folder) return;
    this._folder = folder;
    this._index = 0;
    this._lastAdvance = 0;
    if (!this._frames[folder]) this._loadFolder(folder);
  }

  setAudioLevel() { /* no-op: frame sequences are pre-rendered */ }

  _resize() {
    const w = this._canvas.clientWidth || 480;
    const h = this._canvas.clientHeight || 480;
    this._dpr = Math.min(window.devicePixelRatio || 1, 2);
    this._canvas.width = Math.round(w * this._dpr);
    this._canvas.height = Math.round(h * this._dpr);
  }

  _loop(now) {
    requestAnimationFrame((t) => this._loop(t));

    const frames = this._frames[this._folder];
    if (!frames || !frames.length) return;

    const interval = 1000 / this._fps;
    if (!this._lastAdvance) this._lastAdvance = now;
    if (now - this._lastAdvance >= interval) {
      this._index = (this._index + 1) % frames.length;
      this._lastAdvance = now;
    }

    const img = frames[this._index] || frames[0];
    if (!img || !img.complete || !img.naturalWidth) return;

    const cw = this._canvas.width;
    const ch = this._canvas.height;
    this._ctx.clearRect(0, 0, cw, ch);

    // contain-fit, centered
    const scale = Math.min(cw / img.naturalWidth, ch / img.naturalHeight);
    const dw = img.naturalWidth * scale;
    const dh = img.naturalHeight * scale;
    this._ctx.drawImage(img, (cw - dw) / 2, (ch - dh) / 2, dw, dh);
  }
}
