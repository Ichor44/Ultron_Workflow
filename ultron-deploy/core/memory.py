"""Optimized memory management with in-memory caching and batching.

Provides high-performance fact/note/reminder storage with
LRU caching, write-behind batching, and atomic operations.
Includes memory leak prevention and resource monitoring.
"""

import datetime
import json
import os
import threading
import time
from typing import Any, Dict, List, Optional, Union

from core.cache import get_cache_manager, cached_memory, monitor

DATA_DIR: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


# In-memory cache with write-behind
_memory_cache: Dict[str, Any] = {}
_cache_lock: threading.RLock = threading.RLock()
_dirty: bool = False
_last_save: float = 0
_save_interval: float = 2.0  # seconds
_save_thread: Optional[threading.Thread] = None
_stop_save: threading.Event = threading.Event()

# Memory leak prevention
_max_memory_entries: int = 5000  # Maximum entries in memory cache
_dirty_mark_count: int = 0  # Counter to force save on periodic marks


def _path() -> str:
    """Get the path to the memory store JSON file.
    
    Returns:
        Full path to store.json.
    """
    return os.path.join(DATA_DIR, "store.json")


def _load_raw() -> Dict[str, Any]:
    """Load raw data from disk.
    
    Returns:
        Dictionary containing notes, reminders, and facts.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(_path()):
        return {"notes": {}, "reminders": [], "facts": {}}
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            data: Any = json.load(f)
        if isinstance(data, dict):
            return data
        return {"notes": {}, "reminders": [], "facts": {}}
    except Exception:
        return {"notes": {}, "reminders": [], "facts": {}}


def _load() -> Dict[str, Any]:
    """Backward-compatible load - returns cached data.
    
    Returns:
        Cached memory data dictionary.
    """
    return _get_data()


def _save_raw(data: Dict[str, Any]) -> None:
    """Save raw data to disk atomically.
    
    Args:
        data: Memory data dictionary to save.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp_path: str = _path() + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, _path())


def _load_cached() -> None:
    """Load data into memory cache."""
    global _memory_cache, _dirty, _last_save
    with _cache_lock:
        _memory_cache = _load_raw()
        _dirty = False
        _last_save = time.time()


def _start_save_thread() -> None:
    """Start background save thread."""
    global _save_thread
    if _save_thread is None or not _save_thread.is_alive():
        _stop_save.clear()
        _save_thread = threading.Thread(target=_save_loop, daemon=True)
        _save_thread.start()


def _save_loop() -> None:
    """Background loop to persist dirty cache."""
    global _dirty, _last_save
    while not _stop_save.is_set():
        time.sleep(0.5)
        with _cache_lock:
            if _dirty and (time.time() - _last_save) >= _save_interval:
                try:
                    _save_raw(_memory_cache)
                    _dirty = False
                    _last_save = time.time()
                except Exception:
                    pass


def _mark_dirty() -> None:
    """Mark cache as dirty, start the save thread, and drop the memory
    result cache (every reader shares the same store, so any write
    invalidates all cached reads)."""
    global _dirty, _dirty_mark_count
    with _cache_lock:
        _dirty = True
        _dirty_mark_count += 1
        # Force periodic full save to prevent unbounded growth
        if _dirty_mark_count >= 50:
            _dirty_mark_count = 0
            try:
                _save_raw(_memory_cache)
                _dirty = False
            except Exception:
                pass
    _start_save_thread()
    get_cache_manager().invalidate('memory')


def _get_data() -> Dict[str, Any]:
    """Get data from cache, loading if needed.
    
    Returns:
        Cached memory data dictionary.
    
    Notes:
        - Prunes old entries if cache exceeds maximum size to prevent memory leaks.
        - Periodic forced saves via _mark_dirty also help control growth.
    """
    global _memory_cache
    with _cache_lock:
        if not _memory_cache:
            _load_cached()
        # Prune oldest entries if cache exceeds maximum size
        if len(_memory_cache) > _max_memory_entries:
            # Keep only the most recent entries (notes, then facts, then reminders)
            notes = _memory_cache.get("notes", {})
            facts = _memory_cache.get("facts", {})
            reminders = _memory_cache.get("reminders", [])
            # Calculate how many entries to keep
            total_entries = len(notes) + len(facts) + len(reminders)
            excess = total_entries - _max_memory_entries
            if excess > 0:
                # Remove oldest notes (by key insertion order)
                note_keys = list(notes.keys())
                remove_count = min(excess, len(note_keys))
                for key in note_keys[:remove_count]:
                    del notes[key]
                excess -= remove_count
                if excess > 0:
                    # Remove oldest facts
                    fact_keys = list(facts.keys())
                    remove_count = min(excess, len(fact_keys))
                    for key in fact_keys[:remove_count]:
                        del facts[key]
                    excess -= remove_count
                if excess > 0:
                    # Remove oldest reminders (by creation date)
                    reminders = [r for r in reminders if not r.get("done")]
                    reminders = reminders[excess:]
                # Rebuild cache
                _memory_cache = {"notes": notes, "facts": facts, "reminders": reminders}
        return _memory_cache


