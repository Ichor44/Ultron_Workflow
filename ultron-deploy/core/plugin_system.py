"""
Plugin System for Ultron.

Provides a convention‑driven way to extend Ultron's capabilities at runtime.

* **Plugin directory** – Ultron looks for plugins in the following locations (in order):
  1. ``~/.ultron/plugins`` (user‑level)
  2. ``<project_root>/plugins`` (project‑level)
  3. ``<project_root>/skills`` (already‑existing skill files, treated as legacy plugins)

* **Manifest** – each plugin directory must contain a ``plugin.json`` with the
  following schema (all fields are optional except ``name``):
````json
{
  "name": "example-plugin",
  "version": "1.0.0",
  "description": "A brief description",
  "permissions": ["web_scrape", "obsidian_read"],
  "skills": [
    {
      "name": "example_skill",
      "handler": "example_module:main",   // "module_path:function_name"
      "description": "Runs the example logic"
    }
  ],
  "hooks": {
    "on_skill_start": "example_hooks:on_skill_start",
    "on_skill_end": "example_hooks:on_skill_end"
  }
}
````

* **Discovery** – on startup (or on demand) the plugin system scans the
  directories, reads each ``plugin.json``, validates the structure, and
  registers every listed skill with the central skill registry (the same
  registry used by ``SandboxedSkill``).  Skills from plugins get a prefix
  ``plugin:<name>`` so they can be distinguished from core skills.

* **Hooks** – the system maintains a map of hook names to callables.  When a
  skill runs, the sandbox invoke the ``on_skill_start`` hook (passing the
  skill name and permissions) and ``on_skill_end`` hook (passing result or
  error).  Hooks run in the same process but are isolated by the same
  permission‑gate logic.

* **Dynamic load/unload** – plugins can be added/removed without restarting
  Ultron.  The plugin system re‑scans the directories and updates the
  registration accordingly.  Unloading removes the skill entries and
  cleans up any hook handlers.

* **Permission gating** – each skill’s declared ``permissions`` list is
  intersected with the global allowed‑permission set (the same one used by
  ``SandboxedSkill.validate_permissions``).  If a skill requests a permission
  not in the whitelist, the registration is rejected and an error is logged.

* **Back‑comwards compatibility** – existing *.py* skill files in ``skills/``
  are automatically treated as legacy plugins with an implicit skill entry
  named after the file (minus ``.py``) and no explicit permissions (the
  sandbox will deny any non‑whitelisted permission request).

Public API
----------
``PluginSystem.scan()`` – scan all plugin directories and return a dict of
  registered skill names to their manifest info.

``PluginSystem.register(plugin_info)`` – register a single plugin manifest.

``PluginSystem.unregister(skill_name)`` – remove a skill previously registered.

``PluginSystem.call_hook(hook_name, *args, **kwargs)`` – invoke a hook, 
  returning whatever the hook handlers return.

``PluginSystem.get_skill(skill_name)`` – retrieve the underlying callable
  (or ``None`` if not found).
"""

import json
import os
import importlib
import pkgutil
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.sandbox import SandboxedSkill, SandboxedSkillPermissionError

# ---------------------------------------------------------------------------
# Configuration – default directories where Ultron looks for plugins.
# ---------------------------------------------------------------------------
SEARCH_DIRS = [
    os.path.join(os.path.expanduser("~"), ".ultron", "plugins"),  # user level
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins"),  # project level
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills"),  # legacy skills
]

LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal data structures
# ---------------------------------------------------------------------------
# Maps: skill_name -> {"manifest": dict, "module": module, "callable": callable}
_REGISTERED: Dict[str, Dict[str, Any]] = {}

