"""Stage the cropped frame sequences for the web UI.

Copies the root-level state folders (normal / Listen / loding / error) into
frontend/assets/avatar/<state>/ with predictable zero-padded names
(0001.png, 0002.png, ...) and writes a manifest.json the frontend reads.

Run:  python scripts/prepare_avatar.py
Idempotent — safe to re-run after re-cropping frames.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEST_ROOT = PROJECT_ROOT / "frontend" / "assets" / "avatar"

# source folder on disk  ->  state key used by the UI
SOURCES = {
    "normal": "normal",
    "Listen": "listen",
    "loding": "loding",
    "error": "error",
}

DEFAULT_FPS = 24


def stage_state(src_name: str, state_key: str) -> int:
    src = PROJECT_ROOT / src_name
    dest = DEST_ROOT / state_key
    if not src.is_dir():
        print(f"  ! source folder missing, skipping: {src}")
        return 0

    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    frames = sorted(src.glob("*.png"))
    for index, frame in enumerate(frames, start=1):
        shutil.copyfile(frame, dest / f"{index:04d}.png")

    print(f"  {src_name:8s} -> {state_key:8s}  {len(frames)} frames")
    return len(frames)


def main() -> None:
    DEST_ROOT.mkdir(parents=True, exist_ok=True)
    print(f"Staging avatar frames into {DEST_ROOT}")

    states: dict[str, dict] = {}
    for src_name, state_key in SOURCES.items():
        count = stage_state(src_name, state_key)
        if count:
            states[state_key] = {"count": count, "ext": "png"}

    manifest = {"fps": DEFAULT_FPS, "pad": 4, "states": states}
    (DEST_ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote manifest.json: {json.dumps(manifest)}")


if __name__ == "__main__":
    main()
