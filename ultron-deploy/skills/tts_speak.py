"""
Text-to-speech skill using pyttsx3.

Dependencies (install once):
    pip install pyttsx3

Linux also needs a TTS engine + voices:
    sudo apt-get install espeak-ng espeak-ng-data   # or festival, speech-dispatcher
    # For British male voice: espeak-ng typically includes 'en-gb' / 'english_rp'
"""

NAME = "tts_speak"
DESCRIPTION = "Convert text to speech using local, open-source pyttsx3 backend."
TRIGGERS = ["speak", "say", "text to speech", "tts", "read aloud"]


def _get_engine():
    """Initialise pyttsx3 engine with sensible defaults."""
    import pyttsx3
    engine = pyttsx3.init()
    engine.setProperty("rate", 185)   # words per minute
    engine.setProperty("volume", 1.0) # 0.0 – 1.0
    return engine


def _list_voices(engine):
    """Return a list of (id, name, languages, gender) tuples."""
    out = []
    for v in engine.getProperty("voices"):
        out.append(
            {
                "id": v.id,
                "name": v.name,
                "languages": getattr(v, "languages", []),
                "gender": getattr(v, "gender", "unknown"),
            }
        )
    return out


def _pick_british_male(engine):
    """
    Try to select a British English male voice.
    Falls back to any English voice, then default.
    """
    voices = _list_voices(engine)

    def langs_gender(v):
        langs = [str(l).lower() for l in v.get("languages", [])]
        return langs, (v.get("gender") or "").lower()

    # Preference: British English male -> English male -> any English
    for check, want_gender in (
        (lambda langs: any("en" in l and ("gb" in l or "uk" in l or "british" in l) for l in langs), True),
        (lambda langs: any("en" in l for l in langs), True),
        (lambda langs: any("en" in l for l in langs), False),
    ):
        for v in voices:
            langs, gender = langs_gender(v)
            if check(langs) and (gender in ("male", "m") if want_gender else True):
                return v.get("id")
    return None  # use engine default


def run(text: str, voice_id: str | None = None, rate: int | None = None, volume: float | None = None, list_voices: bool = False, save_path: str | None = None) -> str:
    """
    Speak `text` aloud.

    Args:
        text: Text to speak.
        voice_id: Specific voice ID to use (see list_voices=True).
        rate: Speech rate (words per minute).
        volume: 0.0 – 1.0.
        list_voices: If True, return available voices instead of speaking.
        save_path: If provided, write audio to this .wav/.mp3 file instead of playing.

    Returns:
        Status message or voice list.
    """
    engine = _get_engine()

    if rate is not None:
        engine.setProperty("rate", rate)
    if volume is not None:
        engine.setProperty("volume", max(0.0, min(1.0, volume)))

    if list_voices:
        voices = _list_voices(engine)
        lines = ["Available voices:"]
        for v in voices:
            lines.append(f"  • {v.get('id', '?')} — {v.get('name', '?')} — langs: {v.get('languages', [])} — gender: {v.get('gender', 'unknown')}")
        return "\n".join(lines)

    # Auto-pick British male if no voice_id given
    if voice_id is None:
        voice_id = _pick_british_male(engine)
        if voice_id:
            engine.setProperty("voice", voice_id)
    else:
        engine.setProperty("voice", voice_id)

    if save_path:
        engine.save_to_file(text, save_path)
        engine.runAndWait()
        return f"Saved speech to {save_path}"
    else:
        engine.say(text)
        engine.runAndWait()
        return "Done speaking."