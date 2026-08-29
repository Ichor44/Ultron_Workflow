"""Optimized web server for Ultron.

Key optimizations:
- Integrated with core.cache CacheManager for unified caching
- Reduced cache miss patterns
- Warm cache on startup
- Session-safe agent reuse
"""

import os
import sys
import time
import threading
import hashlib
import io
import asyncio
import uuid
from functools import wraps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from flask import Flask, request, jsonify, send_from_directory, send_file, make_response
from core import engine, proposals, memory, file_output, voice, updater
from core.cache import get_cache_manager, TTLCache

# Flask-Caching for server-side response caching
try:
    from flask_caching import Cache
    CACHING_AVAILABLE = True
except ImportError:
    CACHING_AVAILABLE = False
    Cache = None

ROOT = os.path.dirname(os.path.abspath(__file__))
# Ultron Workflow is now the standard UI served at root (/)
WEBUI = os.path.join(ROOT, "ultron-workflow", "dist")
# Legacy /app route kept for backwards compatibility
DIST = os.path.join(ROOT, "ultron-workflow", "dist")
SKILLS_DIR = os.path.join(ROOT, "skills")
# Ensure skills directory is in path for imports (insert once, not per-request)
if SKILLS_DIR not in sys.path:
    sys.path.insert(0, SKILLS_DIR)

# Disable Flask's built-in static file serving to use custom caching
app = Flask(__name__, static_folder=None, static_url_path="")


# =============================================================================
# CROSS-SITE REQUEST PROTECTION (CSRF hardening)
# =============================================================================
# The API intentionally ships without cookie auth (localhost tooling server),
# but a malicious web page visited by the operator could still drive-by POST
# to http://127.0.0.1:5000 (e.g. /api/terminate). Browsers ALWAYS attach an
# Origin header on cross-origin requests, so rejecting state-changing
# requests whose Origin/Referer points at another host closes that hole with
# zero impact on curl / same-origin UI usage.
@app.before_request
def _reject_cross_site_writes():
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return None
    host = (request.headers.get("Host") or "").split(":")[0].lower()
    for header in ("Origin", "Referer"):
        raw = request.headers.get(header)
        if not raw:
            continue
        origin_host = raw.split("://", 1)[-1].split(":")[0].split("/")[0].lower()
        if origin_host and origin_host != host:
            return jsonify({"error": "cross-site request rejected"}), 403
        break
    return None

# =============================================================================
# CACHING CONFIGURATION
# =============================================================================
def _check_redis_available():
    """Check if Redis is actually reachable."""
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    try:
        import redis
        client = redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1)
        client.ping()
        return True
    except Exception:
        return False

USE_REDIS = bool(os.environ.get("REDIS_URL")) and _check_redis_available()

CACHE_CONFIG = {
    "CACHE_TYPE": "redis" if USE_REDIS else "simple",
    "CACHE_REDIS_URL": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
    "CACHE_DEFAULT_TIMEOUT": 300,
    "CACHE_KEY_PREFIX": "agent:cache:",
    "CACHE_IGNORE_ERRORS": True,
}
if CACHING_AVAILABLE:
    cache = Cache(app, config=CACHE_CONFIG)
else:
    cache = None

CACHE_VERSION = os.environ.get("CACHE_VERSION", "1")
_cache_stats_lock = threading.Lock()
cache_stats = {"hits": 0, "misses": 0, "errors": 0}


def _inc_cache_stat(key: str):
    """Thread-safe increment of cache stat."""
    with _cache_stats_lock:
        cache_stats[key] += 1


def _get_cache_stats() -> dict:
    """Thread-safe get of cache stats snapshot."""
    with _cache_stats_lock:
        return dict(cache_stats)

# =============================================================================
# CACHE INVALIDATION CALLBACKS
# =============================================================================
def _invalidate(pattern, core_ns=None):
    """Invalidate a cache pattern in Flask-Caching and optionally in core cache."""
    invalidate_cache_pattern(pattern)
    if core_ns:
        get_cache_manager().invalidate(core_ns)

# Register callbacks
try:
    from core import skills, recipes
    import config as config_module
    skills.register_on_change(lambda: _invalidate("skills", "skills"))
    recipes.register_on_change(lambda: _invalidate("recipes", "recipes"))
    config_module.register_on_change(lambda: _invalidate("models"))
    config_module.register_on_change(lambda: _invalidate("voice"))
except Exception:
    pass

_session_lock = threading.RLock()

session = {
    "agent": None,
    "cfg": None,
    "busy": threading.Event(),
    "state": "idle",
    "pid": None,
    "event": threading.Event(),
    "answer": None,
    "error": None,
    "messages": [{"role": "assistant", "text": "Ultron online. Try not to waste my time, sir."}],
    "mock": not bool(config.load_config()["provider"]),
}


def get_agent():
    with _session_lock:
        if session["agent"] is None:
            cfg = config.load_config()
            if not cfg["provider"]:
                cfg["provider"] = "mock"
                session["mock"] = True
            session["cfg"] = cfg
            ag = engine.Agent(cfg, auto_approve=False)
            ag.approver = make_approver()
            session["agent"] = ag
        return session["agent"]


def make_approver():
    def approver(p):
        with _session_lock:
            session["pid"] = p.id
            session["state"] = "awaiting"
            session["event"].clear()
        session["event"].wait()
        updated = proposals.get_proposal(p.id)
        if updated is None:
            return "Proposal %s no longer exists." % p.id
        if updated.status == "applied":
            return "Proposal %s approved and applied." % p.id
        if updated.status == "rejected":
            return "Proposal %s was rejected." % p.id
        return "Proposal %s was updated." % p.id
    return approver


def run_turn(message):
    try:
        ag = get_agent()
        with _session_lock:
            session["messages"].append({"role": "user", "text": message})
            session["state"] = "thinking"
        answer = ag.continue_chat(message)
        with _session_lock:
            session["answer"] = answer
            session["messages"].append({"role": "assistant", "text": answer})
            session["state"] = "done"
    except Exception as e:
        with _session_lock:
            session["error"] = str(e)
            session["state"] = "error"
    finally:
        with _session_lock:
            session["pid"] = None
            session["busy"].clear()


# =============================================================================
# CACHE HELPERS
# =============================================================================
def make_cache_key(*args, **kwargs):
    lang = request.headers.get("Accept-Language", "en")[:5] if request else "en"
    user_id = request.headers.get("X-User-ID", "anon") if request else "anon"
    parts = [CACHE_VERSION, lang, user_id] + [str(a) for a in args] + [f"{k}={v}" for k, v in sorted(kwargs.items())]
    key = "|".join(parts)
    if len(key) > 200:
        key = hashlib.sha256(key.encode()).hexdigest()[:32]
    return key


def cached_response(timeout=300, key_prefix="view", vary_on=None):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not CACHING_AVAILABLE or cache is None:
                return f(*args, **kwargs)
            
            vary_parts = [key_prefix]
            if vary_on:
                for attr in vary_on:
                    if attr == "Accept-Language":
                        vary_parts.append(request.headers.get("Accept-Language", "en")[:5])
                    elif attr == "X-User-ID":
                        vary_parts.append(request.headers.get("X-User-ID", "anon"))
                    elif attr == "args":
                        vary_parts.append(str(sorted(request.args.items())))
                    else:
                        vary_parts.append(str(getattr(request, attr, "")))
            
            cache_key = "agent:cache:" + "|".join(vary_parts)
            if len(cache_key) > 200:
                cache_key = cache_key[:100] + ":" + hashlib.sha256(cache_key.encode()).hexdigest()[:16]
            
            try:
                cached = cache.get(cache_key)
                if cached is not None:
                    _inc_cache_stat("hits")
                    response = make_response(cached[0], cached[1])
                    response.headers["X-Cache"] = "HIT"
                    response.headers["X-Cache-Key"] = cache_key
                    return response
                _inc_cache_stat("misses")
            except Exception:
                _inc_cache_stat("errors")
                pass

            response = f(*args, **kwargs)

            if hasattr(response, "status_code") and response.status_code == 200:
                try:
                    cache.set(cache_key, (response.get_data(), response.status_code), timeout=timeout)
                except Exception:
                    _inc_cache_stat("errors")
            
            response.headers["X-Cache"] = "MISS"
            response.headers["X-Cache-Key"] = cache_key
            return response
        return wrapped
    return decorator


def invalidate_cache_pattern(pattern):
    if not CACHING_AVAILABLE or cache is None:
        return
    try:
        if hasattr(cache.cache, "clear"):
            cache.cache.clear()
        elif hasattr(cache.cache, "_cache"):
            cache.cache._cache.clear()
    except Exception:
        pass


def add_cache_headers(response, max_age=300, stale_while_revalidate=60, stale_if_error=86400):
    if response.status_code == 200:
        response.headers["Cache-Control"] = (
            f"public, max-age={max_age}, stale-while-revalidate={stale_while_revalidate}, "
            f"stale-if-error={stale_if_error}"
        )
        response.headers["Vary"] = "Accept-Language, X-User-ID"
    return response


# =============================================================================
# ROUTES
# =============================================================================
@app.route("/")
@cached_response(timeout=3600, key_prefix="index", vary_on=["Accept-Language"])
def index():
    """Serve Ultron Workflow SPA at root — the new standard UI."""
    if not os.path.isfile(os.path.join(DIST, "index.html")):
        return jsonify({"error": "ultron-workflow/dist not built. Run: cd ultron-workflow && npm run build"}), 404
    # HTML entry point references content-hashed assets -> always revalidate,
    # so a rebuild is picked up on the next load without stale bundles.
    response = send_from_directory(DIST, "index.html")
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.route("/app")
@app.route("/app/<path:path>")
def app_frontend(path=""):
    """Legacy /app route — alias to root for backwards compatibility."""
    return index() if not path else serve_workflow_asset(path)


