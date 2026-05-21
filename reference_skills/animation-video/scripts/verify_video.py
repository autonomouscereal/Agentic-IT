#!/usr/bin/env python
"""Validate a local MP4 artifact without requiring ffmpeg/ffprobe."""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path


def iter_boxes(data: bytes, start: int = 0, end: int | None = None):
    end = len(data) if end is None else end
    offset = start
    while offset + 8 <= end:
        size = struct.unpack(">I", data[offset : offset + 4])[0]
        box_type = data[offset + 4 : offset + 8].decode("ascii", errors="replace")
        header = 8
        if size == 1:
            if offset + 16 > end:
                break
            size = struct.unpack(">Q", data[offset + 8 : offset + 16])[0]
            header = 16
        elif size == 0:
            size = end - offset
        if size < header or offset + size > end:
            break
        yield box_type, offset, size, header
        offset += size


def parse_duration(data: bytes) -> float | None:
    for box_type, offset, size, header in iter_boxes(data):
        if box_type != "moov":
            continue
        moov_start = offset + header
        moov_end = offset + size
        for child_type, child_offset, child_size, child_header in iter_boxes(
            data, moov_start, moov_end
        ):
            if child_type != "mvhd":
                continue
            payload = child_offset + child_header
            version = data[payload]
            cursor = payload + 4
            if version == 1:
                cursor += 16
                timescale = struct.unpack(">I", data[cursor : cursor + 4])[0]
                duration = struct.unpack(">Q", data[cursor + 4 : cursor + 12])[0]
            else:
                cursor += 8
                timescale = struct.unpack(">I", data[cursor : cursor + 4])[0]
                duration = struct.unpack(">I", data[cursor + 4 : cursor + 8])[0]
            return duration / timescale if timescale else None
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an MP4 video file.")
    parser.add_argument("video", type=Path)
    parser.add_argument("--min-size", type=int, default=50_000)
    parser.add_argument("--expect-duration", type=float, default=None)
    parser.add_argument("--duration-tolerance", type=float, default=0.5)
    args = parser.parse_args()

    if not args.video.exists():
        print(json.dumps({"ok": False, "error": "missing file", "path": str(args.video)}))
        return 1

    data = args.video.read_bytes()
    boxes = [box_type for box_type, _, _, _ in iter_boxes(data)]
    duration = parse_duration(data)
    errors: list[str] = []

    if len(data) < args.min_size:
        errors.append(f"file is smaller than min size: {len(data)} < {args.min_size}")
    for required in ("ftyp", "moov", "mdat"):
        if required not in boxes:
            errors.append(f"missing MP4 box: {required}")
    if args.expect_duration is not None:
        if duration is None:
            errors.append("duration could not be read from mvhd")
        elif abs(duration - args.expect_duration) > args.duration_tolerance:
            errors.append(
                f"duration mismatch: {duration:.3f}s vs expected {args.expect_duration:.3f}s"
            )

    result = {
        "ok": not errors,
        "path": str(args.video.resolve()),
        "bytes": len(data),
        "top_level_boxes": boxes,
        "duration_seconds": duration,
        "errors": errors,
    }
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