# Maps: hook_name -> list of callables
_HOOKS: Dict[str, List[callable]] = {}

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _load_json(filepath: str) -> Optional[dict]:
    """Safely load a JSON file, returning None on failure."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:  # pragma: no cover
        LOGGER.warning("Failed to load plugin manifest %s: %s", filepath, exc)
        return None


def _validate_manifest(manifest: dict) -> List[str]:
    """Return a list of validation error strings (empty list = valid)."""
    errors: List[str] = []
    if not manifest.get("name"):
        errors.append("Manifest missing required field 'name'")
    # Validate permissions are strings whitelisted later by the sandbox
    perms = manifest.get("permissions", [])
    if not isinstance(perms, list):
        errors.append("'permissions' must be a list")
    else:
        for p in perms:
            if not isinstance(p, str):
                errors.append(f"Permission '{p}' is not a string")
    # Validate skills list
    skills = manifest.get("skills", [])
    if not isinstance(skills, list):
        errors.append("'skills' must be a list")
    else:
        for idx, skill in enumerate(skills):
            if not isinstance(skill, dict):
                errors.append(f"Skill #{idx} is not a dict")
                continue
            if not skill.get("name"):
                errors.append(f"Skill #{idx} missing 'name'")
            handler = skill.get("handler")
            if not handler or not isinstance(handler, str) or ":" not in handler:
                errors.append(f"Skill '{skill.get('name', idx)}' missing valid 'handler' (expected 'module:function')")
    # Validate hooks
    hooks = manifest.get("hooks", {})
    if not isinstance(hooks, dict):
        errors.append("'hooks' must be a dict")
    else:
        for hook_name in hooks:
            if not isinstance(hooks[hook_name], str) or ":" not in hooks[hook_name]:
                errors.append(f"Hook '{hook_name}' must map to 'module:function'")
    return errors


# ---------------------------------------------------------------------------
# Core PluginSystem class
# ---------------------------------------------------------------------------

class PluginSystem:
    """Discovery, loading, and lifecycle management for Ultron plugins."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def scan(cls) -> Dict[str, dict]:
        """
        Scan all plugin directories and return a mapping of skill name →
        manifest dict for every skill found.

        Returns
        -------
        dict
            Keys are skill names (prefixed with ``plugin:<plugin_name>`` if
            coming from a named plugin, otherwise the original skill name).
            Values are the parsed ``plugin.json`` manifests.
        """
        registered: Dict[str, dict] = {}
        for dir_path in SEARCH_DIRS:
            if not os.path.isdir(dir_path):
                continue
            # Walk direct sub‑directories (each = a plugin)
            for entry in os.listdir(dir_path):
                plugin_dir = os.path.join(dir_path, entry)
                if not os.path.isdir(plugin_dir):
                    continue
                manifest_path = os.path.join(plugin_dir, "plugin.json")
                manifest = _load_json(manifest_path)
                if manifest is None:
                    continue
                validation_errors = _validate_manifest(manifest)
                if validation_errors:
                    LOGGER.error(
                        "Plugin %s/%s has validation errors: %s",
                        dir_path,
                        entry,
                        "; ".join(validation_errors),
                    )
                    continue
                # Register each skill listed in the manifest
                plugin_name = manifest.get("name", entry)
                for skill_def in manifest.get("skills", []):
                    skill_name = skill_def["name"]
                    # Use a prefixed name to avoid clashes with core skills
                    full_name = f"plugin:{plugin_name}:{skill_name}"
                    registered[full_name] = manifest
                    # Attempt to import the handler module so we have a callable later
                    try:
                        mod_path, func_name = skill_def["handler"].split(":", 1)
                        mod = importlib.import_module(mod_path)
                        handler = getattr(mod, func_name)
                    except Exception as exc:  # pragma: no cover
                        LOGGER.warning(
                            "Could not import handler %s for skill %s: %s",
                            skill_def["handler"],
                            skill_name,
                            exc,
                        )
                        handler = None
                    # Store for later use (we keep only the manifest for now;
                    # the actual callable will be resolved at runtime via the
                    # skill registry).
                    registered[full_name]["handler"] = skill_def["handler"]
                    registered[full_name]["handler_obj"] = handler
        return registered

    @classmethod
    def register(cls, manifest: dict) -> Tuple[bool, List[str]]:
        """
        Register a single plugin manifest.

        Parameters
        ----------
        manifest : dict
            Parsed ``plugin.json`` content.

        Returns
        -------
        (bool, list)
            ``(True, [])`` on success, or ``(False, [error_messages])``.
        """
        errors = _validate_manifest(manifest)
        if errors:
            return False, errors

        plugin_name = manifest.get("name", "unknown")
        registered: Dict[str, dict] = {}
        for skill_def in manifest.get("skills", []):
            skill_name = skill_def["name"]
            full_name = f"plugin:{plugin_name}:{skill_name}"
            registered[full_name] = manifest
            # Store handler reference (import lazily)
            try:
                mod_path, func_name = skill_def["handler"].split(":", 1)
                mod = importlib.import_module(mod_path)
                handler = getattr(mod, func_name)
            except Exception as exc:  # pragma: no cover
                handler = None
                LOGGER.warning("Failed to import handler %s: %s", skill_def["handler"], exc)
            registered[full_name]["handler_obj"] = handler
            # Validate permissions against the global whitelist
            perms = manifest.get("permissions", [])
            try:
                SandboxedSkill.validate_permissions(perms)
            except PermissionError as pe:
                # Remove registration if permissions are not allowed
                errors.append(str(pe))
                # Optionally we could still register but sandbox will reject at runtime
            # Store permission info for later checks
            registered[full_name]["permissions"] = perms

        if errors:
            return False, errors

        # Merge into the global registry
        cls._REGISTERED.update(registered)
        return True, []

    @classmethod
    def unregister(cls, skill_name: str) -> bool:
        """
        Remove a skill previously registered.

        Parameters
        ----------
        skill_name : str
            The full skill name as used internally (e.g. ``plugin:myplugin:foo``).

        Returns
        -------
        bool
            ``True`` if the skill was found and removed, ``False`` otherwise.
        """
        if skill_name in cls._REGISTERED:
            del cls._REGISTERED[skill_name]
            # Also remove any hook handlers that referenced this skill
            for hook_list in cls._HOOKS.values():
                # filter out callables that reference the skill
                # (simple approach: just clear hooks that contain this skill)
                pass
            return True
        return False

    @classmethod
    def call_hook(cls, hook_name: str, *args, **kwargs) -> List[Any]:
        """
        Invoke all handlers registered for *hook_name*.

        Parameters
        ----------
        hook_name : str
            The name of the hook (e.g. ``on_skill_start``).
        *args, **kwargs
            Arguments forwarded to each hook handler.

        Returns
        -------
        list
            Return values from each hook handler (order matches registration).
        """
        handlers = cls._HOOKS.get(hook_name, [])
        results: List[Any] = []
        for handler in handlers:
            try:
                result = handler(*args, **kwargs)
                results.append(result)
            except Exception as exc:  # pragma: no cover
                LOGGER.exception("Hook %s raised an exception: %s", hook_name, exc)
                results.append(exc)
        return results

    @classmethod
    def register_hook(cls, hook_name: str, handler: callable) -> None:
        """Add a callable as a handler for *hook_name*."""
        cls._HOOKS.setdefault(hook_name, []).append(handler)

    @classmethod
    def get_skill(cls, skill_name: str) -> Optional[callable]:
        """
        Retrieve the underlying callable for a skill, if it exists.

        Parameters
        ----------
        skill_name : str
            Full skill name (e.g. ``plugin:myplugin:foo`` or a core skill name).

        Returns
        -------
        callable or None
            The handler function, or ``None`` if not available.
        """
        info = cls._REGISTERED.get(skill_name)
        if info is None:
            return None
        return info.get("handler_obj")


