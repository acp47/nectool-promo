#!/usr/bin/env python3
"""Generate the Danish voice-over for the Nectool promo with ElevenLabs.

Reads the VO copy from SCRIPT.md, sends one request per paragraph, and writes
numbered MP3s plus a manifest into assets/vo/.

    export ELEVENLABS_API_KEY=...
    python3 scripts/generate-vo.py --list-voices     # pick a Danish voice
    export ELEVENLABS_VOICE_ID=...
    python3 scripts/generate-vo.py

The API key is only ever read from the environment — it is never written to
disk or into the manifest.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

API_ROOT = "https://api.elevenlabs.io/v1"
ROOT = Path(__file__).resolve().parent.parent
SCRIPT_MD = ROOT / "SCRIPT.md"
OUT_DIR = ROOT / "assets" / "vo"
DEFAULT_MODEL = "eleven_multilingual_v2"


def api_key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        sys.exit("ELEVENLABS_API_KEY is not set in the environment.")
    return key


def request(path: str, *, data: bytes | None = None, accept: str) -> bytes:
    req = urllib.request.Request(
        f"{API_ROOT}{path}",
        data=data,
        headers={
            "xi-api-key": api_key(),
            "accept": accept,
            **({"content-type": "application/json"} if data else {}),
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        sys.exit(f"ElevenLabs returned {exc.code} for {path}:\n{body}")
    except urllib.error.URLError as exc:
        sys.exit(f"Could not reach {API_ROOT}: {exc.reason}")


def read_vo_lines() -> list[str]:
    """Return the paragraphs under the '## VO' heading of SCRIPT.md."""
    text = SCRIPT_MD.read_text(encoding="utf-8")
    if "## VO" not in text:
        sys.exit(f"No '## VO' section found in {SCRIPT_MD}.")
    body = text.split("## VO", 1)[1]
    # Stop at the next heading of the same or higher level.
    for line in body.splitlines():
        if line.startswith("## ") or line.startswith("# "):
            body = body.split("\n" + line, 1)[0]
            break
    lines = [
        " ".join(block.split())
        for block in body.split("\n\n")
        if block.strip() and not block.lstrip().startswith("#")
    ]
    if not lines:
        sys.exit("The '## VO' section is empty.")
    return lines


def list_voices() -> None:
    voices = json.loads(request("/voices", accept="application/json"))["voices"]
    for voice in voices:
        labels = voice.get("labels") or {}
        detail = ", ".join(f"{k}={v}" for k, v in labels.items())
        print(f"{voice['voice_id']}  {voice['name']:<24} {detail}")


def duration_s(path: Path) -> float | None:
    """Probe the clip length, when ffprobe is available."""
    if not shutil.which("ffprobe"):
        return None
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        return round(float(out.stdout.strip()), 3)
    except ValueError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-voices", action="store_true",
                        help="print the account's voices and exit")
    parser.add_argument("--voice-id", default=os.environ.get("ELEVENLABS_VOICE_ID"),
                        help="voice to speak with (or set ELEVENLABS_VOICE_ID)")
    parser.add_argument("--model", default=os.environ.get("ELEVENLABS_MODEL", DEFAULT_MODEL),
                        help=f"TTS model (default: {DEFAULT_MODEL})")
    parser.add_argument("--stability", type=float, default=0.45)
    parser.add_argument("--similarity-boost", type=float, default=0.8)
    parser.add_argument("--speed", type=float, default=1.0)
    args = parser.parse_args()

    if args.list_voices:
        list_voices()
        return
    if not args.voice_id:
        sys.exit("No voice selected. Run with --list-voices, then pass --voice-id "
                 "or set ELEVENLABS_VOICE_ID.")

    lines = read_vo_lines()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {"provider": "elevenlabs", "model": args.model,
                "voice_id": args.voice_id, "language": "da", "lines": []}

    for index, text in enumerate(lines, start=1):
        payload = json.dumps({
            "text": text,
            "model_id": args.model,
            "voice_settings": {
                "stability": args.stability,
                "similarity_boost": args.similarity_boost,
                "speed": args.speed,
            },
        }).encode("utf-8")
        audio = request(f"/text-to-speech/{args.voice_id}", data=payload, accept="audio/mpeg")
        out = OUT_DIR / f"vo-{index:02d}.mp3"
        out.write_bytes(audio)
        entry = {"index": index, "text": text,
                 "path": str(out.relative_to(ROOT)), "duration_s": duration_s(out)}
        manifest["lines"].append(entry)
        print(f"{entry['path']}  ({len(audio)} bytes)  {text[:60]}")

    (OUT_DIR / "vo-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    total = sum(l["duration_s"] or 0 for l in manifest["lines"])
    print(f"\nWrote {len(lines)} clips + vo-manifest.json to {OUT_DIR.relative_to(ROOT)}"
          + (f" ({total:.1f}s total)" if total else ""))


if __name__ == "__main__":
    main()