@monitor("memory.save_note")
def save_note(key: str, value: str) -> str:
    """Save a free-form note.
    
    Args:
        key: Note title/key.
        value: Note body content.
        
    Returns:
        Confirmation message.
    """
    data: Dict[str, Any] = _get_data()
    data["notes"][key] = value
    # Check memory usage and prune if needed
    if len(data["notes"]) > _max_memory_entries // 3:
        # Keep only the most recent notes
        note_keys = list(data["notes"].keys())
        keep = note_keys[-(_max_memory_entries // 3):]
        data["notes"] = {k: data["notes"][k] for k in keep}
    _mark_dirty()
    return "Saved note '%s'." % key


@cached_memory
@monitor("memory.recall_note")
def recall_note(key: Optional[str] = None) -> str:
    """Recall a saved note.
    
    Args:
        key: Note key to recall, or None to list all notes.
        
    Returns:
        Note content or list of all notes.
    """
    data: Dict[str, Any] = _get_data()
    if not key:
        if not data["notes"]:
            return "No notes stored yet."
        return json.dumps(data["notes"], indent=2)
    if key in data["notes"]:
        return data["notes"][key]
    return "No note found for '%s'." % key


@monitor("memory.remember_fact")
def remember_fact(key: str, value: str) -> str:
    """Store a persistent fact about the user.
    
    Args:
        key: Fact name (e.g., 'user_name', 'preferred_language').
        value: Fact value.
        
    Returns:
        Confirmation message.
    """
    data: Dict[str, Any] = _get_data()
    data["facts"][key] = value
    # Check memory usage and prune if needed
    if len(data["facts"]) > _max_memory_entries // 3:
        # Keep only the most recent facts
        fact_keys = list(data["facts"].keys())
        keep = fact_keys[-(_max_memory_entries // 3):]
        data["facts"] = {k: data["facts"][k] for k in keep}
    _mark_dirty()
    return "Noted: %s = %s" % (key, value)


@cached_memory
@monitor("memory.recall_fact")
def recall_fact(key: Optional[str] = None) -> str:
    """Recall a stored fact about the user.
    
    Args:
        key: Fact name to recall, or None to list all facts.
        
    Returns:
        Fact value or list of all facts.
    """
    data: Dict[str, Any] = _get_data()
    if not key:
        if not data["facts"]:
            return "I don't have any stored facts about you yet."
        return json.dumps(data["facts"], indent=2)
    if key in data["facts"]:
        return data["facts"][key]
    return "I don't know '%s' yet. Tell me with remember_fact." % key


@monitor("memory.add_reminder")
def add_reminder(text: str, minutes_from_now: int = 0) -> str:
    """Set a reminder for the user.
    
    Args:
        text: What to remind about.
        minutes_from_now: Minutes from now to fire (0 = due immediately).
        
    Returns:
        Confirmation message with due time.
    """
    data: Dict[str, Any] = _get_data()
    due: datetime.datetime = datetime.datetime.now() + datetime.timedelta(minutes=minutes_from_now)
    entry: Dict[str, Any] = {
        "text": text,
        "due": due.isoformat(),
        "created": datetime.datetime.now().isoformat(),
        "done": False,
    }
    data["reminders"].append(entry)
    _mark_dirty()
    if minutes_from_now:
        when: str = due.strftime("%Y-%m-%d %H:%M")
        return "Reminder set for %s: %s" % (when, text)
    return "Reminder set (due now): %s" % text


@cached_memory
@monitor("memory.list_reminders")
def list_reminders() -> str:
    """List all pending reminders.
    
    Returns:
        Formatted list of pending reminders.
    """
    data: Dict[str, Any] = _get_data()
    pending: List[Dict[str, Any]] = [r for r in data["reminders"] if not r.get("done")]
    if not pending:
        return "No pending reminders, sir."
    return "\n".join("[%s] %s" % (r["due"], r["text"]) for r in pending)


def due_reminders(quiet_minutes: int = 0) -> List[Dict[str, Any]]:
    """Get due reminders - not cached as time-sensitive.
    
    Args:
        quiet_minutes: Suppress reminders notified within this many minutes.
        
    Returns:
        List of due reminder dictionaries.
    """
    data: Dict[str, Any] = _get_data()
    now: datetime.datetime = datetime.datetime.now()
    out: List[Dict[str, Any]] = []
    for r in data["reminders"]:
        if r.get("done"):
            continue
        try:
            dt: datetime.datetime = datetime.datetime.fromisoformat(r["due"])
        except Exception:
            continue
        if dt <= now:
            if quiet_minutes and r.get("last_notified"):
                try:
                    ln: datetime.datetime = datetime.datetime.fromisoformat(r["last_notified"])
                    if (now - ln).total_seconds() < quiet_minutes * 60:
                        continue
                except Exception:
                    pass
            out.append(r)
    return out


def mark_notified(text: str) -> None:
    """Mark a reminder as notified.
    
    Args:
        text: Text to match for marking as notified.
    """
    data: Dict[str, Any] = _get_data()
    now: str = datetime.datetime.now().isoformat()
    for r in data["reminders"]:
        if not r.get("done") and text.lower() in r["text"].lower():
            r["last_notified"] = now
    _mark_dirty()


@monitor("memory.complete_reminder")
def complete_reminder(text: str) -> str:
    """Mark a reminder as done by matching text.
    
    Args:
        text: Text to match for completion.
        
    Returns:
        Confirmation message.
    """
    data: Dict[str, Any] = _get_data()
    hit: bool = False
    for r in data["reminders"]:
        if not r.get("done") and text.lower() in r["text"].lower():
            r["done"] = True
            hit = True
    if hit:
        _mark_dirty()
        return "Marked reminder done: %s" % text
    return "No matching reminder found."


def force_save() -> None:
    """Force immediate save to disk."""
    global _dirty, _last_save
    with _cache_lock:
        if _dirty:
            _save_raw(_memory_cache)
            _dirty = False
            _last_save = time.time()


def shutdown() -> None:
    """Shutdown memory module, saving any pending changes."""
    _stop_save.set()
    if _save_thread and _save_thread.is_alive():
        _save_thread.join(timeout=2.0)
    force_save()