def serve_workflow_asset(path: str):
    """Serve workflow assets (JS, CSS, images) from DIST."""
    if not os.path.isfile(os.path.join(DIST, "index.html")):
        return jsonify({"error": "ultron-workflow/dist not built. Run: cd ultron-workflow && npm run build"}), 404
    full = os.path.realpath(os.path.join(DIST, path))
    dist_real = os.path.realpath(DIST)
    if not full.startswith(dist_real + os.sep) and full != dist_real:
        return send_from_directory(DIST, "index.html")
    if os.path.isfile(full):
        response = send_from_directory(DIST, path)
        # Vite emits content-hashed filenames (index-<hash>.js) -> safe to cache forever.
        if path.startswith("assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response
    # SPA fallback
    response = send_from_directory(DIST, "index.html")
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.route("/assets/<path:path>")
def app_assets(path):
    """Serve Vite built assets for merged /app (so index.html's /assets/... works)."""
    if os.path.isfile(os.path.join(DIST, "assets", path)):
        response = send_from_directory(os.path.join(DIST, "assets"), path)
    elif os.path.isfile(os.path.join(DIST, path)):
        response = send_from_directory(DIST, path)
    else:
        return jsonify({"error": "asset not found"}), 404
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


@app.route("/api/state")
def api_state():
    with _session_lock:
        data = {
            "state": session["state"],
            "mock": session["mock"],
            "messages": list(session["messages"]),  # Return a copy to avoid race conditions
            "answer": session["answer"],
            "error": session["error"],
        }
        ag = session.get("agent")
        if ag:
            # Access token_usage atomically to avoid TOCTOU race
            usage = ag.token_usage
            usage_copy = list(usage) if usage else []
            data["token_usage"] = usage_copy
            total = sum(t.get("total_tokens", 0) for t in usage_copy)
            data["total_tokens"] = total
        if session["state"] == "awaiting" and session["pid"]:
            p = proposals.get_proposal(session["pid"])
            if p:
                data["proposal"] = p.to_dict()
                data["diff"] = p.diff()
    return jsonify(data)


@app.route("/api/chat", methods=["POST"])
def api_chat():
    with _session_lock:
        if session["busy"].is_set():
            return jsonify({"error": "Agent is busy. Wait for the current task to finish."}), 429
        body = request.get_json(silent=True) or {}
        message = (body.get("message") or "").strip()
        if not message:
            return jsonify({"error": "Empty message."}), 400
        session["busy"].set()
        session["answer"] = None
        session["error"] = None
        session["state"] = "thinking"
    threading.Thread(target=run_turn, args=(message,), daemon=True).start()
    return jsonify({"state": "thinking"})


@app.route("/api/review/<pid>", methods=["POST"])
def api_review(pid):
    with _session_lock:
        if session["state"] != "awaiting" or session["pid"] != pid:
            return jsonify({"error": "No proposal awaiting review with that id."}), 409
    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    p = proposals.get_proposal(pid)
    if p is None:
        return jsonify({"error": "Unknown proposal."}), 404
    if decision == "approve":
        p.write_file()
        p.status = "applied"
    elif decision == "reject":
        p.status = "rejected"
    elif decision == "edit":
        code = body.get("code")
        if code is None:
            return jsonify({"error": "edit requires code"}), 400
        p.new_content = code
        p.write_file()
        p.status = "applied"
    else:
        return jsonify({"error": "bad decision"}), 400
    proposals.update_proposal(p)
    with _session_lock:
        session["event"].set()
    return jsonify({"ok": True})


@app.route("/api/models")
@cached_response(timeout=300, key_prefix="models", vary_on=["Accept-Language"])
def api_models():
    cfg = config.load_config()
    models = []
    provider = cfg.get("provider", "")
    if provider == "mock":
        return jsonify({"models": models, "mock": True})
    # ollama/lmstudio are normalized into custom_* keys by config.load_config()
    model_key = ("custom_model" if provider in ("ollama", "lmstudio", "custom")
                 else provider + "_model" if provider else None)
    model_name = cfg.get(model_key) if model_key else None
    if provider and model_name:
        models.append({
            "id": model_name,
            "name": model_name,
            "provider": provider,
            "active": True,
        })
    return jsonify({"models": models})


@app.route("/api/models", methods=["POST"])
def api_models_add():
    body = request.get_json(silent=True) or {}
    model_id = (body.get("id") or "").strip()
    name = (body.get("name") or model_id).strip()
    provider = (body.get("provider") or "openrouter").strip().lower()
    valid = ("openrouter", "openai", "anthropic", "ollama", "lmstudio")
    if not model_id:
        return jsonify({"error": "model id required"}), 400
    if provider not in valid:
        return jsonify({"error": "bad provider"}), 400
    updates = {
        "AGENT_LLM_PROVIDER": provider,
        _provider_model_key(provider): model_id,
    }
    config.save_env(updates)
    with _session_lock:
        session["agent"] = None
    invalidate_cache_pattern("models")
    return jsonify({"ok": True, "model": {"id": model_id, "name": name, "provider": provider}})


@app.route("/api/models/activate", methods=["POST"])
def api_models_activate():
    body = request.get_json(silent=True) or {}
    model_id = (body.get("model_id") or "").strip()
    if not model_id:
        return jsonify({"error": "model_id required"}), 400
    cfg = config.load_config()
    provider = cfg.get("provider", "openrouter")
    config.save_env({_provider_model_key(provider): model_id})
    with _session_lock:
        session["agent"] = None
    invalidate_cache_pattern("models")
    return jsonify({"ok": True, "model_id": model_id})


@app.route("/api/voice")
def api_voice_get():
    settings = voice.load_voice_settings()
    return jsonify(settings)


@app.route("/api/voice", methods=["POST"])
def api_voice_post():
    body = request.get_json(silent=True) or {}
    enabled = body.get("enabled")
    voice_engine = (body.get("engine") or "").strip().lower()
    name = (body.get("name") or "").strip()
    rate = body.get("rate")
    volume = body.get("volume")
    try:
        settings = voice.save_voice_settings(
            enabled=enabled if enabled is not None else None,
            engine=voice_engine if voice_engine else None,
            name=name,
            rate=rate if rate is not None else None,
            volume=volume if volume is not None else None,
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    invalidate_cache_pattern("voice")
    return jsonify({"ok": True, "settings": settings})


@app.route("/api/voice/voices")
@cached_response(timeout=3600, key_prefix="voice:voices", vary_on=["args", "Accept-Language"])
def api_voice_voices():
    voice_engine = (request.args.get("engine") or "").strip().lower() or None
    force = request.args.get("refresh") == "1"
    try:
        voices = voice.list_voices(engine=voice_engine, force_refresh=force)
    except Exception as e:
        return jsonify({"voices": [], "error": str(e)}), 200
    return jsonify({"voices": voices})


def _voice_params(body):
    """Extract common voice request parameters with validation."""
    rate = body.get("rate")
    volume = body.get("volume")
    # Validate rate and volume to prevent type errors
    try:
        rate = int(rate) if rate is not None else None
    except (ValueError, TypeError):
        rate = None
    try:
        volume = int(volume) if volume is not None else None
        if volume is not None:
            volume = max(0, min(100, volume))  # Clamp to valid range
    except (ValueError, TypeError):
        volume = None
    return {
        "text": (body.get("text") or "").strip(),
        "engine": (body.get("engine") or "edge").strip().lower(),
        "voice_name": (body.get("name") or "").strip() or None,
        "rate": rate,
        "volume": volume,
    }


@app.route("/api/voice/preview", methods=["POST"])
def api_voice_preview():
    p = _voice_params(request.get_json(silent=True) or {})
    text = p["text"] or "Hello sir, I am Ultron, at your service."
    try:
        voice.speak(text, engine=p["engine"], voice=p["voice_name"], rate=p["rate"], volume=p["volume"])
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 200


@app.route("/api/voice/speak", methods=["POST"])
def api_voice_speak():
    p = _voice_params(request.get_json(silent=True) or {})
    text = p["text"]
    if not text:
        return jsonify({"error": "no text"}), 400
    voice_name = p["voice_name"]
    speak_engine = p["engine"]
    rate = p["rate"]
    volume = p["volume"]

    try:
        import edge_tts
        if not voice_name:
            voice_name = "en-US-AndrewNeural"
        pct = max(-100, min(100, int(rate or 0) * 10))
        rate_str = "%+d%%" % pct
        # Map volume 0-100 to edge-tts range -100 to +100
        vol_pct = max(0, min(100, int(volume or 100)))
        vol_str = "%+d%%" % (vol_pct * 2 - 100)

        audio_buf = io.BytesIO()
        def _run_async():
            nonlocal audio_buf
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                async def _generate():
                    buf = io.BytesIO()
                    comm = edge_tts.Communicate(text, voice_name, rate=rate_str, volume=vol_str)
                    async for chunk in comm.stream():
                        if chunk["type"] == "audio":
                            buf.write(chunk["data"])
                    buf.seek(0)
                    return buf
                audio_buf = new_loop.run_until_complete(_generate())
            finally:
                new_loop.close()

        t = threading.Thread(target=_run_async, daemon=True)
        t.start()
        t.join(timeout=30)

        if audio_buf.getbuffer().nbytes > 100:
            audio_buf.seek(0)
            return send_file(
                audio_buf,
                mimetype="audio/mpeg",
                as_attachment=False,
                download_name="agent_speech.mp3",
            )
    except Exception as e:
        print("edge-tts failed, falling back to SAPI:", e)

    try:
        import tempfile
        import subprocess
        # Escape single quotes for PowerShell single-quoted strings by doubling them
        safe = text.replace("'", "''")
        # Use unique temp file to avoid concurrency conflicts
        tmp_wav = os.path.join(tempfile.gettempdir(), "agent_speech_sapi_%s.wav" % uuid.uuid4().hex[:8])
        voice_clause = '$s.SelectVoice("%s"); ' % voice_name.replace('"', "") if voice_name else ""
        ps = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "%s"
            "$s.Rate = %d; $s.Volume = %d; "
            "$s.SetOutputToWaveFile('%s'); "
            "$s.Speak('[xml] <speak version=\"1.0\">%s</speak>'); "
            "$s.Dispose();"
        ) % (voice_clause, int(rate or 0), int(volume or 100), tmp_wav.replace("'", "''"), safe)
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60,
        )
        if os.path.exists(tmp_wav) and os.path.getsize(tmp_wav) > 1000:
            try:
                return send_file(tmp_wav, mimetype="audio/wav", as_attachment=False)
            finally:
                # Clean up temp file after sending
                try:
                    os.remove(tmp_wav)
                except Exception:
                    pass
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"error": "no TTS engine available"}), 500


def _provider_model_key(provider):
    return {
        "openrouter": "OPENROUTER_MODEL",
        "openai": "OPENAI_MODEL",
        "anthropic": "ANTHROPIC_MODEL",
        "ollama": "OLLAMA_MODEL",
        "lmstudio": "LMSTUDIO_MODEL",
    }.get(provider, "OPENROUTER_MODEL")


@app.route("/api/skills")
@cached_response(timeout=300, key_prefix="skills", vary_on=["Accept-Language"])
def api_skills():
    from core import skills
    return jsonify(skills.list_skills())


@app.route("/api/skills/search")
@cached_response(timeout=60, key_prefix="skills:search", vary_on=["args", "Accept-Language"])
def api_skills_search():
    from core import skills
    query = request.args.get("q", "")
    try:
        top_k = int(request.args.get("top_k", 5))
        if top_k < 1:
            top_k = 5
    except (ValueError, TypeError):
        top_k = 5
    return jsonify(skills.search_skills(query, top_k))


@app.route("/api/skills/<name>/execute", methods=["POST"])
def api_skill_execute(name):
    from core import skills
    body = request.get_json(silent=True) or {}
    args_json = body.get("args_json", "{}")
    try:
        result = skills.execute_skill(name, _parse_args(args_json))
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"result": result})


def _parse_args(s):
    if not s:
        return {}
    try:
        return __import__("json").loads(s)
    except Exception:
        return {}


@app.route("/api/recipes")
@cached_response(timeout=300, key_prefix="recipes", vary_on=["Accept-Language"])
def api_recipes():
    from core import recipes
    return jsonify(recipes.list_recipes())


@app.route("/api/recipe/<name>", methods=["GET", "DELETE"])
def api_recipe_get_delete(name):
    from core import recipes
    if request.method == "DELETE":
        success = recipes.delete_recipe(name)
        invalidate_cache_pattern("recipes")
        return jsonify({"ok": success}), (200 if success else 404)
    text = recipes.read_recipe(name)
    if text is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"name": name, "markdown": text})


