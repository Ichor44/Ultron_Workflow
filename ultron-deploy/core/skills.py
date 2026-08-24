"""Optimized skill management with caching and indexing.

Provides high-performance skill loading, execution, and matching
with LRU caching, inverted index for trigger matching, and
batched operations.

Also integrates the Skill Sandbox and API Gateway for production‑grade
isolated and guarded execution.
"""

import glob
import importlib.util
import logging
import os
import re
import threading
import ast
import json
from typing import Any, Callable, Dict, List, Optional, Set, Union

from core.cache import get_cache_manager, cached_skill, monitor

# Lazy imports for sandbox/gateway/memory — may fail if optional deps missing
SandboxedSkill = None
gateway = None
SemanticMemory = None

def _ensure_sandbox():
    global SandboxedSkill
    if SandboxedSkill is None:
        from core.sandbox import SandboxedSkill as _SS
        SandboxedSkill = _SS
    return SandboxedSkill

def _ensure_gateway():
    global gateway
    if gateway is None:
        from core.api_gateway import gateway as _gw
        gateway = _gw
    return gateway

def _ensure_semantic_memory():
    global SemanticMemory
    if SemanticMemory is None:
        from core.semantic_memory import SemanticMemory as _SM
        SemanticMemory = _SM
    return SemanticMemory

SKILLS_DIR: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "skills")

# Change notification callbacks
_on_change_callbacks: List[Callable[[], None]] = []

# Inverted index for fast trigger matching
_trigger_index: Dict[str, Set[str]] = {}  # trigger_word -> set of skill names
_skill_metadata: Dict[str, Dict[str, Any]] = {}    # skill_name -> {description, triggers, name}
_index_lock: threading.RLock = threading.RLock()
_index_built: bool = False
_LOGGER = logging.getLogger(__name__)


def ensure_dirs() -> None:
    """Ensure the skills directory exists."""
    os.makedirs(SKILLS_DIR, exist_ok=True)


def register_on_change(callback: Callable[[], None]) -> None:
    """Register a callback to be called when skills change.
    
    Args:
        callback: Function to call when skills are modified.
    """
    if callback not in _on_change_callbacks:
        _on_change_callbacks.append(callback)


def _notify_change() -> None:
    """Notify all registered callbacks of skill changes."""
    for cb in _on_change_callbacks:
        try:
            cb()
        except Exception:
            pass
    # Invalidate cache on change
    get_cache_manager().invalidate('skills')


def _skill_path(name: str) -> str:
    """Get the file path for a skill module.
    
    Args:
        name: Skill name.
        
    Returns:
        Full path to the skill's Python file.
    """
    safe: str = "".join(c if (c.isalnum() or c == "_") else "_" for c in name)
    return os.path.join(SKILLS_DIR, safe + ".py")


def skill_path(name: str) -> str:
    """Get the file path for a skill module (public API).
    
    Args:
        name: Skill name.
        
    Returns:
        Full path to the skill's Python file.
    """
    return _skill_path(name)


def _build_trigger_index() -> None:
    """Build inverted index for fast trigger matching."""
    global _trigger_index, _skill_metadata, _index_built
    
    with _index_lock:
        if _index_built:
            return
        
        _trigger_index.clear()
        _skill_metadata.clear()
        
        ensure_dirs()
        for path in glob.glob(os.path.join(SKILLS_DIR, "*.py")):
            name: str = os.path.splitext(os.path.basename(path))[0]
            if name == "__init__":
                continue
            meta: Optional[Dict[str, Any]] = _load_meta_fast(path)
            if meta:
                _skill_metadata[name] = meta
                triggers: List[str] = meta.get("TRIGGERS", [])
                description: str = meta.get("DESCRIPTION", "")
                skill_name: str = meta.get("NAME", name)
                
                # Index trigger words
                for trigger in triggers:
                    if trigger:
                        words: List[str] = _tokenize(trigger.lower())
                        for word in words:
                            if len(word) > 2:
                                _trigger_index.setdefault(word, set()).add(name)
                
                # Index description words
                if description:
                    words = _tokenize(description.lower())
                    for word in words:
                        if len(word) > 3:
                            _trigger_index.setdefault(word, set()).add(name)
                
                # Index skill name
                name_words: List[str] = _tokenize(skill_name.lower())
                for word in name_words:
                    if len(word) > 2:
                        _trigger_index.setdefault(word, set()).add(name)
        
        _index_built = True


def _tokenize(text: str) -> List[str]:
    """Fast tokenization - split on non-alphanumeric."""
    return re.findall(r'[a-z0-9]+', text.lower())


