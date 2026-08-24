"""
Skill Runner - executed inside the SandboxedSkill subprocess.

Responsibilities
----------------
1. Import the requested skill module (by name from the skills package).
2. Read the module-level PERMISSIONS set (required whitelist).
3. Intersect those permissions with the list supplied via stdin; if any
   requested permission is missing from the allowed set, exit with an error.
4. Locate and call the skill's entry point function (convention:
   run(**kwargs), where kwargs come from the sandbox's JSON args).
5. Emit a JSON payload to stdout containing either the result or an error
   message, so the parent process (SandboxedSkill) can parse it.

Convention for skill authors
----------------------------
At the top of every skill module (*.py under core/skills or skills) add:

    PERMISSIONS: set = {"web_scrape", "obsidian_read"}   # whatever is needed

    def run(event: dict) -> dict:
        # Main entry point. event contains any arguments passed from the
        # caller. Return a JSON-serialisable dict.

    Alternatively, a function named handler(event) will also be picked up.

The runner looks for run first, then handler.
"""

import importlib.util
import json
import os
import sys
from typing import Any, Dict, List, Optional


def _import_skill(skill_name: str, skill_path: Optional[str] = None):
    """Import the skill module and return the module object.

    Priority:
    1. A concrete file path supplied by the parent (handles skills that live
       outside the top-level ``skills`` package, e.g. test temp directories).
    2. ``skills.<skill_name>`` from the top-level ``skills`` package.
    """
    try:
        if skill_path and os.path.exists(skill_path):
            spec = importlib.util.spec_from_file_location(skill_name, skill_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod

        import skills  # noqa: F81  (re-import if already loaded)

        mod = getattr(skills, skill_name, None)
        if mod is None:
            __import__(f"skills.{skill_name}")
            mod = sys.modules.get(f"skills.{skill_name}")
        return mod
    except Exception as exc:  # pragma: no cover
        print(json.dumps({"error": f"Failed to import skill module: {exc}"}), file=sys.stderr)
        sys.exit(1)


def main() -> None:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "No skill name provided"}), file=sys.stderr)
        sys.exit(1)

    skill_name = sys.argv[1]

    # Optional third argument: the concrete file path of the skill module
    # (used when the skill does not live inside the top-level skills package).
    skill_path: Optional[str] = sys.argv[3] if len(sys.argv) > 3 else None

    # Read the permission list that the parent sandbox sent via stdin.
    try:
        stdin_data = sys.stdin.read()
        requested_perms: List[str] = json.loads(stdin_data) if stdin_data.strip() else []
    except Exception as exc:
        print(json.dumps({"error": f"Failed to read permissions from stdin: {exc}"}), file=sys.stderr)
        sys.exit(1)

    # Import the skill module.
    mod = _import_skill(skill_name, skill_path)
    if mod is None:
        print(json.dumps({"error": f"Skill module '{skill_name}' not found"}), file=sys.stderr)
        sys.exit(1)

    # Resolve the permission set declared by the skill.
    skill_perms: set = getattr(mod, "PERMISSIONS", set())
    # Intersect: only allow if every requested perm is in skill's declared set
    valid = [p for p in requested_perms if p in skill_perms]
    missing = [p for p in requested_perms if p not in skill_perms]
    if missing:
        print(json.dumps({"error": f"Missing required permissions: {missing}"}), file=sys.stderr)
        sys.exit(1)

    # Grab the event args that were sent on the command line (the kwargs dict).
    raw_kwargs: Dict[str, Any] = {}
    if len(sys.argv) > 2:
        try:
            raw_kwargs = json.loads(sys.argv[2])
        except json.JSONDecodeError:
            raw_kwargs = {}

    # Locate the entry-point function.
    handler: Optional[callable] = getattr(mod, "run", None)
    if handler is None:
        handler = getattr(mod, "handler", None)

    if handler is None:
        print(json.dumps({"error": f"Skill '{skill_name}' has no 'run' or 'handler' function"}), file=sys.stderr)
        sys.exit(1)

    # Execute the handler. Skills follow the run(**kwargs) convention.
    try:
        result: Any = handler(**raw_kwargs)
        # Ensure result is JSON-serialisable; if not, stringify.
        payload = json.dumps(result)
    except Exception as exc:  # pragma: no cover
        payload = json.dumps({"error": f"Handler raised {exc}"})

    # Output JSON to stdout (parent process reads this).
    print(payload, flush=True)


if __name__ == "__main__":
    main()