@app.route("/api/recipe", methods=["POST"])
def api_recipe_post():
    from core import recipes
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    markdown = body.get("markdown", "")
    if not name:
        return jsonify({"error": "name required"}), 400
    path = recipes.write_recipe(name, markdown)
    invalidate_cache_pattern("recipes")
    return jsonify({"ok": True, "path": path})


@app.route("/api/metrics")
def api_metrics():
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory().percent
        disk_path = "C:\\" if os.name == "nt" else "/"
        disk = psutil.disk_usage(disk_path).percent
        net = psutil.net_io_counters()
        uptime = int(time.time() - psutil.boot_time())
        return jsonify({
            "cpu_percent": cpu,
            "memory_percent": mem,
            "disk_percent": disk,
            "network_mbps": round((net.bytes_sent + net.bytes_recv) / 1024 / 1024, 2),
            "uptime": uptime,
        })
    except Exception:
        return jsonify({"cpu_percent": 0, "memory_percent": 0, "disk_percent": 0, "network_mbps": 0, "uptime": 0})


@app.route("/api/terminate", methods=["POST"])
def api_terminate():
    try:
        threading.Thread(target=lambda: (time.sleep(1), os._exit(0)), daemon=True).start()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


@app.route("/api/launch-terminal", methods=["POST"])
def api_launch_terminal():
    """Launch the terminal agent in a new cmd window."""
    try:
        import subprocess
        agent_path = os.path.join(ROOT, "agent.py")
        # Launch in a new terminal window
        subprocess.Popen(
            ["cmd", "/c", "start", "cmd", "/k", f'python "{agent_path}"'],
            cwd=ROOT,
            creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0,
        )
        return jsonify({"ok": True, "message": "Terminal launched"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/brief")
def api_brief():
    data = memory._load()
    notes = len(data.get("notes", {}))
    facts = len(data.get("facts", {}))
    reminders = len([r for r in data.get("reminders", []) if not r.get("done")])
    return jsonify({"notes": notes, "facts": facts, "reminders": reminders})


@app.route("/api/notify", methods=["POST"])
def api_notify():
    from core import notify
    due = memory.due_reminders()
    return jsonify({"shown": notify.notify_due_reminders(due)})


@app.route("/api/skills-sh/install", methods=["POST"])
def api_skills_sh_install():
    body = request.get_json(silent=True) or {}
    repo = body.get("repo")
    if not repo:
        return jsonify({"error": "repo required"}), 400
    invalidate_cache_pattern("skills")
    return jsonify({"ok": True, "repo": repo})


@app.route("/api/config", methods=["POST"])
def api_config_post():
    body = request.get_json(silent=True) or {}
    provider = (body.get("provider") or "").strip().lower()
    model = (body.get("model") or "").strip()
    key = body.get("api_key")
    valid = ("openrouter", "openai", "anthropic", "ollama", "lmstudio", "mock")
    if provider not in valid:
        return jsonify({"error": "bad provider"}), 400
    if provider != "mock" and not model:
        return jsonify({"error": "model is required"}), 400

    updates = {"AGENT_LLM_PROVIDER": provider}
    if provider != "mock":
        updates[_provider_model_key(provider)] = model
        key_env = {
            "openrouter": "OPENROUTER_API_KEY",
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "ollama": "OLLAMA_API_KEY",
            "lmstudio": "LMSTUDIO_API_KEY",
        }.get(provider)
        if key and key_env:
            updates[key_env] = key

    config.save_env(updates)
    with _session_lock:
        session["agent"] = None
        session["mock"] = (provider == "mock")
        session["state"] = "idle"
        session["error"] = None
        session["busy"].clear()
        session["event"].clear()
    invalidate_cache_pattern("models")
    invalidate_cache_pattern("voice")
    return jsonify({"ok": True})


# =============================================================================
# PROTEIN + DNA LAB ENDPOINTS (Unified BioLab)
# Covers: protein analysis, DNA conversion, structure prediction (Boltz-2),
#         design, structure fetching, natural language, proto-tools bridge
# =============================================================================

# Structured metadata for every Protein/DNA lab action — returned as JSON
_BIOLAB_ACTIONS = [
    # Analysis
    {"id": "analyze", "label": "Analyze Sequence", "category": "Analysis", "description": "Composition, MW, charge, categories, motifs", "inputs": ["sequence"], "output": "text report"},
    {"id": "analyze_with_biotite", "label": "Analyze (Biotite)", "category": "Analysis", "description": "Enhanced analysis via biotite (dipeptides, GRAVY)", "inputs": ["sequence"], "output": "text report"},
    {"id": "properties", "label": "Physicochemical Properties", "category": "Analysis", "description": "MW, pI, extinction, instability, aliphatic, GRAVY", "inputs": ["sequence"], "output": "text report"},
    {"id": "motifs", "label": "Motif Search", "category": "Analysis", "description": "Search common motifs or custom regex", "inputs": ["sequence", "motif?"], "output": "text report"},
    {"id": "align", "label": "Sequence Alignment", "category": "Sequence Ops", "description": "Needleman-Wunsch alignment + identity", "inputs": ["sequence1 / sequence + sequence2"], "output": "alignment"},
    {"id": "visualize", "label": "3D Viewer", "category": "Structure", "description": "Generate 3Dmol.js HTML viewer", "inputs": ["pdb_file or pdb_content", "style", "color"], "output": "html file path"},
    # Design
    {"id": "design", "label": "Design Suggestions", "category": "Design", "description": "Optimization for stability/expression/binding", "inputs": ["sequence", "goal"], "output": "suggestions"},
    {"id": "design_from_text", "label": "Design from Text (Evo2)", "category": "Design", "description": "Protein design from natural language via Evo2", "inputs": ["prompt"], "output": "designed sequences"},
    {"id": "design_from_proto_language", "label": "Design from Proto-Language", "category": "Design", "description": "ProteinMPNN / RFdiffusion / Evo2 via proto-language", "inputs": ["prompt"], "output": "designed sequences"},
    {"id": "proto_tools_bridge", "label": "Proto-Tools Bridge", "category": "Design", "description": "Predict / score / design / compare via proto-tools", "inputs": ["action=predict|score|design|compare", "sequence/pdb_file"], "output": "text"},
    # Structure / Boltz-2
    {"id": "fold", "label": "Fold (Boltz-2)", "category": "Structure", "description": "Predict 3D structure with Boltz-2", "inputs": ["sequence"], "output": "pdb + scores"},
    {"id": "dock", "label": "Protein-Ligand Docking", "category": "Structure", "description": "Boltz-2 protein-ligand + affinity (pIC50)", "inputs": ["protein_sequence/sequence", "ligand_smiles or ligand_ccd", "predict_affinity?"], "output": "scores + pdb"},
    # Structure fetch / search
    {"id": "download_structure", "label": "Download Structure", "category": "Structure Fetch", "description": "Download from RCSB PDB or AlphaFold DB", "inputs": ["identifier", "source=pdb|alphafold"], "output": "saved file + sequence"},
    {"id": "search_structure", "label": "Search Structures", "category": "Structure Fetch", "description": "RCSB PDB full-text search", "inputs": ["query", "limit?"], "output": "hits"},
    {"id": "research_topic", "label": "Research Topic", "category": "Research", "description": "Web search protein literature via Firecrawl", "inputs": ["topic"], "output": "search results"},
    # DNA / Sequence Ops (legacy protein_lab DNA helpers)
    {"id": "protein_to_dna", "label": "Protein → DNA", "category": "DNA Lab", "description": "Translate protein sequence to DNA codons", "inputs": ["protein_sequence"], "output": "dna sequence"},
    {"id": "dna_to_protein", "label": "DNA → Protein", "category": "DNA Lab", "description": "Translate DNA to protein (6-frame ORF scan)", "inputs": ["dna_sequence"], "output": "protein sequence"},
    {"id": "parse_fasta", "label": "Parse FASTA", "category": "Sequence Ops", "description": "Split FASTA content into headers + sequences", "inputs": ["content"], "output": "fasta entries"},
    {"id": "convert", "label": "Format Convert", "category": "Sequence Ops", "description": "Convert fasta <-> raw", "inputs": ["sequence", "from_format", "to_format"], "output": "converted sequence"},
    {"id": "clean_sequence", "label": "Clean Sequence", "category": "Sequence Ops", "description": "Strip whitespace / headers / invalid chars", "inputs": ["sequence"], "output": "cleaned string"},
    {"id": "natural_language", "label": "Natural Language", "category": "Natural Language", "description": "Parse 'Design a protein that binds ATP', 'Download structure of insulin', etc.", "inputs": ["prompt"], "output": "intent + execution"},
    {"id": "help", "label": "Help", "category": "Utilities", "description": "List all actions with human-readable help", "inputs": [], "output": "help text"},
]

# --- Evo2 / dna_lab action metadata (24 actions incl. v3) ---
_EVO2_ACTIONS = [
    {"id": "generate", "label": "Generate DNA (Evo2)", "category": "Evo2", "description": "Generate DNA via Evo2 NIM (autocomplete / de novo)", "inputs": ["sequence", "num_tokens", "temperature", "top_k", "enable_sampled_probs"], "output": "generated sequence"},
    {"id": "score", "label": "Score Variant (Evo2)", "category": "Evo2", "description": "Embedding-distance variant scoring (BRCA1-style zero-shot)", "inputs": ["reference_sequence", "variant_sequence", "layer/layer_name"], "output": "score report"},
    {"id": "embeddings", "label": "Genomic Embeddings (Evo2)", "category": "Evo2", "description": "Get Evo2 embeddings for downstream ML", "inputs": ["sequence", "layer_name/layer"], "output": "embeddings report"},
    {"id": "forward", "label": "Forward Pass (Evo2)", "category": "Evo2", "description": "Forward pass / logits & layer activations", "inputs": ["sequence", "layer_name/layer"], "output": "layer activations"},
    {"id": "analyze", "label": "Analyze DNA (Evo2)", "category": "Evo2", "description": "GC, k-mers, codons, validation (dna_lab)", "inputs": ["sequence", "k"], "output": "analysis report"},
    {"id": "reverse_complement", "label": "Reverse Complement", "category": "Sequence Ops", "description": "Watson-Crick reverse complement", "inputs": ["sequence"], "output": "reverse complement"},
    {"id": "complement", "label": "Complement", "category": "Sequence Ops", "description": "Watson-Crick complement (non-reversed)", "inputs": ["sequence"], "output": "complement"},
    {"id": "transcribe", "label": "Transcribe DNA→RNA", "category": "Sequence Ops", "description": "DNA to RNA transcription (T→U)", "inputs": ["sequence"], "output": "rna sequence"},
    {"id": "reverse_transcribe", "label": "Reverse Transcribe RNA→DNA", "category": "Sequence Ops", "description": "RNA to DNA reverse transcription (U→T)", "inputs": ["sequence"], "output": "dna sequence"},
    {"id": "orf_find", "label": "ORF Finder (6-frame)", "category": "Sequence Ops", "description": "6-frame ORF scan + best ORF", "inputs": ["sequence"], "output": "orfs + coords"},
    {"id": "codon_optimize", "label": "Codon Optimize", "category": "Sequence Ops", "description": "Codon optimize for organism (human/e_coli/yeast)", "inputs": ["sequence", "organism"], "output": "optimized dna"},
    {"id": "validate", "label": "Validate DNA", "category": "Sequence Ops", "description": "Validate sequence (invalid chars, GC, warnings)", "inputs": ["sequence"], "output": "validation report"},
    {"id": "gc_content", "label": "GC Content", "category": "Sequence Ops", "description": "Calculate GC% + interpretation", "inputs": ["sequence"], "output": "gc% report"},
    {"id": "batch_score", "label": "Batch Score Variants", "category": "Batch", "description": "Parallel variant scoring (ThreadPoolExecutor)", "inputs": ["reference_sequence", "variant_sequences[]", "layer"], "output": "batch report"},
    {"id": "batch_generate", "label": "Batch Generate", "category": "Batch", "description": "Parallel DNA generation", "inputs": ["sequences[]", "num_tokens", "temperature", "top_k"], "output": "batch report"},
    {"id": "batch_embeddings", "label": "Batch Embeddings", "category": "Batch", "description": "Parallel embeddings", "inputs": ["sequences[]", "layer_name"], "output": "batch report"},
    {"id": "batch_analyze", "label": "Batch Analyze", "category": "Batch", "description": "Parallel sequence analysis with aggregation", "inputs": ["sequences[]", "k"], "output": "batch report"},
    {"id": "fetch_and_analyze", "label": "Fetch & Analyze", "category": "Fetch", "description": "Fetch via sub-bots/NCBI then analyze", "inputs": ["query/url/identifier/accession", "k", "fetch_mode"], "output": "fetched + analysis"},
    {"id": "fetch_and_score", "label": "Fetch & Score", "category": "Fetch", "description": "Fetch reference via sub-bots/NCBI then score variants", "inputs": ["query/url/identifier/accession", "variant_sequence/variant_sequences", "reference_sequence?", "layer"], "output": "fetched + score"},
    # v3 integrated
    {"id": "primer_design", "label": "Primer Design", "category": "Sequence Ops", "description": "Design primers for targetRegion (primerLength, tmMethod)", "inputs": ["sequence", "primer_length", "target_region", "tm_method"], "output": "primers"},
    {"id": "crispr", "label": "CRISPR Guide Design", "category": "Sequence Ops", "description": "CRISPR guide design with PAM + guideLength", "inputs": ["sequence", "pam", "guide_length", "target_region"], "output": "guides"},
    {"id": "melting_temp", "label": "Melting Temperature", "category": "Sequence Ops", "description": "Calculate Tm (wallace | gc | nearest_neighbor)", "inputs": ["sequence", "tm_method/method"], "output": "tm report"},
    {"id": "dna_to_protein_integrated", "label": "DNA→Protein Integrated", "category": "DNA Lab", "description": "Integrated 6-frame + codon-aware translation", "inputs": ["dna_sequence/sequence"], "output": "protein"},
    {"id": "genome_pipeline", "label": "Genome Pipeline", "category": "Pipeline", "description": "End-to-end genome pipeline (analyze→orf→optimize)", "inputs": ["sequence", "target_region", "method", "organism"], "output": "pipeline report"},
    # v4 plasmid design & host management
    {"id": "design_plasmid", "label": "Design Plasmid", "category": "Plasmid Design", "description": "Design custom plasmid from protein sequence with codon optimization", "inputs": ["protein_sequence", "host"], "output": "plasmid design"},
    {"id": "plasmid_stats", "label": "Plasmid Statistics", "category": "Plasmid Design", "description": "Compute plasmid stats (GC%, Tm, MW, restriction sites, copy number)", "inputs": ["sequence", "host"], "output": "stats report"},
    {"id": "set_host", "label": "Set Host Organism", "category": "Plasmid Design", "description": "Set default host organism for plasmid operations (e.coli/human/yeast)", "inputs": ["organism"], "output": "confirmation"},
    {"id": "get_host", "label": "Get Host Organism", "category": "Plasmid Design", "description": "Get current default host organism", "inputs": [], "output": "host info"},
]

# Dispatch sets — exact per spec (incl v3 + v4 plasmid design)
DNA_EVO2_ACTIONS = {"generate","score","embeddings","forward","analyze","reverse_complement","complement","transcribe","reverse_transcribe","orf_find","codon_optimize","validate","gc_content","batch_score","batch_generate","batch_embeddings","batch_analyze","fetch_and_analyze","fetch_and_score","primer_design","crispr","melting_temp","tm","dna_to_protein_integrated","genome_pipeline","design_plasmid","plasmid_stats","set_host","get_host"}
LEGACY_DNA_ACTIONS = {"protein_to_dna", "dna_to_protein", "parse_fasta", "convert", "clean_sequence", "align"}

# Single source of truth — deduped
_ALL_ACTIONS = _BIOLAB_ACTIONS + _EVO2_ACTIONS
_LEGACY_DNA_META = [a for a in _BIOLAB_ACTIONS if a["id"] in LEGACY_DNA_ACTIONS]
_DNALAB_ACTIONS = _EVO2_ACTIONS + _LEGACY_DNA_META  # derived from _ALL_ACTIONS (Evo2 + legacy DNA helpers)
_BIOLAB_DNA_ACTIONS = list(_DNALAB_ACTIONS)  # back-compat alias — keep alive for health/counts
_BIOLAB_BY_ID = {a["id"]: a for a in _ALL_ACTIONS}

# Centralized action alias map (single source; shared by run/batch/fetch)
_DNA_ACTION_ALIASES = {
    "rev_comp": "reverse_complement", "revcomp": "reverse_complement", "rc": "reverse_complement",
    "transcription": "transcribe", "reverse_transcription": "reverse_transcribe",
    "orf": "orf_find", "orfs": "orf_find", "codon": "codon_optimize", "codon_opt": "codon_optimize",
    "validation": "validate", "gc": "gc_content",
    "fetch_analyze": "fetch_and_analyze", "fetch_score": "fetch_and_score",
    "primer": "primer_design", "tm": "melting_temp", "meltingtemp": "melting_temp", "melting_temp": "melting_temp",
    "crispr_guide": "crispr",
    "batchscore": "batch_score", "batchgenerate": "batch_generate", "batchembeddings": "batch_embeddings", "batchanalyze": "batch_analyze",
    "score": "batch_score", "generate": "batch_generate", "embeddings": "batch_embeddings", "analyze_batch": "batch_analyze",
    # v4 plasmid design aliases
    "design-plasmid": "design_plasmid", "designplasmid": "design_plasmid",
    "plasmid-stats": "plasmid_stats", "plasmidstats": "plasmid_stats",
    "set-host": "set_host", "sethost": "set_host", "set_host_organism": "set_host",
    "get-host": "get_host", "gethost": "get_host", "get_host_organism": "get_host",
}
_BATCH_ALIASES = {"batchscore":"batch_score","batchgenerate":"batch_generate","batchembeddings":"batch_embeddings","batchanalyze":"batch_analyze","score":"batch_score","generate":"batch_generate","embeddings":"batch_embeddings","analyze":"batch_analyze"}

def _normalize_dna_action(raw: str) -> str:
    a = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    return _DNA_ACTION_ALIASES.get(a, a)

# Helper: camelCase → snake_case + alias normalization for DNA/Evo2 params (single shared function)
def _dna_normalize_kwargs(raw_kwargs: dict) -> dict:
    """Normalize DNA lab kwargs (shared by run / batch / fetch):
       - camelCase to snake_case
       - alias map for referenceSequence/variantSequence/variantSequences/layerName/numTokens/topK/enableSampledProbs etc.
       - v3: pam, guideLength, primerLength, tmMethod, targetRegion, method
       - propagates layer <-> layer_name for compat.
    """
    alias = {
        "reference_sequence": "reference_sequence",
        "referenceSequence": "reference_sequence",
        "reference": "reference_sequence",
        "ref_seq": "reference_sequence",
        "refSeq": "reference_sequence",
        "variant_sequence": "variant_sequence",
        "variantSequence": "variant_sequence",
        "variant": "variant_sequence",
        "variant_sequences": "variant_sequences",
        "variantSequences": "variant_sequences",
        "variants": "variant_sequences",
        "sequences": "sequences",
        "sequence": "sequence",
        "seq": "sequence",
        "dna": "sequence",
        "dna_sequence": "sequence",
        "query": "query",
        "identifier": "identifier",
        "accession": "accession",
        "id": "identifier",
        "pdb_id": "identifier",
        "uniprot": "identifier",
        "url": "url",
        "organism": "organism",
        "org": "organism",
        "layer_name": "layer_name",
        "layerName": "layer_name",
        "layer": "layer_name",
        "num_tokens": "num_tokens",
        "numTokens": "num_tokens",
        "top_k": "top_k",
        "topK": "top_k",
        "enable_sampled_probs": "enable_sampled_probs",
        "enableSampledProbs": "enable_sampled_probs",
        "temperature": "temperature",
        "model": "model",
        "api_key": "api_key",
        "apiKey": "api_key",
        "k": "k",
        "fetch_mode": "fetch_mode",
        "fetchMode": "fetch_mode",
        "limit": "limit",
        "auto_analyze": "auto_analyze",
        "autoAnalyze": "auto_analyze",
        "content": "content",
        "from_format": "from_format",
        "fromFormat": "from_format",
        "to_format": "to_format",
        "toFormat": "to_format",
        "protein_sequence": "protein_sequence",
        "proteinSequence": "protein_sequence",
        "protein": "protein_sequence",
        # v3
        "pam": "pam",
        "guide_length": "guide_length",
        "guideLength": "guide_length",
        "primer_length": "primer_length",
        "primerLength": "primer_length",
        "tm_method": "tm_method",
        "tmMethod": "tm_method",
        "target_region": "target_region",
        "targetRegion": "target_region",
        "method": "method",
        # v4 plasmid design
        "host": "host",
        "organism": "organism",
        "org": "organism",
    }
    normalized: dict = {}
    for k, v in list(raw_kwargs.items()):
        if k in alias:
            target = alias[k]
        else:
            snake = ''.join(['_'+c.lower() if c.isupper() else c for c in k]).lstrip('_')
            target = alias.get(snake, alias.get(k, snake))
        if target not in normalized:
            normalized[target] = v
    if "layer_name" in normalized and "layer" not in normalized:
        normalized["layer"] = normalized["layer_name"]
    if "layer" in normalized and "layer_name" not in normalized:
        normalized["layer_name"] = normalized["layer"]
    if "sequence" in normalized and "sequences" not in normalized and isinstance(normalized["sequence"], list):
        normalized["sequences"] = normalized["sequence"]
    if "method" in normalized and "tm_method" not in normalized and normalized.get("method") in ("wallace","gc","nearest_neighbor","nn"):
        normalized["tm_method"] = normalized["method"]
    return normalized


@app.route("/api/protein-lab/run", methods=["POST"])
def api_protein_lab_run():
    """Run any Protein/DNA Lab action — unified proxy to skills.protein_lab.run.

    Accepts: { action: str, ...kwargs }  where kwargs are forwarded verbatim.
    Also normalizes common aliases (e.g. sequence2 -> sequence2, dna -> dna_sequence,
    protein -> protein_sequence) so the WebUI / workflow nodes stay ergonomic.
    """
    try:
        from protein_lab import run as protein_lab_run

        body = request.get_json(silent=True) or {}
        action = (body.get("action") or "analyze").strip().lower()
        kwargs = {k: v for k, v in body.items() if k != "action"}

        # ---- Alias normalization so workflow nodes can use ergonomic keys ----
        _alias = {
            "protein": "protein_sequence",
            "proteinSequence": "protein_sequence",
            "dna": "dna_sequence",
            "dnaSequence": "dna_sequence",
            "seq": "sequence",
            "seq1": "sequence1",
            "seq2": "sequence2",
            "ligand": "ligand_smiles",
            "smiles": "ligand_smiles",
            "text": "prompt",
            "query": "query",
            "id": "identifier",
            "pdb_id": "identifier",
            "uniprot": "identifier",
        }
        for src, dst in list(_alias.items()):
            if src in kwargs and dst not in kwargs:
                kwargs[dst] = kwargs[src]
        # Also accept camelCase from workflow nodes
        for k in list(kwargs.keys()):
            snake = ''.join(['_'+c.lower() if c.isupper() else c for c in k]).lstrip('_')
            if snake != k and snake not in kwargs:
                kwargs[snake] = kwargs[k]

        result = protein_lab_run(action=action, **kwargs)
        return jsonify({"result": result, "action": action})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/dna-lab/run", methods=["POST"])
def api_dna_lab_run():
    """Dedicated DNA Lab endpoint — dispatches to dna_lab (Evo2) or protein_lab (legacy DNA ops).

    Dispatch:
      DNA_EVO2_ACTIONS -> from dna_lab import run as dna_lab_run
      LEGACY_DNA_ACTIONS -> from protein_lab import run as protein_lab_run
    Aliases: camelCase→snake_case, referenceSequence→reference_sequence, variantSequence→variant_sequence,
             variantSequences→variant_sequences, layerName→layer_name/layer, numTokens→num_tokens,
             topK→top_k, enableSampledProbs etc.  Returns lab='dna' for Evo2, 'protein' for legacy.
    """
    try:
        body = request.get_json(silent=True) or {}
        raw_action = (body.get("action") or body.get("task") or "analyze")
        action = _normalize_dna_action(raw_action)
        raw_kwargs = {k: v for k, v in body.items() if k not in ("action", "task")}
        kwargs = _dna_normalize_kwargs(raw_kwargs)
        is_evo2 = action in DNA_EVO2_ACTIONS
        raw_out = dict(kwargs)  # what was actually forwarded
        if is_evo2:
            from dna_lab import run as dna_lab_run
            result = dna_lab_run(action=action, **kwargs)
            lab = "dna"
        else:
            from protein_lab import run as protein_lab_run
            # legacy actions expect protein_sequence/dna_sequence; if caller gave 'sequence', map for legacy
            if "sequence" in kwargs and "protein_sequence" not in kwargs and "dna_sequence" not in kwargs:
                if action == "dna_to_protein":
                    kwargs["dna_sequence"] = kwargs.pop("sequence")
                elif action in LEGACY_DNA_ACTIONS:
                    # protein_to_dna default, also align/parse etc.
                    if action == "protein_to_dna":
                        kwargs["protein_sequence"] = kwargs.pop("sequence")
            result = protein_lab_run(action=action, **kwargs)
            lab = "protein"
        return jsonify({"result": result, "action": action, "lab": lab, "raw": raw_out})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/dna-lab/batch", methods=["POST"])
def api_dna_lab_batch():
    """Convenience for batch_score / batch_generate / batch_embeddings / batch_analyze.
    Body: {action, reference_sequence, variant_sequences[], sequences[], layer, ...}
    Delegates to dna_lab batch handler via same dispatch (Evo2) with alias normalization.
    """
    try:
        body = request.get_json(silent=True) or {}
        raw_action = (body.get("action") or body.get("task") or "").strip()
        if not raw_action:
            if "reference_sequence" in body or "referenceSequence" in body:
                raw_action = "batch_score"
            elif "sequences" in body or "variant_sequences" in body or "variantSequences" in body:
                raw_action = "batch_analyze"
            else:
                raw_action = "batch_analyze"
        action = _normalize_dna_action(raw_action)
        # batch shorthand already covered by _DNA_ACTION_ALIASES; keep _BATCH_ALIASES as fallback for bare names
        if action not in DNA_EVO2_ACTIONS and action.lower().replace("_","") in _BATCH_ALIASES:
            action = _BATCH_ALIASES[action.lower().replace("_","")]
        raw_kwargs = {k: v for k, v in body.items() if k not in ("action", "task")}
        kwargs = _dna_normalize_kwargs(raw_kwargs)
        raw_out = dict(kwargs)
        # batch actions are always Evo2
        if action not in DNA_EVO2_ACTIONS:
            # force to batch_analyze if still unknown
            if action in {"batch_score","batch_generate","batch_embeddings","batch_analyze"}:
                pass
            else:
                return jsonify({"error": "batch action must be one of: batch_score, batch_generate, batch_embeddings, batch_analyze", "action": action}), 400
        from dna_lab import run as dna_lab_run
        result = dna_lab_run(action=action, **kwargs)
        return jsonify({"result": result, "action": action, "lab": "dna", "raw": raw_out})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/dna-lab/fetch", methods=["POST"])
def api_dna_lab_fetch():
    """Fetch & analyze/score via dna_lab (sub-bots / NCBI fallback).
    Body: {query/url/identifier/accession/fetch_mode/limit/auto_analyze, reference_sequence?, variant_sequence?}
    Delegates to dna_lab fetch_and_analyze (default) or fetch_and_score if variant info present.
    """
    try:
        body = request.get_json(silent=True) or {}
        raw_action_raw = (body.get("action") or body.get("task") or "")
        raw_action = _normalize_dna_action(raw_action_raw) if raw_action_raw else ""
        raw_kwargs = {k: v for k, v in body.items() if k not in ("action", "task")}
        kwargs = _dna_normalize_kwargs(raw_kwargs)
        raw_out = dict(kwargs)
        if raw_action in DNA_EVO2_ACTIONS and raw_action.startswith("fetch"):
            action = raw_action
        else:
            has_variant = any(k in kwargs for k in ("variant_sequence","variant_sequences","reference_sequence"))
            has_variant_raw = any(k in body for k in ("variantSequence","variantSequences","variant_sequence","variant_sequences","referenceSequence","reference_sequence"))
            if has_variant or has_variant_raw or raw_action == "fetch_and_score":
                action = "fetch_and_score"
            else:
                action = "fetch_and_analyze"
        from dna_lab import run as dna_lab_run
        result = dna_lab_run(action=action, **kwargs)
        return jsonify({"result": result, "action": action, "lab": "dna", "raw": raw_out})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/boltz/run", methods=["POST"])
def api_boltz_run():
    """Proxy to skills.boltz_2.run — exposes all Boltz-2 tasks (fold, multimer, ligand, covalent, dna_protein)."""
    try:
        from boltz_2 import run as boltz_run
        body = request.get_json(silent=True) or {}
        # Forward every field; boltz_2 has its own validation
        result = boltz_run(**body)
        return jsonify({"result": result, "task": body.get("task", "fold")})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/biolab/health")
def api_biolab_health():
    """Health + capability check for the BioLab subsystem (protein, dna, Evo2, sub-bots)."""
    info = {"protein_lab": False, "dna_lab": False, "boltz_2": False, "biotite": False, "firecrawl": False, "evo2_nim": False, "sub_bots": False}
    try:
        import protein_lab  # noqa: F401
        info["protein_lab"] = True
    except Exception:
        pass
    try:
        import dna_lab  # noqa: F401
        info["dna_lab"] = True
    except Exception:
        pass
    try:
        import boltz_2  # noqa: F401
        info["boltz_2"] = True
    except Exception:
        pass
    try:
        import biotite  # noqa: F401
        info["biotite"] = True
    except Exception:
        pass
    try:
        from skills import web_crawler  # noqa: F401
        info["firecrawl"] = True
    except Exception:
        pass
    # Evo2 NIM key present
    try:
        if os.environ.get("NVIDIA_API_KEY") or os.environ.get("NVCF_RUN_KEY"):
            info["evo2_nim"] = True
        else:
            # also show as False but keep key; will be reported via dna_lab check
            info["evo2_nim"] = False
    except Exception:
        pass
    # sub-bots manager check
    try:
        from ultron_sub_bots.manager import SubBotManager  # noqa: F401
        info["sub_bots"] = True
    except Exception:
        try:
            import ultron_sub_bots  # noqa: F401
            info["sub_bots"] = True
        except Exception:
            info["sub_bots"] = False
    return jsonify({
        "ok": True,
        "capabilities": info,
        "actions_count": len(_BIOLAB_ACTIONS),
        "evo2_actions_count": len(_EVO2_ACTIONS),
        "dna_actions_count": len(_DNALAB_ACTIONS),
        "total_actions": len(_BIOLAB_ACTIONS) + len(_EVO2_ACTIONS),
    })


@app.route("/api/dna-lab/health")
def api_dna_lab_health():
    """Dedicated DNA Lab health — mirrors biolab but focused on Evo2/NIM/sub-bots."""
    info = {"dna_lab": False, "evo2_nim": False, "sub_bots": False, "biotite": False, "firecrawl": False, "protein_lab": False}
    try:
        import dna_lab  # noqa: F401
        info["dna_lab"] = True
    except Exception:
        pass
    try:
        import protein_lab  # noqa: F401
        info["protein_lab"] = True
    except Exception:
        pass
    try:
        import biotite  # noqa: F401
        info["biotite"] = True
    except Exception:
        pass
    try:
        from skills import web_crawler  # noqa: F401
        info["firecrawl"] = True
    except Exception:
        pass
    has_key = bool(os.environ.get("NVIDIA_API_KEY") or os.environ.get("NVCF_RUN_KEY"))
    info["evo2_nim"] = has_key
    try:
        from ultron_sub_bots.manager import SubBotManager  # noqa: F401
        info["sub_bots"] = True
    except Exception:
        try:
            import ultron_sub_bots  # noqa: F401
            info["sub_bots"] = True
        except Exception:
            info["sub_bots"] = False
    return jsonify({
        "ok": True,
        "lab": "dna",
        "capabilities": info,
        "actions": len(_EVO2_ACTIONS),
        "evo2_actions": [a["id"] for a in _EVO2_ACTIONS],
        "legacy_actions": list(LEGACY_DNA_ACTIONS),
        "dna_evo2_actions": sorted(list(DNA_EVO2_ACTIONS)),
    })


@app.route("/api/protein-lab/actions")
def api_protein_lab_actions():
    """Get available Protein/DNA Lab actions — structured + human-readable help.

    Query params:
      format=json|text  (default json)  — json returns _BIOLAB_ACTIONS; text returns the skill help string.
      category=...      — optional filter (Analysis, Structure, DNA Lab, etc.)
    """
    fmt = (request.args.get("format") or "json").lower()
    cat = (request.args.get("category") or "").strip()

    # Text mode = legacy skill help string (for backwards compat)
    if fmt == "text":
        try:
            from protein_lab import run as protein_lab_run
            result = protein_lab_run(action="help")
            return jsonify({"actions": result, "format": "text"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    actions = _BIOLAB_ACTIONS
    if cat:
        actions = [a for a in actions if a["category"].lower() == cat.lower()]
    return jsonify({"actions": actions, "count": len(actions), "format": "json"})


@app.route("/api/dna-lab/actions")
def api_dna_lab_actions():
    """Get DNA Lab specific actions — merged Evo2 + legacy DNA ops.

    Query params:
      category=Evo2|Batch|Fetch|DNA Lab|Sequence Ops (optional filter)
      format=json|text (text returns dna_lab help string)
    """
    fmt = (request.args.get("format") or "json").lower()
    cat = (request.args.get("category") or "").strip()
    if fmt == "text":
        try:
            from dna_lab import run as dna_lab_run
            result = dna_lab_run(action="help")
            return jsonify({"actions": result, "format": "text", "lab": "dna"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    actions = _DNALAB_ACTIONS
    if cat:
        actions = [a for a in actions if a["category"].lower() == cat.lower()]
    return jsonify({"actions": actions, "count": len(actions), "format": "json", "lab": "dna", "evo2_actions": len(_EVO2_ACTIONS), "legacy_actions": len(_LEGACY_DNA_META)})


@app.route("/api/boltz/actions")
def api_boltz_actions():
    """List Boltz-2 tasks."""
    return jsonify({"actions": [
        {"id": "fold", "label": "Fold (single chain)", "inputs": ["sequence / protein_sequence"]},
        {"id": "multimer", "label": "Multimer (multi-chain)", "inputs": ["sequences dict or list"]},
        {"id": "ligand", "label": "Protein-ligand + affinity", "inputs": ["protein_sequence", "ligand_smiles|ligand_ccd", "predict_affinity?", "pocket_residues?"]},
        {"id": "covalent", "label": "Covalent ligand", "inputs": ["protein_sequence", "ligand_ccd", "covalent_bonds"]},
        {"id": "dna_protein", "label": "DNA-protein complex", "inputs": ["protein_sequences[]", "dna_sequences[]"]},
    ]})


# =============================================================================
# MASTERMIND — Deep Research & Knowledge Synthesis
# =============================================================================

@app.route("/api/mastermind/run", methods=["POST"])
def api_mastermind_run():
    """Run MasterMind deep research — PhD-level topic analysis.

    Accepts: { action: "research"|"query"|"list"|"status", topic: str, question: str, depth: str }
    
    Actions:
      research — Deep web research, LLM synthesis, saves to knowledge base
      query    — Query stored research with questions
      list     — List all researched topics
      status   — Show knowledge base stats
    
    The research action increases step limits and timeout for long-running processes.
    """
    try:
        from master_mind import run as mastermind_run

        body = request.get_json(silent=True) or {}
        action = (body.get("action") or "research").strip().lower()
        kwargs = {k: v for k, v in body.items() if k != "action"}

        # Normalize camelCase to snake_case
        for k in list(kwargs.keys()):
            snake = ''.join(['_'+c.lower() if c.isupper() else c for c in k]).lstrip('_')
            if snake != k and snake not in kwargs:
                kwargs[snake] = kwargs[k]

        result = mastermind_run(action=action, **kwargs)
        return jsonify({"result": result, "action": action, "success": True})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e), "success": False}), 500


@app.route("/api/mastermind/status")
def api_mastermind_status():
    """Get MasterMind knowledge base status."""
    try:
        from master_mind import run as mastermind_run
        result = mastermind_run(action="status")
        return jsonify({"result": result, "success": True})
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500


@app.route("/api/mastermind/list")
def api_mastermind_list():
    """List all researched topics in MasterMind knowledge base."""
    try:
        from master_mind import run as mastermind_run
        result = mastermind_run(action="list")
        return jsonify({"result": result, "success": True})
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500


# =============================================================================
# MECH LAB — Text-to-CAD endpoints
# =============================================================================

_MECHLAB_ACTIONS = [
    {"id": "generate", "label": "Generate CAD", "category": "CAD", "description": "Generate STEP file from natural language description", "inputs": ["prompt", "output_path?"], "output": "STEP file + preview"},
    {"id": "inspect", "label": "Inspect Geometry", "category": "CAD", "description": "Inspect STEP/STP file for refs, facts, planes, positioning", "inputs": ["target", "facts?", "planes?", "positioning?"], "output": "inspection report"},
    {"id": "snapshot", "label": "Snapshot Preview", "category": "CAD", "description": "Generate PNG/GIF visual preview of CAD model", "inputs": ["target"], "output": "image file path"},
    {"id": "export_stl", "label": "Export STL", "category": "Export", "description": "Export STEP to STL mesh format", "inputs": ["target", "output?"], "output": "STL file path"},
    {"id": "export_3mf", "label": "Export 3MF", "category": "Export", "description": "Export STEP to 3MF format", "inputs": ["target", "output?"], "output": "3MF file path"},
    {"id": "export_glb", "label": "Export GLB", "category": "Export", "description": "Export STEP to native GLB format", "inputs": ["target", "output?"], "output": "GLB file path"},
    {"id": "help", "label": "Help", "category": "Utilities", "description": "List all Mech Lab actions", "inputs": [], "output": "help text"},
]

# Canonical path to text-to-cad skill
_TEXT_TO_CAD_ROOT = os.path.join(ROOT, "text-to-cad-main", "text-to-cad-main")
_CAD_SKILL_DIR = os.path.join(_TEXT_TO_CAD_ROOT, "skills", "cad")
_CAD_SCRIPTS_DIR = os.path.join(_CAD_SKILL_DIR, "scripts")


def _find_python():
    """Find the best available Python interpreter."""
    # Check for .venv first
    venv_python = os.path.join(ROOT, ".venv", "Scripts", "python.exe" if os.name == "nt" else "bin", "python")
    if os.path.isfile(venv_python):
        return venv_python
    venv_python2 = os.path.join(ROOT, ".venv", "bin", "python")
    if os.path.isfile(venv_python2):
        return venv_python2
    return sys.executable


def _run_cad_command(cmd_args, cwd=None, timeout=120):
    """Run a CAD skill command and return (stdout, stderr, returncode)."""
    import subprocess
    python = _find_python()
    if cwd is None:
        cwd = _CAD_SKILL_DIR
    try:
        result = subprocess.run(
            [python] + cmd_args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONPATH": _TEXT_TO_CAD_ROOT},
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "", "Command timed out after %ds" % timeout, -1
    except Exception as e:
        return "", str(e), -1


def _generate_build123d_source(prompt):
    """Generate build123d Python source from a natural language prompt.
    
    This creates a Python file with a gen_step() function that build123d can render.
    For now, we provide a template-based generator; a real deployment would use an LLM.
    """
    # Escape prompt for embedding in Python string
    safe_prompt = prompt.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    
    source = '''"""Auto-generated build123d CAD source.

Description: {prompt}
"""
import math
from build123d import *


def gen_step() -> Part:
    """Generate the CAD part from the description."""
    # TODO: Replace with LLM-generated geometry based on the prompt.
    # This is a placeholder that demonstrates the pipeline.
    with BuildPart() as part:
        # Default: create a simple block as placeholder
        Box(100, 60, 20)
        # Add fillets to edges
        fillet(part.edges(), radius=2)
    return part


if __name__ == "__main__":
    from cadpy.generation import generate_step_targets
    generate_step_targets(["__main__.py"], verbose=True)
'''.format(prompt=safe_prompt)
    return source


@app.route("/api/mech-lab/run", methods=["POST"])
def api_mech_lab_run():
    """Run any Mech Lab action — text-to-CAD pipeline.

    Accepts: { action: str, prompt?: str, target?: str, output?: str, ... }
    Actions: generate, inspect, snapshot, export_stl, export_3mf, export_glb, help
    """
    try:
        body = request.get_json(silent=True) or {}
        action = (body.get("action") or "help").strip().lower()
        
        if action == "help":
            help_text = "MECH LAB — Text-to-CAD Actions:\n\n"
            for a in _MECHLAB_ACTIONS:
                help_text += f"  {a['id']:20s} — {a['description']}\n"
                if a['inputs']:
                    help_text += f"  {'':20s}   Inputs: {', '.join(a['inputs'])}\n"
            help_text += "\nUsage: Send a POST request with {action: 'generate', prompt: '...'} to create CAD.\n"
            help_text += "The generate action creates build123d Python source and runs it through the CAD pipeline.\n"
            return jsonify({"result": help_text, "action": "help"})
        
        if action == "generate":
            prompt = (body.get("prompt") or "").strip()
            if not prompt:
                return jsonify({"error": "prompt is required for generate action"}), 400
            
            output_dir = body.get("output_dir") or os.path.join(ROOT, "output", "cad")
            os.makedirs(output_dir, exist_ok=True)
            
            # Generate a safe filename from prompt
            import re
            safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', prompt[:50]).strip('_').lower()
            if not safe_name:
                safe_name = "cad_part_%d" % int(time.time())
            
            source_path = os.path.join(output_dir, "%s.py" % safe_name)
            step_path = os.path.join(output_dir, "%s.step" % safe_name)
            
            # Generate build123d source
            source = _generate_build123d_source(prompt)
            with open(source_path, "w") as f:
                f.write(source)
            
            # Run the STEP generation
            stdout, stderr, rc = _run_cad_command(
                ["-m", "scripts.step", source_path, "-o", step_path],
                cwd=_CAD_SKILL_DIR,
                timeout=180,
            )
            
            result_lines = []
            result_lines.append("=== MECH LAB — CAD Generation ===")
            result_lines.append("Prompt: %s" % prompt)
            result_lines.append("Source: %s" % source_path)
            result_lines.append("Output: %s" % step_path)
            result_lines.append("")
            
            if rc == 0:
                result_lines.append("SUCCESS — STEP file generated!")
                result_lines.append("")
                if stdout:
                    result_lines.append("Output:\n%s" % stdout)
            else:
                result_lines.append("STEP generation returned code %d" % rc)
                if stderr:
                    result_lines.append("Errors:\n%s" % stderr)
                if stdout:
                    result_lines.append("Output:\n%s" % stdout)
                result_lines.append("")
                result_lines.append("Note: The source file was created at: %s" % source_path)
                result_lines.append("You can edit it and re-run, or use the build123d API directly.")
            
            return jsonify({
                "result": "\n".join(result_lines),
                "action": "generate",
                "source_path": source_path,
                "step_path": step_path if rc == 0 else None,
                "success": rc == 0,
            })
        
        elif action == "inspect":
            target = (body.get("target") or "").strip()
            if not target:
                return jsonify({"error": "target is required for inspect action"}), 400
            
            cmd = ["-m", "scripts.inspect", "refs", target]
            if body.get("facts"):
                cmd.append("--facts")
            if body.get("planes"):
                cmd.append("--planes")
            if body.get("positioning"):
                cmd.append("--positioning")
            
            stdout, stderr, rc = _run_cad_command(cmd, cwd=_CAD_SKILL_DIR)
            
            result_text = ""
            if rc == 0:
                result_text = stdout or "Inspection complete (no output)"
            else:
                result_text = "Inspection failed (code %d)\n%s\n%s" % (rc, stdout, stderr)
            
            return jsonify({"result": result_text, "action": "inspect", "success": rc == 0})
        
        elif action == "snapshot":
            target = (body.get("target") or "").strip()
            if not target:
                return jsonify({"error": "target is required for snapshot action"}), 400
            
            stdout, stderr, rc = _run_cad_command(
                ["-m", "scripts.snapshot", target],
                cwd=_CAD_SKILL_DIR,
            )
            
            result_text = ""
            if rc == 0:
                result_text = stdout or "Snapshot generated"
            else:
                result_text = "Snapshot failed (code %d)\n%s\n%s" % (rc, stdout, stderr)
            
            return jsonify({"result": result_text, "action": "snapshot", "success": rc == 0})
        
        elif action in ("export_stl", "export_3mf", "export_glb"):
            target = (body.get("target") or "").strip()
            if not target:
                return jsonify({"error": "target is required for export action"}), 400
            
            export_flag = {"export_stl": "--stl", "export_3mf": "--3mf", "export_glb": "--glb"}[action]
            output = body.get("output") or target.rsplit(".", 1)[0] + {"export_stl": ".stl", "export_3mf": ".3mf", "export_glb": ".glb"}[action]
            
            stdout, stderr, rc = _run_cad_command(
                ["-m", "scripts.step", target, export_flag, output],
                cwd=_CAD_SKILL_DIR,
            )
            
            result_text = ""
            if rc == 0:
                result_text = "Export complete: %s\n%s" % (output, stdout)
            else:
                result_text = "Export failed (code %d)\n%s\n%s" % (rc, stdout, stderr)
            
            return jsonify({"result": result_text, "action": action, "success": rc == 0, "output": output if rc == 0 else None})
        
        else:
            return jsonify({"error": "Unknown action: %s. Valid: %s" % (action, ", ".join(a["id"] for a in _MECHLAB_ACTIONS))}), 400
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/mech-lab/actions")
def api_mech_lab_actions():
    """Get available Mech Lab actions."""
    return jsonify({"actions": _MECHLAB_ACTIONS, "count": len(_MECHLAB_ACTIONS)})


@app.route("/api/mech-lab/health")
def api_mech_lab_health():
    """Health check for Mech Lab — verifies text-to-cad skill is installed."""
    info = {
        "text_to_cad": os.path.isdir(_TEXT_TO_CAD_ROOT),
        "cad_skill": os.path.isdir(_CAD_SKILL_DIR),
        "cadpy_available": False,
        "build123d_available": False,
    }
    try:
        import cadpy
        info["cadpy_available"] = True
    except ImportError:
        pass
    try:
        import build123d
        info["build123d_available"] = True
    except ImportError:
        pass
    return jsonify({"ok": True, "capabilities": info})


# =============================================================================
# MECH LAB — Extended Skills Endpoints
# =============================================================================

_TEXT_TO_CAD_SKILLS_DIR = os.path.join(_TEXT_TO_CAD_ROOT, "skills")


def _run_skill_command(skill_name, cmd_args, cwd=None, timeout=120):
    """Run a command in a specific skill directory."""
    import subprocess
    python = _find_python()
    skill_dir = os.path.join(_TEXT_TO_CAD_SKILLS_DIR, skill_name)
    if cwd is None:
        cwd = skill_dir
    try:
        result = subprocess.run(
            [python] + cmd_args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONPATH": _TEXT_TO_CAD_ROOT},
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "", "Command timed out after %ds" % timeout, -1
    except Exception as e:
        return "", str(e), -1


@app.route("/api/mech-lab/dxf", methods=["POST"])
def api_mech_lab_dxf():
    """Generate DXF 2D drawing from Python ezdxf source."""
    try:
        body = request.get_json(silent=True) or {}
        source_path = (body.get("source") or "").strip()
        output_path = body.get("output")

        if not source_path:
            return jsonify({"error": "source path is required"}), 400

        cmd = ["-m", "scripts.dxf", source_path]
        if output_path:
            cmd.extend(["-o", output_path])

        stdout, stderr, rc = _run_skill_command("dxf", cmd)
        result_text = stdout if rc == 0 else f"DXF generation failed (code {rc})\n{stderr}\n{stdout}"
        return jsonify({"result": result_text, "action": "dxf", "success": rc == 0})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/mech-lab/gcode", methods=["POST"])
def api_mech_lab_gcode():
    """Slice 3D mesh to G-code using slicer backends."""
    try:
        body = request.get_json(silent=True) or {}
        action = (body.get("sub_action") or "discover").strip()
        input_path = (body.get("input") or "").strip()
        output_path = body.get("output")
        profile = body.get("profile")

        if action == "discover":
            stdout, stderr, rc = _run_skill_command("gcode", ["-m", "scripts.gcode_tool", "discover"])
        elif action == "inspect":
            if not input_path:
                return jsonify({"error": "input is required for inspect"}), 400
            stdout, stderr, rc = _run_skill_command("gcode", ["-m", "scripts.gcode_tool", "inspect", "--input", input_path, "--json"])
        elif action == "slice":
            if not input_path or not output_path:
                return jsonify({"error": "input and output are required for slice"}), 400
            cmd = ["-m", "scripts.gcode_tool", "slice", "--input", input_path, "--output", output_path, "--backend", "auto"]
            if profile:
                cmd.extend(["--profile", profile])
            if body.get("dry_run"):
                cmd.append("--dry-run")
            else:
                cmd.append("--execute")
            stdout, stderr, rc = _run_skill_command("gcode", cmd, timeout=300)
        elif action == "validate":
            gcode_path = (body.get("gcode") or "").strip()
            if not gcode_path:
                return jsonify({"error": "gcode path is required for validate"}), 400
            cmd = ["-m", "scripts.gcode_tool", "validate", "--gcode", gcode_path, "--json"]
            if profile:
                cmd.extend(["--profile", profile])
            stdout, stderr, rc = _run_skill_command("gcode", cmd)
        else:
            return jsonify({"error": f"Unknown sub_action: {action}"}), 400

        result_text = stdout if rc == 0 else f"G-code {action} failed (code {rc})\n{stderr}\n{stdout}"
        return jsonify({"result": result_text, "action": "gcode", "sub_action": action, "success": rc == 0})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/mech-lab/urdf", methods=["POST"])
def api_mech_lab_urdf():
    """Generate URDF robot description from Python source."""
    try:
        body = request.get_json(silent=True) or {}
        source_path = (body.get("source") or "").strip()
        output_path = body.get("output")

        if not source_path:
            return jsonify({"error": "source path is required"}), 400

        cmd = ["-m", "scripts.urdf", source_path]
        if output_path:
            cmd.extend(["-o", output_path])

        stdout, stderr, rc = _run_skill_command("urdf", cmd)
        result_text = stdout if rc == 0 else f"URDF generation failed (code {rc})\n{stderr}\n{stdout}"
        return jsonify({"result": result_text, "action": "urdf", "success": rc == 0})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/mech-lab/step-parts", methods=["POST"])
def api_mech_lab_step_parts():
    """Search step.parts catalog for purchasable CAD parts."""
    try:
        body = request.get_json(silent=True) or {}
        query = (body.get("query") or "").strip()
        download = body.get("download", False)
        part_id = body.get("id")

        if not query and not part_id:
            return jsonify({"error": "query or id is required"}), 400

        cmd = ["-m", "scripts.download_step_part.py"]
        if part_id:
            cmd.extend(["--id", part_id])
        else:
            cmd.append(query)

        if download:
            cmd.append("--download")

        stdout, stderr, rc = _run_skill_command("step-parts", cmd, timeout=60)
        result_text = stdout if rc == 0 else f"Step parts search failed (code {rc})\n{stderr}\n{stdout}"
        return jsonify({"result": result_text, "action": "step-parts", "success": rc == 0})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/mech-lab/bambu", methods=["POST"])
def api_mech_lab_bambu():
    """Bambu Lab printer control — config, status, send, pause, cancel."""
    try:
        body = request.get_json(silent=True) or {}
        sub_action = (body.get("sub_action") or "status").strip()
        printer = body.get("printer", "a1-mini")

        cmd = ["-m", "scripts.bambu_lan_print", sub_action, "--printer", printer]

        if sub_action == "config":
            host = body.get("host")
            access_code = body.get("access_code")
            if host:
                cmd.extend(["--host", host])
            if access_code:
                cmd.extend(["--access-code", access_code])
            if body.get("fetch_serial"):
                cmd.append("--fetch-serial")
        elif sub_action == "send":
            gcode = body.get("gcode")
            handoff = body.get("handoff", "template-project")
            action_mode = body.get("action_mode", "upload-only")
            if gcode:
                cmd.extend(["--gcode", gcode])
            cmd.extend(["--handoff", handoff, "--action", action_mode])
            if body.get("execute"):
                cmd.append("--execute")
                if body.get("confirm_start_print"):
                    cmd.append("--confirm-start-print")
        elif sub_action == "status":
            if body.get("push_all"):
                cmd.append("--push-all")
            wait = body.get("wait_seconds", 5)
            cmd.extend(["--wait-seconds", str(wait)])
        elif sub_action in ("pause", "cancel"):
            if body.get("execute"):
                cmd.append("--execute")
                if sub_action == "cancel" and body.get("confirm_cancel_print"):
                    cmd.append("--confirm-cancel-print")

        stdout, stderr, rc = _run_skill_command("bambu-labs", cmd, timeout=30)
        result_text = stdout if rc == 0 else f"Bambu {sub_action} failed (code {rc})\n{stderr}\n{stdout}"
        return jsonify({"result": result_text, "action": "bambu", "sub_action": sub_action, "success": rc == 0})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/mech-lab/mech-ai", methods=["POST"])
def api_mech_lab_mech_ai():
    """Mechanical AI Skill — BOM, diagnostics, analysis, reports."""
    try:
        body = request.get_json(silent=True) or {}
        sub_action = (body.get("sub_action") or "understand").strip()
        task = body.get("task", {})

        script_map = {
            "understand": "scripts.sw_understand.py",
            "mechanism": "scripts.sw_mechanism.py",
            "diagnostics": "scripts.sw_diagnostics.py",
            "export": "scripts.sw_export.py",
            "report": "scripts.report_pdf.py",
            "dfm": "scripts.sw_dfm.py",
            "analysis": "scripts.run_analysis.py",
            "optimize": "scripts.optimize.py",
            "design_review": "scripts.design_review.py",
        }

        script = script_map.get(sub_action)
        if not script:
            return jsonify({"error": f"Unknown sub_action: {sub_action}"}), 400

        # Write task JSON to temp file
        import tempfile
        task_path = os.path.join(tempfile.gettempdir(), f"mech_ai_task_{int(time.time())}.json")
        out_path = os.path.join(tempfile.gettempdir(), f"mech_ai_result_{int(time.time())}.json")

        with open(task_path, "w") as f:
            json.dump(task, f)

        cmd = [script, "--task", task_path, "--out", out_path]
        if sub_action == "report":
            results_files = body.get("results", [])
            cmd = [script, "--out", out_path]
            for rf in results_files:
                cmd.extend(["--results", rf])

        stdout, stderr, rc = _run_skill_command("Mechanical-AI-Skill-main", cmd, timeout=300)

        result_data = None
        if os.path.isfile(out_path):
            with open(out_path) as f:
                result_data = json.load(f)

        result_text = stdout if rc == 0 else f"Mechanical AI {sub_action} failed (code {rc})\n{stderr}\n{stdout}"
        return jsonify({
            "result": result_text,
            "action": "mech-ai",
            "sub_action": sub_action,
            "success": rc == 0,
            "data": result_data,
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/mech-lab/skills")
def api_mech_lab_skills():
    """List all available Mech Lab skills."""
    skills = [
        {"id": "text-to-cad", "name": "Text to CAD", "category": "CAD Generation", "backend": True},
        {"id": "cad-viewer", "name": "CAD Viewer", "category": "CAD Generation", "backend": True},
        {"id": "step-parts", "name": "Step Parts Catalog", "category": "CAD Generation", "backend": True},
        {"id": "dxf", "name": "DXF 2D Drawings", "category": "Manufacturing", "backend": True},
        {"id": "gcode", "name": "G-code (3D Printing)", "category": "Manufacturing", "backend": True},
        {"id": "bambu-labs", "name": "Bambu Lab Print", "category": "Manufacturing", "backend": True},
        {"id": "sendcutsend", "name": "SendCutSend Preflight", "category": "Manufacturing", "backend": False},
        {"id": "urdf", "name": "URDF Robot Description", "category": "Robotics", "backend": True},
        {"id": "srdf", "name": "SRDF Motion Planning", "category": "Robotics", "backend": False},
        {"id": "sdf", "name": "SDF Simulator Worlds", "category": "Robotics", "backend": False},
        {"id": "mech-ai", "name": "Mechanical AI Skill", "category": "Engineering Analysis", "backend": True},
        {"id": "thermal-research", "name": "Thermal-Fluid Research", "category": "Engineering Analysis", "backend": False},
        {"id": "implicit-cad", "name": "Implicit CAD (SDF/GLSL)", "category": "CAD Generation", "backend": False},
    ]
    return jsonify({"skills": skills, "count": len(skills)})


# =============================================================================
# PROJECT MODE — Idea-to-Reality Pipeline
# =============================================================================

@app.route("/api/project-mode/start", methods=["POST"])
def api_project_mode_start():
    """Start a new project from an idea."""
    try:
        from project_mode import run as project_run
        body = request.get_json(silent=True) or {}
        idea = (body.get("idea") or "").strip()
        if not idea:
            return jsonify({"error": "idea is required"}), 400
        result = project_run(action="create", idea=idea)
        # Extract project_id from result
        project_id = ""
        for part in result.split():
            if len(part) == 8 and part.isalnum():
                project_id = part
                break
        return jsonify({"ok": True, "result": result, "project_id": project_id})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/project-mode/status/<project_id>")
def api_project_mode_status(project_id):
    """Get project status."""
    try:
        from project_mode import run as project_run, _get_project
        project = _get_project(project_id)
        if not project:
            return jsonify({"error": f"Project {project_id} not found"}), 404
        return jsonify({"ok": True, "project": project.to_dict()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/project-mode/result/<project_id>")
def api_project_mode_result(project_id):
    """Get project results."""
    try:
        from project_mode import run as project_run, _get_project
        project = _get_project(project_id)
        if not project:
            return jsonify({"error": f"Project {project_id} not found"}), 404
        return jsonify({"ok": True, "project": project.to_dict()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/project-mode/list")
def api_project_mode_list():
    """List all projects."""
    try:
        from project_mode import run as project_run, _projects, _project_lock
        with _project_lock:
            projects = [p.to_dict() for p in _projects.values()]
        return jsonify({"ok": True, "projects": projects})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# MCP SERVER MANAGEMENT ENDPOINTS
# =============================================================================
@app.route("/api/mcp/status")
def api_mcp_status():
    """Get overall MCP connection status."""
    try:
        from core.mcp_dynamic import _agent_mcp_manager
        report = _agent_mcp_manager.get_status_report()
        return jsonify(report)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/mcp/servers")
def api_mcp_servers():
    """List all configured MCP servers with their status."""
    try:
        from core.mcp_dynamic import _agent_mcp_manager
        servers = []
        for sid, conn in _agent_mcp_manager.connections.items():
            servers.append({
                "id": sid,
                "status": conn.status,
                "enabled": conn.config.get("enabled", True),
                "command": conn.config.get("command", []),
                "type": conn.config.get("type", "local"),
                "connected_at": conn.connected_at,
                "last_heartbeat": conn.last_heartbeat,
            })
        return jsonify({"servers": servers})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/mcp/toggle", methods=["POST"])
def api_mcp_toggle():
    """Toggle an MCP server connection."""
    try:
        from core.mcp_dynamic import _agent_mcp_manager
        import asyncio
        body = request.get_json(silent=True) or {}
        server_id = (body.get("server_id") or "").strip()
        if not server_id:
            return jsonify({"error": "server_id required"}), 400

        # Run the async toggle in a sync context
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(_agent_mcp_manager.toggle_server(server_id))
        finally:
            loop.close()

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/mcp/connect", methods=["POST"])
def api_mcp_connect():
    """Connect to an MCP server."""
    try:
        from core.mcp_dynamic import _agent_mcp_manager
        import asyncio
        body = request.get_json(silent=True) or {}
        server_id = (body.get("server_id") or "").strip()
        if not server_id:
            return jsonify({"error": "server_id required"}), 400

        loop = asyncio.new_event_loop()
        try:
            success = loop.run_until_complete(_agent_mcp_manager.connect_server(server_id))
        finally:
            loop.close()

        return jsonify({"success": success, "server_id": server_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/mcp/disconnect", methods=["POST"])
def api_mcp_disconnect():
    """Disconnect from an MCP server."""
    try:
        from core.mcp_dynamic import _agent_mcp_manager
        import asyncio
        body = request.get_json(silent=True) or {}
        server_id = (body.get("server_id") or "").strip()
        if not server_id:
            return jsonify({"error": "server_id required"}), 400

        loop = asyncio.new_event_loop()
        try:
            success = loop.run_until_complete(_agent_mcp_manager.disconnect_server(server_id))
        finally:
            loop.close()

        return jsonify({"success": success, "server_id": server_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/output/<filename>")
def api_output_file(filename):
    path = file_output.get_file_path(filename)
    if path is None:
        return jsonify({"error": "File not found"}), 404
    return send_file(path, as_attachment=True, download_name=filename)


@app.route("/api/output")
def api_output_list():
    return jsonify(file_output.list_files())


@app.route("/api/cache/stats")
def api_cache_stats():
    stats = _get_cache_stats()
    total = stats["hits"] + stats["misses"]
    hit_rate = (stats["hits"] / total * 100) if total > 0 else 0

    # Also include core cache stats
    core_stats = get_cache_manager().get_all_stats()

    return jsonify({
        "flask_cache": {
            "hits": stats["hits"],
            "misses": stats["misses"],
            "errors": stats["errors"],
            "hit_rate_pct": round(hit_rate, 2),
            "backend": "redis" if USE_REDIS else "memory",
            "version": CACHE_VERSION,
        },
        "core_cache": core_stats,
    })


@app.route("/api/cache/clear", methods=["POST"])
def api_cache_clear():
    invalidate_cache_pattern("*")
    for ns in ('skills', 'recipes', 'memory', 'vault'):
        get_cache_manager().invalidate(ns)
    with _cache_stats_lock:
        cache_stats["hits"] = 0
        cache_stats["misses"] = 0
        cache_stats["errors"] = 0
    return jsonify({"ok": True, "cleared": True})


@app.route("/api/update/check")
def api_update_check():
    """Check the cloud repo for a newer Ultron version."""
    return jsonify(updater.check())


@app.route("/api/update/apply", methods=["POST"])
def api_update_apply():
    """Pull the latest version from the cloud and restart."""
    return jsonify(updater.apply_update())


@app.route("/<path:filename>")
def serve_static(filename):
    """Serve static files (hud fonts, textures, icons) with long-term cache headers."""
    # Security: prevent path traversal by resolving and checking the path is within WEBUI (ultron-workflow/dist)
    webui_real = os.path.realpath(WEBUI)
    file_path = os.path.realpath(os.path.join(WEBUI, filename))
    if not file_path.startswith(webui_real + os.sep) and file_path != webui_real:
        return send_from_directory(WEBUI, "index.html")
    if not os.path.isfile(file_path):
        return send_from_directory(WEBUI, "index.html")

    # Use the resolved path to serve the file safely
    # send_from_directory expects forward slashes even on Windows
    relative_path = os.path.relpath(file_path, webui_real).replace(os.sep, "/")
    response = make_response(send_from_directory(WEBUI, relative_path))

    if filename.endswith((".woff", ".woff2", ".ttf", ".otf", ".svg", ".png", ".jpg", ".jpeg", ".ico",
                          ".css", ".js", ".map")):
        return add_cache_headers(response, max_age=31536000)
    if filename == "index.html":
        return add_cache_headers(response, max_age=300)

    return response


def main():
    port = int(os.environ.get("AGENT_PORT", "5000"))
    ascii_art = r"""
       .--.
    .-(    ).
   (___.__.))
     ' ' ' '
  """
    print(ascii_art)
    print("Ultron web UI starting at http://127.0.0.1:%d" % port)
    if session["mock"] or not config.load_config()["provider"]:
        print("No LLM provider configured -> running in offline MOCK mode. Set one in .env for real use.")
    if CACHING_AVAILABLE:
        backend = "Redis" if USE_REDIS else "in-memory"
        print(f"Response caching enabled ({backend} backend)")
    else:
        print("Flask-Caching not installed - response caching disabled")
    
    warmup_cache()
    host = os.environ.get("AGENT_HOST", "127.0.0.1")
    # Production WSGI server when available (waitress) — Flask dev server as fallback.
    try:
        from waitress import serve
    except ImportError:
        print("waitress not installed - using Flask dev server (pip install waitress for production serving)")
        app.run(host=host, port=port, debug=False, threaded=True)
    else:
        print("Serving with waitress (production WSGI) at http://%s:%d" % (host, port))
        serve(app, host=host, port=port, threads=int(os.environ.get("AGENT_WSGI_THREADS", "8")))


def warmup_cache():
    if not CACHING_AVAILABLE or cache is None:
        return

    try:
        with app.test_client() as client:
            client.get("/")
            endpoints = [
                "/api/skills",
                "/api/recipes",
                "/api/models",
                "/api/voice/voices",
            ]
            for endpoint in endpoints:
                try:
                    client.get(endpoint)
                except Exception:
                    pass
        print("Cache warm-up completed")
    except Exception as e:
        print(f"Cache warm-up skipped: {e}")


if __name__ == "__main__":
    main()