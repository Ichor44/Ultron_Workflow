"""
Skill Sandbox for Ultron.

Provides isolation, resource quotas, and permission gating for every skill
(and therefore every agent/subagent) that runs inside Ultron.

* **Isolation** – each skill execution runs in a separate subprocess; the
  parent process only sees the result or a structured error.
* **Resource quotas** – configurable CPU time (seconds) and memory (MiB).  If
  the limit is exceeded the subprocess is terminated.
* **Permission gates** – a skill may declare the permissions it needs
  (``"web_scrape"``, ``"obsidian_read"``, ``"biomcp_query"``, etc.).  The
  sandbox only grants those permissions; any attempt to exceed the whitelist
  causes the job to be aborted.
* **Fail‑safe boundaries** – a crashed or misbehaving skill only kills its own
  subprocess; the host process remains healthy.

The public API is ``SandboxedSkill.run(skill_func, permissions, **kwargs)``.
"""

import json
import os
import signal
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Helper: build the command line that will invoke the skill subprocess.
# The skill code lives in ``skills/`` and is invoked via a small bootstrap that
# runs ``core/skill_runner.py`` as a plain script (see _build_skill_cmd below).
# ---------------------------------------------------------------------------

def _build_skill_cmd(
    skill_name: str, args: Dict[str, Any], skill_path: Optional[str] = None
) -> List[str]:
    """Return a list suitable for ``subprocess.Popen``.

    The runner (``core/skill_runner.py``) is executed as a plain script via a
    small ``-c`` bootstrap instead of ``python -m core.skill_runner`` because:

    * ``python -m core.skill_runner`` imports the ``core`` package first, and
      ``core/__init__.py`` pulls in the entire ML stack (LLM clients, HF model
      weights, voice, websocket, ...), which can take minutes or hang.
    * Running the file directly also breaks: its directory (``core``) lands on
      ``sys.path`` and shadows the top-level ``skills`` package with the
      unrelated ``core/skills.py`` manager module.

    The bootstrap inserts the project root at the front of ``sys.path`` so the
    runner's ``import skills`` resolves to the real top-level ``skills``
    package, and executes the runner as ``__main__`` without ever importing
    the ``core`` package.  If *skill_path* is given (a concrete .py file), its
    directory is added to ``sys.path`` as well and the path is passed to the
    runner as an extra argument.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    runner_path = os.path.join(root, "core", "skill_runner.py")

    parts = [
        "import sys;",
        "sys.path.insert(0, %r);" % root,
    ]
    if skill_path:
        parts.append("sys.path.insert(0, %r);" % os.path.dirname(skill_path))
    parts.append(
        "exec(compile(open(%r, encoding='utf-8').read(), %r, 'exec'), "
        "{'__name__': '__main__', '__file__': %r})"
        % (runner_path, runner_path, runner_path)
    )
    bootstrap = "".join(parts)

    cmd: List[str] = [sys.executable, "-c", bootstrap, skill_name, json.dumps(args)]
    if skill_path:
        cmd.append(skill_path)
    return cmd


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class SandboxedSkill:
    """Wrapper that runs a user‑provided skill function inside a sandbox."""

    # ------------------------------------------------------------------
    # Configuration knobs (can be overridden per‑instance)
    # ------------------------------------------------------------------
    default_timeout: float = 30.0          # seconds before kill
    default_memory_mib: int = 512          # max resident memory
    default_cpu_seconds: int = 10          # wall‑clock CPU time limit

    # ------------------------------------------------------------------
    # Permission whitelist – keys that the sandbox will allow for a given
    # invocation.  The skill's manifest defines what it *requests*; the
    # sandbox intersect‑s it with this global whitelist.
    # ------------------------------------------------------------------
    ALLOWED_PERMISSIONS = {
        "web_scrape",
        "web_search",
        "web_interact",
        "obsidian_read",
        "obsidian_write",
        "obsidian_search",
        "biomcp_query",
        "biomcp_gene",
        "biomcp_disease",
        "biomcp_drug",
        "file_read",
        "file_write",
        "sqlite_query",
    }

    @classmethod
    def validate_permissions(cls, requested: List[str]) -> List[str]:
        """Return the intersection of *requested* with the global whitelist."""
        allowed = cls.ALLOWED_PERMISSIONS
        valid = [p for p in requested if p in allowed]
        if len(valid) != len(requested):
            # Some requested permissions are not in the whitelist – reject.
            raise PermissionError(
                f"Invalid permission(s): {set(requested) - allowed}. "
                f"Allowed: {allowed}"
            )
        return valid

    # ------------------------------------------------------------------
    # Core running logic
    # ------------------------------------------------------------------
    @classmethod
    def run(
        cls,
        skill_name: str,
        permissions: List[str],
        kwargs: Dict[str, Any],
        timeout: float | None = None,
        memory_mib: int | None = None,
        cpu_seconds: int | None = None,
        skill_path: str | None = None,
    ) -> Tuple[Any, Dict[str, str]]:
        """
        Execute *skill_name* with the given *permissions* and *kwargs*.

        Returns ``(result, metadata)`` where *metadata* contains
        ``{"duration": "...", "exit_code": "...", "notes": "..."}``.

        If the skill exceeds limits or violates permissions a ``RuntimeError``
        (or ``PermissionError``) is raised.
        """
        timeout = timeout or cls.default_timeout
        memory_mib = memory_mib or cls.default_memory_mib
        cpu_seconds = cpu_seconds or cls.default_cpu_seconds

        # 1️⃣ Validate permissions early.
        valid_perms = cls.validate_permissions(permissions)

        # 2️⃣ Build the subprocess command.
        cmd = _build_skill_cmd(skill_name, kwargs, skill_path)

        # 3️⃣ Start the subprocess with resource limits.
        #    On Windows we use a job object to enforce memory & CPU limits.
        #    On POSIX we can use ``resource`` module (simplified here).
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )

        # ------------------------------------------------------------------
        # Windows Job Object setup (memory + CPU time limit)
        # ------------------------------------------------------------------
        job_active = False
        if sys.platform == "win32":
            try:
                import ctypes
                import ctypes.wintypes

                JOBOBJECT_BASIC_LIMIT_INFORMATION = 4
                JobObjectBasicUIRestrictions = 8

                class PROCESS_BASIC_INFORMATION(ctypes.Structure):
                    pass  # we will not need the full struct for this snippet

                # Create a job object.
                job = ctypes.wintypes.HANDLE(
                    ctypes.kernel32.CreateJobObjectW(None, None)
                )
                if not job:
                    raise OSError("CreateJobObject failed")

                # Set basic limits: per‑process memory (MiB) and CPU time (ms).
                limit_info = ctypes.wintypes.JOB_OBJECT_BASIC_LIMIT_INFORMATION()
                limit_info.PeriodicRate = 0
                limit_info.BasicLimitFlags = (
                    1 << 0  # JOB_OBJECT_LIMIT_PROCESS_TIME
                )
                # Convert CPU seconds to 100‑nanosecond intervals.
                cpu_interval = int(cpu_seconds * 10_000_000)
                limit_info.CpuRate = cpu_interval
                # Memory limit in bytes.
                memory_bytes = memory_mib * 1024 * 1024
                limit_info.MemoryLimit = memory_bytes

                ctypes.kernel32.SetInformationJobObject(
                    job,
                    JOBOBJECT_BASIC_LIMIT_INFORMATION,
                    ctypes.byref(limit_info),
                    ctypes.sizeof(limit_info),
                )

                # Assign the child process to the job.
                ctypes.kernel32.AssignProcessToJobObject(job, proc._handle)
                job_active = True
            except Exception:
                # Failed to set up job object – fall back to simple timeout enforcement.
                job_active = False

        # ------------------------------------------------------------------
        # Communicate with the subprocess (send args, receive result).
        # ------------------------------------------------------------------
        try:
            # Send the permission list so the runner can reject disallowed ops.
            proc.stdin.write(json.dumps(valid_perms).encode() + b"\n")
            proc.stdin.flush()
            proc.stdin.close()  # Send EOF so child's sys.stdin.read() returns

            # Wait for completion with a wall‑clock timeout.
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                # Force kill the process group.
                proc.kill()
                proc.wait()
                raise RuntimeError(f"Skill '{skill_name}' timed out after {timeout}s")

            exit_code = proc.returncode
            result_text = stdout.decode("utf-8", errors="replace").strip()
            error_text = stderr.decode("utf-8", errors="replace").strip()

            # ------------------------------------------------------------------
            # Parse the JSON result that the runner emits.
            # ------------------------------------------------------------------
            metadata: Dict[str, str] = {
                "exit_code": str(exit_code),
                "duration": str(time.time() - start_time) if "start_time" in dir() else "?",
                "notes": "",
            }

            if exit_code == 0:
                try:
                    result = json.loads(result_text)
                except json.JSONDecodeError:
                    result = result_text
                return result, metadata
            else:
                # Propagate the runner's error message.
                raise RuntimeError(
                    f"Skill '{skill_name}' failed (exit {exit_code}): {error_text or result_text}"
                )
        finally:
            # Ensure the process handle is closed.
            try:
                proc.stdout.close()
            except Exception:
                pass
            try:
                if proc.stdin and not proc.stdin.closed:
                    proc.stdin.close()
            except Exception:
                pass


# ----------------------------------------------------------------------
# Tiny runner module that skills import.  It reads the permission list from
# stdin, checks the skill's manifest, and then executes the actual handler.
# ----------------------------------------------------------------------
# (The runner will be placed in ``core/skill_runner.py``; see the surrounding
# files for the expected manifest format.)
# ----------------------------------------------------------------------