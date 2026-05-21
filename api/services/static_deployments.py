"""Approval-gated static site publishing helpers.

This adapter deliberately publishes only static files from an agent workspace
to a dashboard-owned directory. It does not open host ports, edit nginx, or
grant shell access to the host.
"""

from pathlib import Path
import os
import re
import shutil


PUBLISHED_SITES_DIR = os.getenv("PUBLISHED_SITES_DIR", "/app/data/published_sites")
MAX_STATIC_FILES = int(os.getenv("PUBLISHED_SITE_MAX_FILES", "200"))
MAX_STATIC_BYTES = int(os.getenv("PUBLISHED_SITE_MAX_BYTES", str(25 * 1024 * 1024)))
SAFE_EXTENSIONS = {
    ".html",
    ".htm",
    ".css",
    ".js",
    ".mjs",
    ".json",
    ".txt",
    ".md",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".woff",
    ".woff2",
}


def sanitize_slug(value):
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "").strip().lower()).strip("-")
    return slug[:80] or "agent-site"


def _resolve_inside(root, value):
    root_path = Path(root).resolve()
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root_path / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root_path)
    except ValueError as exc:
        raise ValueError("source_dir must stay inside the agent work directory") from exc
    return resolved


def _validate_static_tree(source):
    if not source.exists() or not source.is_dir():
        raise ValueError("source_dir does not exist or is not a directory")
    if not (source / "index.html").is_file():
        raise ValueError("static deployment requires index.html at the source root")

    files = []
    total_bytes = 0
    for path in source.rglob("*"):
        if path.is_symlink():
            raise ValueError("static deployment cannot include symlinks")
        if not path.is_file():
            continue
        if path.suffix.lower() not in SAFE_EXTENSIONS:
            raise ValueError(f"unsupported static file type: {path.name}")
        total_bytes += path.stat().st_size
        files.append(path)
        if len(files) > MAX_STATIC_FILES:
            raise ValueError(f"static deployment exceeds file limit of {MAX_STATIC_FILES}")
        if total_bytes > MAX_STATIC_BYTES:
            raise ValueError(f"static deployment exceeds byte limit of {MAX_STATIC_BYTES}")
    return {"file_count": len(files), "total_bytes": total_bytes}


def publish_static_site(work_dir, source_dir, slug, published_root=None):
    """Copy a validated static site from an agent workspace into published_root."""
    work_root = Path(work_dir).resolve()
    source = _resolve_inside(work_root, source_dir or ".")
    stats = _validate_static_tree(source)
    safe_slug = sanitize_slug(slug)
    root = Path(published_root or PUBLISHED_SITES_DIR).resolve()
    target = root / safe_slug
    tmp_target = root / f".{safe_slug}.tmp"
    root.mkdir(parents=True, exist_ok=True)
    if tmp_target.exists():
        shutil.rmtree(tmp_target)
    shutil.copytree(source, tmp_target)
    if target.exists():
        shutil.rmtree(target)
    tmp_target.replace(target)
    return {
        "slug": safe_slug,
        "source_dir": str(source),
        "target_dir": str(target),
        "relative_url": f"/published/{safe_slug}/",
        **stats,
    }
