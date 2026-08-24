"""Optimized recipe management with caching.

Provides high-performance recipe loading and management
with LRU caching and change notifications.
"""

import glob
import json
import os
import re
import threading
from typing import Dict, List, Optional, Any

from core.cache import get_cache_manager, cached_recipe, monitor

RECIPES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "recipes")

# Change notification callbacks
_on_change_callbacks = []

# Regex for parsing frontmatter
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)


def ensure_dirs():
    os.makedirs(RECIPES_DIR, exist_ok=True)


def register_on_change(callback):
    """Register a callback to be called when recipes change."""
    if callback not in _on_change_callbacks:
        _on_change_callbacks.append(callback)


def _notify_change():
    for cb in _on_change_callbacks:
        try:
            cb()
        except Exception:
            pass
    # Invalidate cache on change
    get_cache_manager().invalidate('recipes')


def _recipe_path(name):
    safe = "".join(c if (c.isalnum() or c in "_-") else "_" for c in name)
    return os.path.join(RECIPES_DIR, safe + ".md")


@cached_recipe
@monitor("recipes.list_recipes")
def list_recipes():
    """List all recipes - cached."""
    ensure_dirs()
    out = []
    for path in glob.glob(os.path.join(RECIPES_DIR, "*.md")):
        name = os.path.splitext(os.path.basename(path))[0]
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        meta, body = parse(text)
        out.append({
            "name": meta.get("name") or name,
            "description": meta.get("description") or (body.strip().splitlines()[0] if body.strip() else name),
            "triggers": meta.get("triggers", ""),
            "file": os.path.basename(path),
        })
    return out


def parse(text):
    """Parse frontmatter from markdown text."""
    meta = {}
    body = text
    if text.startswith("---"):
        m = _FRONTMATTER_RE.match(text)
        if m:
            fm, body = m.group(1), m.group(2)
            for line in fm.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip().lower()] = v.strip()
    return meta, body


@cached_recipe
def read_recipe(name):
    """Read recipe markdown - cached."""
    path = _recipe_path(name)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    for p in glob.glob(os.path.join(RECIPES_DIR, "*.md")):
        with open(p, "r", encoding="utf-8") as f:
            t = f.read()
        meta, _ = parse(t)
        if (meta.get("name") or os.path.splitext(os.path.basename(p))[0]) == name:
            return t
    return None


@cached_recipe
def load_recipe(name):
    """Load parsed recipe - cached."""
    text = read_recipe(name)
    if text is None:
        return None
    meta, body = parse(text)
    return {
        "name": meta.get("name") or name,
        "description": meta.get("description", ""),
        "triggers": meta.get("triggers", ""),
        "body": body,
        "raw": text,
    }


def write_recipe(name, markdown):
    """Write a recipe file and notify change callbacks."""
    ensure_dirs()
    path = _recipe_path(name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(markdown)
    _notify_change()
    return path


def use_recipe(name, args):
    """Use a recipe with provided arguments."""
    r = load_recipe(name)
    if r is None:
        return "Recipe '%s' not found." % name
    arg_str = ""
    if args:
        try:
            arg_str = "\nProvided inputs:\n" + json.dumps(args, indent=2)
        except Exception:
            arg_str = "\nProvided inputs: %s" % args
    return ("RECIPE: %s\nDESCRIPTION: %s\n\n%s%s\n\nFollow the recipe above to fulfill the user's request."
            % (r["name"], r["description"], r["body"], arg_str))


def delete_recipe(name):
    """Delete a recipe file."""
    ensure_dirs()
    path = _recipe_path(name)
    if os.path.exists(path):
        os.remove(path)
        _notify_change()
        return True
    return False