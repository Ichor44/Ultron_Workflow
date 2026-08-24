"""Optimized voice output for Ultron.

Two engines:
   - "edge"   : Microsoft Edge online neural TTS via `edge-tts` (default, high quality,
                 needs internet, free, no API key). Lists many voices.
   - "sapi"   : Windows System.Speech (SAPI) offline TTS. Used as a fallback when
                edge-tts is unavailable or the network is down.

The agent's speak behaviour is controlled by settings stored in the config (.env):
   VOICE_ENABLED  : "true"/"false"  (master on/off switch)
   VOICE_ENGINE   : "edge"/"sapi"
   VOICE_NAME     : voice id, e.g. "en-US-AndrewNeural" (edge) or "Microsoft David" (sapi)
   VOICE_RATE     : -10..10 (edge) or words-per-min offset (sapi, -10..10)
   VOICE_VOLUME   : 0..100

Helper functions here stay engine-agnostic; the web UI reads/writes the settings via
config.save_env and calls list_voices()/speak() as needed.

Key optimizations:
- Cached voice listing
- Pre-compiled PowerShell templates
- Reduced temp file overhead
"""

import os
import subprocess
import uuid
import threading
import json
import time
from typing import Dict, List, Optional, Any

# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------
def load_voice_settings():
    """Load voice settings from environment variables."""
    return {
        "enabled": os.environ.get("VOICE_ENABLED", "false").lower() == "true",
        "engine": os.environ.get("VOICE_ENGINE", "edge").lower(),
        "name": os.environ.get("VOICE_NAME", "").strip(),
        "rate": _coerce_int(os.environ.get("VOICE_RATE"), -2),
        "volume": _coerce_int(os.environ.get("VOICE_VOLUME"), 100),
    }


def save_voice_settings(enabled=None, engine=None, name=None, rate=None, volume=None):
    """Persist voice settings to .env via config.save_env."""
    import config
    updates = {}
    if enabled is not None:
        updates["VOICE_ENABLED"] = "true" if enabled else "false"
    for key, val in (("VOICE_ENGINE", engine), ("VOICE_NAME", name),
                     ("VOICE_RATE", rate), ("VOICE_VOLUME", volume)):
        if val is not None:
            updates[key] = str(val)
    if updates:
        config.save_env(updates)
    return load_voice_settings()


def _coerce_int(val, default):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Voice listing with caching
# ---------------------------------------------------------------------------
_voice_cache: Dict[str, List[Dict]] = {}
_voice_cache_lock = threading.Lock()
_voice_cache_ttl = 300.0  # 5 minutes


def list_voices(engine=None, force_refresh=False):
    """Return a list of available voices for the requested engine.
    
    Each entry: {"id": str, "name": str, "gender": str, "locale": str}
    Falls back to SAPI voices if edge-tts is unavailable.
    """
    engine = (engine or os.environ.get("VOICE_ENGINE", "edge")).lower()
    
    cache_key = f"voices:{engine}"
    now = time.time()
    
    if not force_refresh:
        with _voice_cache_lock:
            if cache_key in _voice_cache:
                cached, timestamp = _voice_cache[cache_key]
                if (now - timestamp) < _voice_cache_ttl:
                    return cached
    
    if engine == "sapi":
        result = _list_sapi_voices()
    else:
        try:
            result = _list_edge_voices(force_refresh=force_refresh)
        except Exception:
            result = _list_sapi_voices()
    
    with _voice_cache_lock:
        _voice_cache[cache_key] = (result, now)
    
    return result


def _list_edge_voices(force_refresh=False):
    import asyncio
    try:
        import edge_tts
    except Exception:
        raise

    cache_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".voice_cache_edge.json")
    cache_file = os.path.abspath(cache_file)
    
    if not force_refresh and os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    async def _fetch():
        vs = await edge_tts.list_voices()
        return [{
            "id": v["ShortName"],
            "name": v["FriendlyName"],
            "gender": v.get("Gender", ""),
            "locale": v.get("Locale", ""),
        } for v in vs]

    out = asyncio.run(_fetch())
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(out, f)
    except Exception:
        pass
    return out


