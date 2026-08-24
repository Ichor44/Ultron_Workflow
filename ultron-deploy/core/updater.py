"""Git-based self-updater for Ultron deployments.

Lets a running Ultron instance check the cloud repo (GitHub) for newer
versions and update itself with one click from the web UI.

Configuration (environment variables):
    ULTRON_REPO_URL       Git remote to pull updates from (required to enable).
                          e.g. https://github.com/youruser/ultron.git
    ULTRON_UPDATE_BRANCH  Branch to track (default: main)
    ULTRON_AUTO_RESTART   "1" -> exit process after applying an update so the
                          container supervisor restarts it with new code
                          (default: "1" inside Docker, else "0").

Flow:
    GET  /api/update/check  -> compare local HEAD vs origin/<branch>
    POST /api/update/apply  -> git reset --hard, pip install if requirements
                               changed, then schedule process restart.

Runtime data (data/, logs/, output/, .env) is untracked by design, so updates
never touch user keys or generated files.
"""

import os
import subprocess
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_FILE = os.path.join(ROOT, "VERSION")

REPO_URL = os.environ.get("ULTRON_REPO_URL", "").strip()
BRANCH = os.environ.get("ULTRON_UPDATE_BRANCH", "main").strip() or "main"

_in_docker = os.path.exists("/.dockerenv")
AUTO_RESTART = os.environ.get(
    "ULTRON_AUTO_RESTART", "1" if _in_docker else "0"
) == "1"

_apply_lock = threading.Lock()


class UpdateError(Exception):
    pass


def _run(args, timeout=120):
    """Run a command in the app root and return (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            args,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    except subprocess.TimeoutExpired:
        return 124, "", "command timed out after %ss" % timeout


def _git(args, timeout=120):
    # safe.directory=* avoids "dubious ownership" failures inside containers
    # where uid mapping can differ between image build and runtime volumes.
    code, out, err = _run(
        ["git", "-c", "safe.directory=*"] + args, timeout=timeout)
    if code != 0:
        raise UpdateError("git %s failed: %s" % (" ".join(args), err or out))
    return out


def is_configured():
    """True when self-update can actually run here."""
    return bool(REPO_URL) and os.path.isdir(os.path.join(ROOT, ".git"))


def current_version():
    try:
        with open(VERSION_FILE, "r") as fh:
            return fh.read().strip()
    except OSError:
        return "unknown"


def _head():
    return _git(["rev-parse", "--short", "HEAD"])


def _ensure_remote():
    remotes = _git(["remote"])
    if "origin" not in remotes.split():
        _git(["remote", "add", "origin", REPO_URL])
    else:
        url = _git(["remote", "get-url", "origin"])
        if url != REPO_URL:
            _git(["remote", "set-url", "origin", REPO_URL])


def _fetch():
    # Neutralize any local credential prompts; fail fast instead of hanging.
    _git([
        "-c", "credential.interactive=false",
        "-c", "core.askPass=",
        "fetch", "--prune", "origin", BRANCH,
    ], timeout=90)


def _remote_ref():
    return _git(["rev-parse", "--short", "origin/%s" % BRANCH])


def _rev_version(ref):
    code, out, _ = _run(["git", "show", "%s:VERSION" % ref])
    return out.strip() if code == 0 else "unknown"


def check():
    """Compare local checkout against the cloud. Never raises."""
    info = {
        "ok": True,
        "configured": is_configured(),
        "branch": BRANCH,
        "current_version": current_version(),
        "current_commit": None,
        "latest_version": None,
        "latest_commit": None,
        "behind": 0,
        "update_available": False,
        "auto_restart": AUTO_RESTART,
    }
    if not info["configured"]:
        info["error"] = (
            "Self-update not configured. Set ULTRON_REPO_URL and deploy "
            "from a git clone."
        )
        return info
    try:
        _ensure_remote()
        _fetch()
        info["current_commit"] = _head()
        info["latest_commit"] = _remote_ref()
        info["latest_version"] = _rev_version("origin/%s" % BRANCH)
        behind = _git([
            "rev-list", "--count",
            "HEAD..origin/%s" % BRANCH,
        ])
        info["behind"] = int(behind) if behind else 0
        info["update_available"] = info["behind"] > 0
    except UpdateError as exc:
        info["ok"] = False
        info["error"] = str(exc)
    except Exception as exc:  # defensive: never 500 the UI
        info["ok"] = False
        info["error"] = "Update check failed: %s" % exc
    return info


def _requirements_changed(old_ref):
    code, old_reqs, _ = _run(
        ["git", "show", "%s:requirements.txt" % old_ref])
    if code != 0:
        return True
    try:
        with open(os.path.join(ROOT, "requirements.txt")) as fh:
            return fh.read() != old_reqs
    except OSError:
        return True


def _pip_install():
    pip = [
        sys.executable,
        "-m", "pip", "install", "--user", "--no-cache-dir",
        "--quiet", "-r", "requirements.txt",
    ]
    code, _, err = _run(pip, timeout=600)
    if code != 0:
        raise UpdateError("pip install failed: %s" % err[:500])


def _schedule_restart():
    if not AUTO_RESTART:
        return False

    def _die():
        import time
        time.sleep(2.5)
        os._exit(0)

    threading.Thread(target=_die, daemon=True).start()
    return True


def apply_update():
    """Pull the latest code and stage a restart. Returns a result dict."""
    if not is_configured():
        return {
            "ok": False,
            "error": "Self-update not configured (ULTRON_REPO_URL missing).",
        }
    if not _apply_lock.acquire(blocking=False):
        return {"ok": False, "error": "An update is already in progress."}
    try:
        result = check()
        if not result.get("ok"):
            return result
        if not result.get("update_available"):
            return {
                "ok": True,
                "updated": False,
                "message": "Already up to date (%s)." % result["current_version"],
                "version": result["current_version"],
                "restarting": False,
            }

        old_head = result["current_commit"]
        reqs_changed = _requirements_changed("HEAD")
        _git(["reset", "--hard", "origin/%s" % BRANCH], timeout=60)
        # Never touch runtime/user files that live outside git tracking.
        _git(["clean", "-fd",
              "--exclude=data", "--exclude=logs", "--exclude=output",
              "--exclude=.env", "--exclude=.gitconfig"], timeout=60)

        deps_note = "skipped"
        if reqs_changed:
            _pip_install()
            deps_note = "reinstalled"

        restarting = _schedule_restart()
        new_version = current_version()
        return {
            "ok": True,
            "updated": True,
            "old_commit": old_head,
            "new_commit": result["latest_commit"],
            "version": new_version,
            "dependencies": deps_note,
            "restarting": restarting,
            "message": (
                "Updated to %s. Restarting..." % new_version
                if restarting else
                "Updated to %s. Restart Ultron to load the new version."
                % new_version
            ),
        }
    except UpdateError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": "Update failed: %s" % exc}
    finally:
        _apply_lock.release()
