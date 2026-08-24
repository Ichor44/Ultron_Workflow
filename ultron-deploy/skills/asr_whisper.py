"""
Local on-device speech-to-text via whisper.cpp + MinGW + Rust.
Captures microphone audio with sounddevice, transcribes via whisper-cli.

Setup (one-time, run from PowerShell as admin or user):
    powershell -ExecutionPolicy Bypass -File tools\\whisper-cli\\setup.ps1

That script installs MinGW-w64 (w64devkit, ~35 MB), Rust (gnu target),
downloads a whisper.cpp GGML model (~75 MB), and builds whisper-cli.exe.

Dependencies (pip install):
    pip install sounddevice numpy
"""

import json
import os
import subprocess
import tempfile
import wave

NAME = "asr_whisper"
DESCRIPTION = "Transcribe speech from microphone using local whisper.cpp (no cloud, no Visual Studio, ~minutes setup)."
TRIGGERS = ["transcribe", "speech to text", "stt", "asr", "whisper", "dictate", "voice typing", "record", "mic"]

# ── Paths (relative to the AGENT root) ─────────────────────────────────
_AGENT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WHISPER_CLI = os.path.join(_AGENT_ROOT, "tools", "whisper-cli", "target", "x86_64-pc-windows-gnu", "release", "whisper-cli.exe")
# Fallback for native-target builds
if not os.path.exists(_WHISPER_CLI):
    _WHISPER_CLI = os.path.join(_AGENT_ROOT, "tools", "whisper-cli", "target", "release", "whisper-cli.exe")
_MODEL_DIR = os.path.join(_AGENT_ROOT, "tools", "whisper-cli", "models")
_DEFAULT_MODEL = os.path.join(_MODEL_DIR, "ggml-tiny.en.bin")


def _glob_models():
    """Any ggml model in the models dir (last-resort search)."""
    import glob as _glob
    models = _glob.glob(os.path.join(_MODEL_DIR, "ggml-*.bin"))
    return os.path.abspath(models[0]) if models else None


def _find_model(model_path=None):
    """Resolve model path, falling back to default or env var."""
    if model_path and os.path.exists(model_path):
        return os.path.abspath(model_path)
    env_model = os.environ.get("WHISPER_MODEL")
    if env_model and os.path.exists(env_model):
        return os.path.abspath(env_model)
    if os.path.exists(_DEFAULT_MODEL):
        return _DEFAULT_MODEL
    return _glob_models()


def _check_setup():
    """Return a helpful status string if setup is incomplete."""
    issues = []
    if not os.path.exists(_WHISPER_CLI):
        issues.append(
            f"whisper-cli not found at {_WHISPER_CLI}. "
            f"Run: powershell -ExecutionPolicy Bypass -File \"{os.path.join(_AGENT_ROOT, 'tools', 'whisper-cli', 'setup.ps1')}\""
        )
    model = _find_model()
    if not model:
        issues.append(
            f"No whisper model found in {_MODEL_DIR}. "
            f"Run the setup script above, or manually download a .bin model."
        )
    # Check sounddevice
    try:
        import sounddevice as sd  # noqa: F401
    except ImportError:
        issues.append("sounddevice not installed. Run: pip install sounddevice numpy")
    return issues


def _record_audio(duration=5, samplerate=16000, device=None):
    """Record from microphone, return (pcm_int16, samplerate)."""
    import numpy as np
    import sounddevice as sd

    # Use default input device if none specified
    if device is not None:
        sd.default.device = (device, None)

    # Ensure we're at 16kHz mono
    recording = sd.rec(
        int(duration * samplerate),
        samplerate=samplerate,
        channels=1,
        dtype="float32",
        blocking=True,
    )
    # Convert f32 [-1,1] → int16 for WAV
    pcm = (np.clip(recording, -1.0, 1.0) * 32767).astype(np.int16)
    return pcm.flatten(), samplerate


def _save_wav(pcm_int16, samplerate, path):
    """Write int16 PCM to a WAV file."""
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(samplerate)
        wf.writeframes(pcm_int16.tobytes())
    return path