def _list_sapi_voices():
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$s.GetInstalledVoices() | ForEach-Object { "
        "$v = $_.VoiceInfo; "
        "Write-Output ($v.Name + '|' + $v.Gender + '|' + $v.Culture.Name) "
        "}; "
        "$s.Dispose();"
    )
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30,
        )
        out = []
        for line in res.stdout.decode("utf-8", "ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("|")
            out.append({
                "id": parts[0],
                "name": parts[0],
                "gender": parts[1] if len(parts) > 1 else "",
                "locale": parts[2] if len(parts) > 2 else "",
            })
        return out
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Speaking
# ---------------------------------------------------------------------------
def speak(text, engine=None, voice=None, rate=None, volume=None, max_chars=1000):
    """Speak `text` aloud. Returns True if audio was produced, False otherwise.

    Honours the master on/off switch (VOICE_ENABLED).
    """
    settings = load_voice_settings()
    if not settings["enabled"]:
        return False

    engine = engine or settings["engine"]
    voice = voice or settings["name"]
    rate = rate if rate is not None else settings["rate"]
    volume = volume if volume is not None else settings["volume"]

    clean = " ".join(str(text).split())
    if not clean:
        return False
    if len(clean) > max_chars:
        clean = clean[:max_chars] + " ... (truncated)"

    if engine == "sapi":
        return _speak_sapi(clean, voice, rate, volume)
    try:
        return _speak_edge(clean, voice, rate, volume)
    except Exception:
        # Graceful fallback so the butler still speaks.
        return _speak_sapi(clean, voice, rate, volume)


# Pre-compiled PowerShell templates for SAPI
_SAPI_VOICE_TEMPLATE = (
    "Add-Type -AssemblyName System.Speech; "
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    "{voice_clause}"
    "$s.Rate = {rate}; $s.Volume = {volume}; "
    "$s.Speak('[xml] <speak version=\"1.0\">{text}</speak>'); "
    "$s.Dispose();"
)


def _speak_sapi(text, voice, rate, volume):
    """Speak using Windows SAPI."""
    # Escape single quotes for PowerShell single-quoted strings by doubling them
    safe = text.replace("'", "''")
    voice_clause = '$s.SelectVoice("%s"); ' % voice.replace('"', "") if voice else ""
    ps = _SAPI_VOICE_TEMPLATE.format(
        voice_clause=voice_clause,
        rate=rate,
        volume=volume,
        text=safe
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90,
        )
        return True
    except Exception:
        return False


def _speak_edge(text, voice, rate, volume):
    """Speak using Microsoft Edge online TTS."""
    import asyncio
    import edge_tts

    if not voice:
        voice = "en-US-AndrewNeural"

    # edge-tts rate is a percent string
    pct = max(-100, min(100, int(rate) * 10))
    rate_str = "%+d%%" % pct
    # Map volume 0-100 to edge-tts range -100 to +100
    vol_pct = max(0, min(100, int(volume)))
    vol_str = "%+d%%" % (vol_pct * 2 - 100)

    async def _say():
        comm = edge_tts.Communicate(text, voice, rate=rate_str, volume=vol_str)
        # Use unique temp file to avoid concurrency conflicts
        tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output", "agent_voice_%s.mp3" % uuid.uuid4().hex[:8])
        tmp = os.path.abspath(tmp)

        os.makedirs(os.path.dirname(tmp), exist_ok=True)

        with open(tmp, "wb") as f:
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
        try:
            _play(tmp)
        finally:
            # Clean up temp file after playing
            try:
                os.remove(tmp)
            except Exception:
                pass

    asyncio.run(_say())
    return True


def _play(path):
    """Play an audio file using Windows media player.
    
    On Windows, uses PowerShell's SoundPlayer to play the audio in the background
    without opening any visible media player window. Falls back to os.startfile
    only if the direct approach fails.
    """
    try:
        safe_path = path.replace("'", "''")
        ps = "(New-Object Media.SoundPlayer '%s').PlaySync();" % safe_path
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120,
        )
        return
    except Exception:
        pass
    
    # Fallback: use startfile
    try:
        os.startfile(path) if hasattr(os, "startfile") else subprocess.Popen(
            ["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except Exception:
        pass