@cached_skill
@monitor("skills.list_skills")
def list_skills() -> List[Dict[str, Any]]:
    """List all skills with metadata - cached.
    
    Returns:
        List of skill dictionaries with name, description, and triggers.
    """
    ensure_dirs()
    _build_trigger_index()
    
    with _index_lock:
        result: List[Dict[str, Any]] = []
        for name, meta in _skill_metadata.items():
            result.append({
                "name": name,
                "description": meta.get("DESCRIPTION", ""),
                "triggers": meta.get("TRIGGERS", []),
            })
        return result


@cached_skill
def read_skill(name: str) -> Optional[str]:
    """Read skill source code - cached.
    
    Args:
        name: Skill module name.
        
    Returns:
        Skill source code as a string, or None if not found.
    """
    path: str = _skill_path(name)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _load_meta_fast(path: str) -> Optional[Dict[str, Any]]:
    """Fast metadata loading without full module execution.
    
    Args:
        path: Path to the skill Python file.
        
    Returns:
        Dictionary with NAME, DESCRIPTION, and TRIGGERS, or None on error.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            src: str = f.read()
        
        # Fast regex extraction for metadata
        meta: Dict[str, Any] = {}
        
        # Extract NAME
        m: Optional[re.Match] = re.search(r'^NAME\s*=\s*["\']([^"\']+)["\']', src, re.MULTILINE)
        if m:
            meta["NAME"] = m.group(1)
        
        # Extract DESCRIPTION
        m = re.search(r'^DESCRIPTION\s*=\s*["\']([^"\']+)["\']', src, re.MULTILINE)
        if m:
            meta["DESCRIPTION"] = m.group(1)
        
        # Extract TRIGGERS
        m = re.search(r'^TRIGGERS\s*=\s*(\[.*?\])', src, re.MULTILINE | re.DOTALL)
        if m:
            try:
                meta["TRIGGERS"] = ast.literal_eval(m.group(1))
            except Exception:
                meta["TRIGGERS"] = []
        else:
            meta["TRIGGERS"] = []
        
        return meta
    except Exception:
        return None


def _load_meta(path: str) -> Dict[str, Any]:
    """Load metadata by executing the module (fallback for complex skills).
    
    Args:
        path: Path to the skill Python file.
        
    Returns:
        Dictionary with NAME, DESCRIPTION, and TRIGGERS.
    """
    meta: Dict[str, Any] = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            src: str = f.read()
        ns: Dict[str, Any] = {}
        exec(compile(src, path, "exec"), ns)
        meta["NAME"] = ns.get("NAME", "")
        meta["DESCRIPTION"] = ns.get("DESCRIPTION", "")
        meta["TRIGGERS"] = ns.get("TRIGGERS", [])
    except Exception:
        pass
    return meta


@monitor("skills.load_skill")
def load_skill(name: str) -> Optional[Any]:
    """Load skill module - not cached as modules may have state.
    
    Args:
        name: Skill module name.
        
    Returns:
        Loaded module, or None if not found.
    """
    path: str = _skill_path(name)
    if not os.path.exists(path):
        return None
    try:
        spec: Any = importlib.util.spec_from_file_location("skill_" + name, path)
        module: Any = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        # A skill with an import-time error must not crash the agent
        return None


@monitor("skills.execute_skill")
def execute_skill(name: str, args: Optional[Dict[str, Any]] = None) -> str:
    """Execute a skill by name with arguments, respecting sandbox isolation
    and gateway‑mediated external calls.
    
    The flow:
    1. Load the skill module.
    2. Read its ``PERMISSIONS`` set (if present).
    3. Validate those permissions against the global whitelist (SandboxedSkill).
    4. Run the skill's ``run()`` inside the sandbox (subprocess with resource limits).
    5. On success, store a summary of the result in semantic memory.
    6. Return the string result (or error message).
    
    Args:
        name: Skill module name.
        args: Optional arguments to pass to the skill's run() function.
        
    Returns:
        Skill execution result as a string.
    """
    from core.semantic_memory import SemanticMemory as _SM
    # ------------------------------------------------------------------
    # 1️⃣ Load the skill module
    # ------------------------------------------------------------------
    module: Optional[Any] = load_skill(name)
    if module is None:
        return "Skill '%s' not found or not approved yet." % name
    # ------------------------------------------------------------------
    # 2️⃣ Determine requested permissions
    # ------------------------------------------------------------------
    # Skills may declare a ``PERMISSIONS`` attribute (a set of strings).
    # The sandbox will only allow those that are in the global whitelist.
    requested_perms: List[str] = getattr(module, "PERMISSIONS", [])
    # ------------------------------------------------------------------
    # 3️⃣ Validate permissions – will raise PermissionError if invalid
    # ------------------------------------------------------------------
    try:
        _SS = _ensure_sandbox()
        valid_perms = _SS.validate_permissions(requested_perms)
    except PermissionError as pe:
        return "Skill '%s' has invalid permissions: %s" % (name, pe)
    except Exception as e:
        # Sandbox unavailable — fall back to direct execution
        valid_perms = requested_perms
        _SS = None
    # ------------------------------------------------------------------
    # 4️⃣ Run the skill inside the sandbox (or directly if sandbox unavailable)
    # ------------------------------------------------------------------
    if _SS is not None:
        try:
            result_any, metadata = _SS.run(
                skill_name=name,
                permissions=valid_perms,
                kwargs=args or {},
                timeout=60,
                memory_mib=512,
                cpu_seconds=10,
                skill_path=_skill_path(name),
            )
            result_str = json.dumps(result_any) if isinstance(result_any, (dict, list)) else str(result_any)
        except Exception as e:
            return "Skill '%s' failed in sandbox: %s" % (name, e)
    else:
        # Direct execution fallback — no sandbox isolation
        try:
            handler = getattr(module, "run", None) or getattr(module, "handler", None)
            if handler is None:
                return "Skill '%s' has no run() or handler() function." % name
            result_any = handler(**(args or {}))
            result_str = json.dumps(result_any) if isinstance(result_any, (dict, list)) else str(result_any)
        except Exception as e:
            return "Skill '%s' failed: %s" % (name, e)
    # ------------------------------------------------------------------
    # 5️⃣ Store a summary in semantic memory (helps future queries)
    # ------------------------------------------------------------------
    try:
        _SM_cls = _ensure_semantic_memory()
        sm = _SM_cls()
        sm.add_text(
            result_str,
            metadata={
                "source": "skill_execution",
                "skill_name": name,
                "elapsed": metadata.get("duration", "") if 'metadata' in dir() else "",
                "exit_code": metadata.get("exit_code", "") if 'metadata' in dir() else "",
            },
        )
    except Exception:
        _LOGGER.debug("Failed to store skill result in semantic memory", exc_info=True)
    # ------------------------------------------------------------------
    # 6️⃣ Return the string result
    # ------------------------------------------------------------------
    return result_str


def write_skill(name: str, code: str) -> str:
    """Write a skill file and notify change callbacks.
    
    Args:
        name: Skill module name.
        code: Python source code for the skill.
        
    Returns:
        Path to the written skill file.
    """
    ensure_dirs()
    path: str = _skill_path(name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(code)
    
    # Invalidate index and cache
    global _index_built
    with _index_lock:
        _index_built = False
    _notify_change()
    return path


def _score_skills(query: str) -> Dict[str, int]:
    """Score all skills against a query using the inverted index."""
    _build_trigger_index()
    query_words = _tokenize(query.lower())
    if not query_words:
        return {}

    with _index_lock:
        scores: Dict[str, int] = {}
        for word in query_words:
            if word in _trigger_index:
                for skill_name in _trigger_index[word]:
                    scores[skill_name] = scores.get(skill_name, 0) + 1

        # Boost exact trigger matches
        for skill_name, meta in _skill_metadata.items():
            for trigger in meta.get("TRIGGERS", []):
                if trigger.lower() in query.lower():
                    scores[skill_name] = scores.get(skill_name, 0) + 5
        return scores


def find_skill_by_trigger(query: str, threshold: int = 2) -> Optional[str]:
    """Fast skill lookup using inverted index.

    Args:
        query: User query to match against triggers
        threshold: Minimum score to consider a match

    Returns:
        Best matching skill name or None
    """
    scores = _score_skills(query)
    if not scores:
        return None

    best_skill = max(scores.items(), key=lambda x: x[1])
    if best_skill[1] >= threshold:
        return best_skill[0]

    return None


def search_skills(query: str, top_k: int = 5) -> List[Dict]:
    """Search skills by query using inverted index.

    Args:
        query: Search query
        top_k: Number of results to return

    Returns:
        List of skill dicts sorted by relevance
    """
    scores = _score_skills(query)
    if not scores:
        return []

    with _index_lock:
        # Boost exact name matches
        for skill_name, meta in _skill_metadata.items():
            if meta.get("NAME", "").lower() in query.lower():
                scores[skill_name] = scores.get(skill_name, 0) + 3

        sorted_skills = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        return [{
            "name": skill_name,
            "description": _skill_metadata.get(skill_name, {}).get("DESCRIPTION", ""),
            "triggers": _skill_metadata.get(skill_name, {}).get("TRIGGERS", []),
            "score": score,
        } for skill_name, score in sorted_skills]


def rebuild_index() -> None:
    """Force rebuild of the trigger index."""
    global _index_built
    with _index_lock:
        _index_built = False
    _build_trigger_index()