def run(
    duration: int | str = 5,
    model: str | None = None,
    input_device: int | None = None,
    audio_file: str | None = None,
    list_devices: bool = False,
    **kwargs,
) -> str:
    """
    Transcribe speech from microphone (or a WAV file) using local whisper.cpp.

    Args:
        duration: Recording length in seconds (default 5). Ignored if audio_file is given.
        model:   Path to a GGML whisper model. Uses default if omitted.
        input_device: Index of the input microphone (see list_devices=True).
        audio_file: Optional path to an existing WAV file to transcribe instead of recording.
        list_devices: If True, list available audio input devices and return.

    Returns:
        Transcribed text, or device list, or error message.
    """
    # ── Check setup ───────────────────────────────────────────────────
    issues = _check_setup()
    if issues:
        return (
            "⚠️  ASR setup incomplete:\n" + "\n".join(f"  • {m}" for m in issues)
        )

    # ── List audio devices ────────────────────────────────────────────
    if list_devices:
        try:
            import sounddevice as sd
        except ImportError:
            return "sounddevice not installed. Run: pip install sounddevice numpy"
        devices = sd.query_devices()
        lines = ["Available audio input devices:"]
        for i, dev in enumerate(devices):
            if dev["max_input_channels"] > 0:
                lines.append(f"  [{i}] {dev['name']}  (ch={dev['max_input_channels']}, sr={dev['default_samplerate']:.0f} Hz)")
        return "\n".join(lines)

    # ── Resolve model ─────────────────────────────────────────────────
    model_path = _find_model(model)
    if not model_path:
        return (
            "No whisper model found. "
            f"Download one to {_MODEL_DIR} (e.g. ggml-tiny.en.bin from "
            "https://huggingface.co/ggerganov/whisper.cpp)."
        )

    # ── Get audio ─────────────────────────────────────────────────────
    tmp_wav = None
    try:
        if audio_file:
            # Transcribe an existing file
            wav_path = os.path.abspath(audio_file)
            if not os.path.exists(wav_path):
                return f"Audio file not found: {wav_path}"
        else:
            # Record from mic
            try:
                dur = int(duration)
            except (ValueError, TypeError):
                dur = 5
            if dur < 1:
                dur = 5
            if dur > 120:
                dur = 120

            try:
                pcm, sr = _record_audio(duration=dur, samplerate=16000, device=input_device)
            except Exception as e:
                return f"Microphone recording failed: {e}"

            tmp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp_wav.close()
            _save_wav(pcm, sr, tmp_wav.name)
            wav_path = tmp_wav.name

        # ── Run whisper-cli ───────────────────────────────────────────
        result = subprocess.run(
            [_WHISPER_CLI, model_path, wav_path],
            capture_output=True,
            text=True,
            timeout=300,  # 5 min timeout for long audio
        )

        if result.returncode != 0:
            err = result.stderr.strip() or f"exit code {result.returncode}"
            return f"whisper-cli failed: {err}"

        transcript = result.stdout.strip()
        if not transcript:
            return "(no speech detected — the model returned an empty transcript)"
        return transcript

    except subprocess.TimeoutExpired:
        return "whisper-cli timed out (audio too long?)."
    except FileNotFoundError:
        return (
            f"whisper-cli not found at {_WHISPER_CLI}. "
            f"Run the setup script to build it."
        )
    except Exception as e:
        return f"ASR error: {e}"
    finally:
        # Clean up temp file
        if tmp_wav and os.path.exists(tmp_wav.name):
            try:
                os.unlink(tmp_wav.name)
            except Exception:
                pass


# ── CLI entry point (for testing standalone) ───────────────────────────
if __name__ == "__main__":
    import sys
    if "--list-devices" in sys.argv:
        print(run(list_devices=True))
    elif len(sys.argv) > 1 and sys.argv[1].endswith(".wav"):
        print(run(audio_file=sys.argv[1]))
    else:
        dur = int(sys.argv[1]) if len(sys.argv) > 1 else 5
        print(f"Recording for {dur} seconds... (speak now)", file=sys.stderr)
        print(run(duration=dur))
