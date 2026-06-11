#!/usr/bin/env python3
"""Bridge FastAPI honest-ad generation to the logged-in Magnific MCP.

Reads JSON on stdin:
  {"prompt": "...", "model": "realism", "resolution": "1k", "aspect_ratio": "widescreen_16_9"}

Prints JSON on stdout:
  {"url": "https://..."}
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CODEX = "/Applications/Codex.app/Contents/Resources/codex"


def _extract_url(text: str) -> str | None:
    try:
        parsed = json.loads(text)
    except Exception:
        parsed = None
    if isinstance(parsed, dict):
        for key in ("url", "image_url", "output_url"):
            value = parsed.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
    match = re.search(r"https?://[^\s\"'<>]+", text)
    return match.group(0).rstrip(".,") if match else None


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read() or b"{}")
    except Exception as exc:
        print(f"invalid json: {exc}", file=sys.stderr)
        return 2

    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        print("missing prompt", file=sys.stderr)
        return 2

    codex = os.environ.get("CODEX_CLI") or shutil.which("codex") or DEFAULT_CODEX
    model = payload.get("model") or "realism"
    resolution = payload.get("resolution") or "1k"
    aspect_ratio = payload.get("aspect_ratio") or "widescreen_16_9"
    timeout_s = float(payload.get("timeout_s") or 85)

    instruction = f"""Use the configured Magnific MCP OAuth image generation tool to create exactly one image.

Return only JSON exactly like {{"url":"https://..."}} with the final generated image URL. Do not include markdown or commentary.

Image settings:
- model: {model}
- resolution: {resolution}
- aspect ratio: {aspect_ratio}

Prompt:
{prompt}
"""

    with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as f:
        output_path = f.name

    env = {**os.environ, "NO_COLOR": "1", "TERM": os.environ.get("TERM") or "xterm-256color"}
    try:
        proc = subprocess.run(
            [
                codex,
                "exec",
                "--dangerously-bypass-approvals-and-sandbox",
                "-C",
                str(REPO_ROOT),
                "-o",
                output_path,
                instruction,
            ],
            cwd=str(REPO_ROOT),
            env=env,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=max(20, timeout_s - 2),
            check=False,
        )
        output = Path(output_path).read_text(encoding="utf-8", errors="ignore")
        url = _extract_url(output) or _extract_url(proc.stderr or "")
        if proc.returncode != 0 or not url:
            print((proc.stderr or output)[-2000:], file=sys.stderr)
            return 1
        print(json.dumps({"url": url}, separators=(",", ":")))
        return 0
    except subprocess.TimeoutExpired:
        print("magnific mcp bridge timed out", file=sys.stderr)
        return 1
    finally:
        try:
            Path(output_path).unlink()
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