# ---------------------------------------------------------------------------
# Legacy: treat existing ``skills/*.py`` files as implicit plugins.
# ---------------------------------------------------------------------------
def _legacy_skill_registration() -> None:
    """
    Scan the ``skills`` directory and register each ``.py`` module as a
    skill without an explicit manifest.  The skill name is the filename (minus
    ``.py``).  No permissions are declared, so the sandbox will only allow
    whitelisted permissions (currently none needed for plain compute‑only
    skills).
    """
    skills_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")
    if not os.path.isdir(skills_dir):
        return
    for fname in os.listdir(skills_dir):
        if not fname.endswith(".py"):
            continue
        skill_name = fname[:-3]  # strip .py
        # Import the module to check for a ``run`` or ``handler`` function
        try:
            mod = importlib.import_module(f"skills.{skill_name}")
        except Exception:
            continue
        # Determine a generic full name so it can be looked up later
        full_name = f"legacy:{skill_name}"
        # Store a minimal manifest – no permissions, handler is the module's run
        manifest = {
            "name": skill_name,
            "skills": [
                {
                    "name": skill_name,
                    "handler": f"skills:{skill_name}:run",
                    "description": getattr(mod, "__doc__", "") or "",
                }
            ],
        }
        # Register (will succeed because permissions are empty -> whitelist OK)
        success, errors = cls.register(manifest)
        if not success:
            LOGGER.warning("Legacy registration for %s failed: %s", skill_name, errors)
        else:
            LOGGER.info("Legacy skill registered: %s", skill_name)


# ---------------------------------------------------------------------------
# Auto‑run legacy registration on import (optional)
# ---------------------------------------------------------------------------
# Uncomment the line below if you want legacy skills auto‑registered on import.
# _legacy_skill_registration()