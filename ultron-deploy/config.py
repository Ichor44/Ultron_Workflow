"""Optimized configuration management with caching.

Provides high-performance config loading with LRU caching,
environment variable parsing, and change notifications.
"""

import os
import threading
from typing import Dict, Any, Optional

from core.cache import get_cache_manager, cached_config, monitor

# Change notification callbacks
_on_change_callbacks = []
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
_env_path = os.path.abspath(_env_path)

# In-memory config cache
_config_cache: Optional[Dict[str, Any]] = None
_cache_lock = threading.RLock()


def register_on_change(callback):
    """Register a callback to be called when config changes."""
    if callback not in _on_change_callbacks:
        _on_change_callbacks.append(callback)


def _notify_change():
    for cb in _on_change_callbacks:
        try:
            cb()
        except Exception:
            pass
    # Invalidate cache
    global _config_cache
    with _cache_lock:
        _config_cache = None
    get_cache_manager().invalidate('config')


def _load_dotenv_raw():
    """Load .env file into os.environ."""
    if not os.path.exists(_env_path):
        return
    with open(_env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key, val = key.strip(), val.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = val


@cached_config
@monitor("config.load_config")
def load_config():
    """Load configuration from environment - cached."""
    global _config_cache

    with _cache_lock:
        if _config_cache is not None:
            return _config_cache

    _load_dotenv_raw()

    provider = os.environ.get("AGENT_LLM_PROVIDER", "").lower()
    openai_key = os.environ.get("OPENAI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    custom_key = os.environ.get("CUSTOM_API_KEY")

    if not provider:
        if openrouter_key:
            provider = "openrouter"
        elif openai_key:
            provider = "openai"
        elif anthropic_key:
            provider = "anthropic"
        elif custom_key:
            provider = "custom"

    # Normalize local OpenAI-compatible providers (ollama/lmstudio) into the
    # "custom" provider family so the engine actually supports them. The web UI
    # exposes these as selectable providers, so they must map to a working path.
    if provider == "ollama":
        custom_base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        custom_api_key = os.environ.get("OLLAMA_API_KEY", "no-key")
        custom_model = os.environ.get("OLLAMA_MODEL", "")
    elif provider == "lmstudio":
        custom_base_url = os.environ.get("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
        custom_api_key = os.environ.get("LMSTUDIO_API_KEY", "no-key")
        custom_model = os.environ.get("LMSTUDIO_MODEL", "")
    else:
        custom_base_url = os.environ.get("CUSTOM_BASE_URL", "http://localhost:11434/v1")
        custom_api_key = custom_key
        custom_model = os.environ.get("CUSTOM_MODEL", "")

    config = {
        "provider": provider,
        "openai_api_key": openai_key,
        "openai_base_url": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "openai_model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        "anthropic_api_key": anthropic_key,
        "anthropic_model": os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"),
        "openrouter_api_key": openrouter_key,
        "openrouter_base_url": os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        "openrouter_model": os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
        "openrouter_site": os.environ.get("OPENROUTER_SITE", "https://localhost/agent"),
        "openrouter_title": os.environ.get("OPENROUTER_TITLE", "Ultron"),
        "custom_api_key": custom_api_key,
        "custom_base_url": custom_base_url,
        "custom_model": custom_model,
        "custom_name": os.environ.get("CUSTOM_NAME", "My Custom Model"),
    }

    with _cache_lock:
        _config_cache = config

    return config


def get_all_models():
    """Get a list of all configured models."""
    cfg = load_config()
    models = []
    
    if cfg["openrouter_api_key"]:
        models.append({
            "provider": "openrouter",
            "model": cfg["openrouter_model"],
            "name": "OpenRouter: %s" % cfg["openrouter_model"],
            "active": cfg["provider"] == "openrouter",
        })
    
    if cfg["openai_api_key"]:
        models.append({
            "provider": "openai",
            "model": cfg["openai_model"],
            "name": "OpenAI: %s" % cfg["openai_model"],
            "active": cfg["provider"] == "openai",
        })
    
    if cfg["anthropic_api_key"]:
        models.append({
            "provider": "anthropic",
            "model": cfg["anthropic_model"],
            "name": "Anthropic: %s" % cfg["anthropic_model"],
            "active": cfg["provider"] == "anthropic",
        })
    
    if cfg["custom_api_key"] and cfg["custom_model"]:
        models.append({
            "provider": "custom",
            "model": cfg["custom_model"],
            "name": "%s: %s" % (cfg["custom_name"], cfg["custom_model"]),
            "active": cfg["provider"] == "custom",
        })
    
    return models


def add_custom_model(name, base_url, api_key, model):
    """Add a custom OpenAI-compatible model."""
    updates = {
        "CUSTOM_NAME": name,
        "CUSTOM_BASE_URL": base_url,
        "CUSTOM_API_KEY": api_key,
        "CUSTOM_MODEL": model,
        "AGENT_LLM_PROVIDER": "custom",
    }
    save_env(updates)
    return True


def remove_custom_model():
    """Remove the custom model configuration."""
    updates = {
        "CUSTOM_NAME": "",
        "CUSTOM_BASE_URL": "",
        "CUSTOM_API_KEY": "",
        "CUSTOM_MODEL": "",
    }
    # Only switch provider if currently on custom
    if os.environ.get("AGENT_LLM_PROVIDER") == "custom":
        # Try to switch to another available provider
        openrouter_key = os.environ.get("OPENROUTER_API_KEY")
        openai_key = os.environ.get("OPENAI_API_KEY")
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        
        if openrouter_key:
            updates["AGENT_LLM_PROVIDER"] = "openrouter"
        elif openai_key:
            updates["AGENT_LLM_PROVIDER"] = "openai"
        elif anthropic_key:
            updates["AGENT_LLM_PROVIDER"] = "anthropic"
        else:
            updates["AGENT_LLM_PROVIDER"] = "mock"
    
    save_env(updates)
    return True


def save_env(updates: Dict[str, str]):
    """Save environment variables to .env file."""
    lines = []
    if os.path.exists(_env_path):
        with open(_env_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()

    # Build key->index mapping, keeping track of ALL indices for each key
    # to properly handle duplicate keys
    key_indices: Dict[str, List[int]] = {}
    for i, line in enumerate(lines):
        if "=" in line:
            k = line.strip().split("=", 1)[0].strip()
            if k:
                key_indices.setdefault(k, []).append(i)

    for k, v in updates.items():
        # Validate key and value to prevent .env corruption
        if "\n" in k or "\r" in k:
            raise ValueError("Environment variable key cannot contain newlines")
        # Replace newlines in values to prevent .env corruption
        v = v.replace("\n", " ").replace("\r", " ")
        text = "%s=%s" % (k, v)
        if k in key_indices:
            # Update the last occurrence and remove any earlier duplicates
            indices = key_indices[k]
            lines[indices[-1]] = text
            # Remove earlier duplicate lines (iterate in reverse to preserve indices)
            for idx in reversed(indices[:-1]):
                lines.pop(idx)
            # Rebuild indices since we modified the list
            key_indices = {}
            for i, line in enumerate(lines):
                if "=" in line:
                    kk = line.strip().split("=", 1)[0].strip()
                    if kk:
                        key_indices.setdefault(kk, []).append(i)
        else:
            lines.append(text)

    with open(_env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    os.environ.update(updates)
    _notify_change()


def get_env(key: str, default: str = "") -> str:
    """Get environment variable with default."""
    return os.environ.get(key, default)


def set_env(key: str, value: str):
    """Set environment variable and persist to .env."""
    save_env({key: value})