"""Optimized file output module with atomic writes and path safety.

Provides high-performance file I/O operations with:
- Atomic writes (write to temp then rename)
- Filename sanitization cache
- Efficient path resolution
"""

import base64
import os
import uuid
import threading
from typing import Dict, List, Optional, Any

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")

# Filename sanitization cache
_sanitize_cache: Dict[str, str] = {}
_sanitize_cache_size = 256
_sanitize_lock = threading.Lock()


def ensure_dirs():
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def _sanitize_filename(filename: str) -> str:
    """Sanitize filename with caching for repeated calls."""
    if filename in _sanitize_cache:
        return _sanitize_cache[filename]
    
    safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in filename)
    
    # LRU eviction
    with _sanitize_lock:
        if len(_sanitize_cache) >= _sanitize_cache_size:
            _sanitize_cache.pop(next(iter(_sanitize_cache)))
        _sanitize_cache[filename] = safe
    
    return safe


def save_file(filename, content, is_base64=False):
    """Save file with atomic write and collision handling.
    
    Features:
    - Atomic write: write to temp file then rename (crash-safe)
    - Filename collision avoidance with UUID suffix
    - Thorough temp file cleanup on error
    - Base64 content decoding support
    """
    ensure_dirs()
    safe_name = _sanitize_filename(filename)
    path = os.path.join(OUTPUT_DIR, safe_name)
    
    # Handle filename collisions efficiently
    if os.path.exists(path):
        name, ext = os.path.splitext(safe_name)
        # Use short UUID for collision avoidance
        path = os.path.join(OUTPUT_DIR, "%s_%s%s" % (name, uuid.uuid4().hex[:6], ext))
    
    data = base64.b64decode(content) if is_base64 else content.encode("utf-8")
    mode = "wb"
    
    # Atomic write: write to temp file then rename
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, mode) as f:
            f.write(data)
        os.replace(tmp_path, path)
    except Exception:
        # Clean up temp file on error - best effort
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        # Also clean up any partially written target file
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
        raise
    
    # Schedule temp file cleanup (in case rename didn't happen)
    _cleanup_orphan_tmps()
    
    rel_path = os.path.relpath(path, OUTPUT_DIR)
    return {
        "path": path,
        "filename": os.path.basename(path),
        "size": len(data),
        "download_url": "/api/output/%s" % os.path.basename(path),
    }


def _cleanup_orphan_tmps():
    """Clean up any orphaned .tmp files in the output directory.
    
    This handles cases where an agent crashed mid-write, leaving
    .tmp files that would cause 'file-already-exists' errors on retry.
    """
    try:
        if not os.path.exists(OUTPUT_DIR):
            return
        for name in os.listdir(OUTPUT_DIR):
            if name.endswith(".tmp"):
                try:
                    os.remove(os.path.join(OUTPUT_DIR, name))
                except Exception:
                    pass  # Best effort cleanup
    except Exception:
        pass  # Directory may not exist or be accessible


def list_files():
    """List files in output directory."""
    ensure_dirs()
    files = []
    try:
        for name in sorted(os.listdir(OUTPUT_DIR)):
            fpath = os.path.join(OUTPUT_DIR, name)
            if os.path.isfile(fpath):
                stat = os.stat(fpath)
                files.append({
                    "filename": name,
                    "size": stat.st_size,
                    "download_url": "/api/output/%s" % name,
                })
    except FileNotFoundError:
        pass
    return files


def get_file_path(filename):
    """Get full path for a file by name (basename only for safety)."""
    ensure_dirs()
    safe = os.path.basename(filename)
    path = os.path.join(OUTPUT_DIR, safe)
    return path if os.path.exists(path) else None