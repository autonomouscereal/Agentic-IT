#!/usr/bin/env python3
"""Render a short deterministic MP4 motion graphic with ffmpeg.

This helper is intentionally small so chat harnesses can produce a safe demo
animation artifact without installing packages or fetching remote assets.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def clean_text(value: str, fallback: str) -> str:
    text = " ".join(str(value or fallback).split())
    text = text.replace("\\", " ").replace(":", " ").replace("'", " ")
    return text[:80] or fallback


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a simple MP4 animation.")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--title", default="Agentic Operations")
    parser.add_argument("--subtitle", default="Validated animation artifact")
    parser.add_argument("--marker", default="")
    parser.add_argument("--duration", type=float, default=3.0)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=30)
    args = parser.parse_args()

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print(json.dumps({"ok": False, "error": "ffmpeg not found"}))
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    duration = max(1.0, min(float(args.duration), 10.0))
    width = max(320, min(int(args.width), 1920))
    height = max(240, min(int(args.height), 1080))
    fps = max(12, min(int(args.fps), 60))
    title = clean_text(args.title, "Agentic Operations")
    subtitle = clean_text(args.subtitle, "Validated animation artifact")
    marker = clean_text(args.marker, "") if args.marker else ""
    box_y = int(height / 2 - 55)
    track_y = int(height / 2 + 125)
    track_width = max(80, width - 320)
    box_travel = max(40, width - 300)

    text_filters = [
        f"drawtext=text='{title}':fontcolor=white:fontsize=54:x=(w-text_w)/2:y=90",
        f"drawtext=text='{subtitle}':fontcolor=0xD1FAE5:fontsize=32:x=(w-text_w)/2:y=168",
    ]
    if marker:
        text_filters.append(
            f"drawtext=text='{marker}':fontcolor=0xCBD5E1:fontsize=24:x=(w-text_w)/2:y=h-86"
        )
    vf = ",".join([
        "format=yuv420p",
        "drawbox=x=0:y=0:w=iw:h=ih:color=0x0F172A@1:t=fill",
        "drawbox=x='120+{travel}*t/{d}':y={box_y}:w=110:h=110:color=0x38BDF8@0.95:t=fill".format(
            travel=box_travel,
            d=duration,
            box_y=box_y,
        ),
        f"drawbox=x=160:y={track_y}:w={track_width}:h=12:color=0x22C55E@0.95:t=fill",
        *text_filters,
    ])
    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s={width}x{height}:d={duration}:r={fps}",
        "-vf",
        vf,
        "-movflags",
        "+faststart",
        "-pix_fmt",
        "yuv420p",
        str(args.output),
    ]
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    result = {
        "ok": proc.returncode == 0 and args.output.exists() and args.output.stat().st_size > 1024,
        "path": str(args.output.resolve()),
        "bytes": args.output.stat().st_size if args.output.exists() else 0,
        "returncode": proc.returncode,
        "stderr": proc.stderr[-1000:],
    }
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
